"""Tanítás: időkerethez igazított előtanítás (pretrain) és beszélgetésre hangolás (sft).

- Folytatható: minden futás onnan indul, ahol az előző abbahagyta (checkpoint.pt).
- A `model.pt` mindig a legjobb (legkisebb ellenőrző veszteségű) változat. Ezt használja a TecF Ai.
- Leállítható Ctrl+C-vel vagy a felületről; ilyenkor is ment.
"""
from __future__ import annotations

import json
import math
import threading
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Callable

import numpy as np
import torch

from tecf.llm.hardware import PRESETS, detect, free_gpu_memory, grad_accum, micro_batch
from tecf.llm.model import GPT, GPTConfig


def _load_tokens(root: Path, stage: str, split: str) -> np.memmap:
    meta = json.loads((root / "data" / "meta.json").read_text())
    path = root / "data" / f"{stage}_{split}.bin"
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError(f"Nincs {stage} adat. Futtasd előbb: tecf model corpus, majd tecf model prepare")
    return np.memmap(path, dtype=np.dtype(meta["dtype"]), mode="r")


def _batch(data: np.memmap, block: int, bs: int, device: str) -> tuple[torch.Tensor, torch.Tensor]:
    ix = np.random.randint(0, len(data) - block - 1, bs)
    x = torch.from_numpy(np.stack([data[i:i + block].astype(np.int64) for i in ix]))
    y = torch.from_numpy(np.stack([data[i + 1:i + 1 + block].astype(np.int64) for i in ix]))
    if device == "cuda":
        return x.pin_memory().to(device, non_blocking=True), y.pin_memory().to(device, non_blocking=True)
    return x.to(device), y.to(device)


def train(root: Path, stage: str = "pretrain", minutes: float = 60, preset: str = "auto", new: bool = False,
          log: Callable[[str], None] = print, stop: threading.Event | None = None) -> dict:
    hw = detect()
    device = hw.device
    meta = json.loads((root / "data" / "meta.json").read_text())
    ckpt_path, best_path = root / "checkpoint.pt", root / "model.pt"

    # ---------- modell: folytatás vagy új ----------
    ckpt = None
    if ckpt_path.exists() and not new:
        ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)
        cfg = GPTConfig(**ckpt["config"])
        preset = ckpt["preset"]
    else:
        if preset == "auto":
            from tecf.llm.hardware import choose
            preset, why = choose(hw, meta["pretrain"]["train"])
            log(f"Modellméret: {why}")
        p = dict(PRESETS[preset])
        p["vocab_size"] = (meta["vocab_size"] + 63) // 64 * 64  # 64-re kerekítve: gyorsabb GPU-n
        cfg = GPTConfig(**p)
    model = GPT(cfg)
    if ckpt:
        model.load_state_dict(ckpt["model"])
    if device == "cuda":
        free_gpu_memory(log)
    model.to(device)

    train_data = _load_tokens(root, stage, "train")
    try:
        val_data = _load_tokens(root, stage, "val")
    except RuntimeError:
        val_data = train_data
    block = min(cfg.block_size, len(train_data) - 2, len(val_data) - 2)
    if block < 8:
        raise RuntimeError("Túl kevés a tanítóanyag. Gyűjts többet: tecf model corpus")

    mb = micro_batch(preset, hw)
    accum = grad_accum(preset, mb)
    # sft: kisebb tanulási ráta, hogy a korábban tanultakat ne felejtse el
    peak_lr = {"pretrain": 6e-4 if cfg.n_embd <= 768 else 3e-4, "sft": 5e-5}[stage]
    opt = model.optimizer(peak_lr, 0.1, device)
    same_stage = ckpt is not None and ckpt.get("stage") == stage
    if same_stage and "optimizer" in ckpt:
        opt.load_state_dict(ckpt["optimizer"])
    step = ckpt["step"] if ckpt else 0
    best_val = ckpt.get("best_val", float("inf")) if same_stage else float("inf")
    tokens_seen = ckpt.get("tokens_seen", 0) if ckpt else 0

    if device == "cuda":
        dtype = torch.bfloat16 if hw.bf16 else torch.float16
        amp = torch.autocast("cuda", dtype=dtype)
        scaler = torch.amp.GradScaler("cuda", enabled=dtype == torch.float16)
        torch.backends.cuda.matmul.allow_tf32 = True
    else:
        amp, scaler = nullcontext(), None

    log(f"Tanítás [{stage}] – {preset} modell, {model.num_params() / 1e6:.1f}M paraméter, eszköz: {device}\n"
        f"  adat: {len(train_data) / 1e6:.2f}M token, kontextus {block}, köteg {mb}×{accum}, időkeret {minutes} perc")

    @torch.no_grad()
    def evaluate(iters: int = 20) -> float:
        model.eval()
        losses = []
        for _ in range(iters):
            x, y = _batch(val_data, block, mb, device)
            with amp:
                losses.append(model(x, y)[1].item())
        model.train()
        return float(np.mean(losses))

    def save(val: float) -> None:
        state = {"model": model.state_dict(), "optimizer": opt.state_dict(), "config": cfg.to_dict(),
                 "preset": preset, "stage": stage, "step": step, "best_val": best_val, "tokens_seen": tokens_seen}
        torch.save(state, ckpt_path)
        if val <= best_val:
            torch.save({"model": model.state_dict(), "config": cfg.to_dict(), "stage": stage, "val_loss": val,
                        "step": step}, best_path)

    budget = minutes * 60
    start = last_eval = time.time()
    eval_every = max(30.0, min(300.0, budget / 10))
    warm = 0.05
    history = []
    model.train()
    try:
        while True:
            frac = (time.time() - start) / budget
            if frac >= 1 or (stop is not None and stop.is_set()):
                break
            # tanulási ráta: bemelegítés, majd koszinusz lecsengés az időkeret végéig
            lr = peak_lr * (frac / warm if frac < warm else 0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * (frac - warm) / (1 - warm))))
            for g in opt.param_groups:
                g["lr"] = lr
            loss_acc = 0.0
            for _ in range(accum):
                x, y = _batch(train_data, block, mb, device)
                with amp:
                    loss = model(x, y)[1] / accum
                loss_acc += loss.item()
                (scaler.scale(loss) if scaler else loss).backward()
            if scaler:
                scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            if scaler:
                scaler.step(opt)
                scaler.update()
            else:
                opt.step()
            opt.zero_grad(set_to_none=True)
            step += 1
            tokens_seen += mb * accum * block
            if time.time() - last_eval >= eval_every:
                val = evaluate()
                improved = val < best_val
                best_val = min(best_val, val)
                save(val)
                last_eval = time.time()
                history.append({"step": step, "train": loss_acc, "val": val, "t": time.time()})
                log(f"  lépés {step}: tanító veszteség {loss_acc:.3f}, ellenőrző {val:.3f} "
                    f"(perplexitás {math.exp(min(val, 20)):.1f}){' ★ új legjobb' if improved else ''}"
                    f"  [{int(frac * 100)}%]")
    except KeyboardInterrupt:
        log("Megszakítva – mentés...")
    val = evaluate()
    best_val = min(best_val, val)
    save(val)  # a model.pt csak akkor frissül, ha ez a legjobb eredmény
    with open(root / "train_log.jsonl", "a", encoding="utf-8") as f:
        for h in history:
            f.write(json.dumps({**h, "stage": stage, "preset": preset}) + "\n")
    result = {"stage": stage, "preset": preset, "params_m": round(model.num_params() / 1e6, 1), "steps": step,
              "val_loss": round(val, 4), "best_val": round(best_val, 4), "tokens_seen": tokens_seen}
    log(f"✓ Kész: {result}")
    return result
