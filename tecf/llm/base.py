"""Saját modell ALAPTUDÁSSAL: egy kész, nyílt modellből (Qwen3) indul, és azt tanítja tovább.

A nulláról tanított modell hónapokig tanulna, mire értelmesen beszél. Ez a mód egy olyan modellre épít,
amely már tud magyarul, programozik és gondolkodik, és ezt hangolja a saját tudásodra (LoRA):
  - a tudásbázis dokumentumaira (rendszergazda, hálózat, programozás, a saját jegyzeteid)
  - a jónak értékelt beszélgetésekre (így a te stílusodban, a te környezetedre válaszol)

Az eredmény egy önálló, a gépen tárolt modell: D:\\TecFAi\\sajat_modell\\alap\\modell
Minden újabb futás a legutóbbi saját modellből folytatja, így folyamatosan fejlődik.

Szükséges: torch, transformers, peft, accelerate (requirements-train.txt)
"""
from __future__ import annotations

import json
import math
import os
import random
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from tecf.config import Config
from tecf.knowledge import KnowledgeBase
from tecf.llm import model_dir
from tecf.llm.hardware import Hardware, detect, free_gpu_memory

# (min. VRAM GB, Hugging Face azonosító, leírás) – Apache-2.0 licenc, magyarul is tudnak
BASE_MODELS = [
    (0, "Qwen/Qwen3-0.6B", "0,6 milliárd paraméter – bármilyen gépen fut, CPU-n is tanítható"),
    (5.5, "Qwen/Qwen3-1.7B", "1,7 milliárd paraméter – 6+ GB VRAM"),
    (11.5, "Qwen/Qwen3-4B", "4 milliárd paraméter – 12+ GB VRAM"),
    (21.5, "Qwen/Qwen3-8B", "8 milliárd paraméter – 22+ GB VRAM"),
]
SYSTEM = "Te TecF Ai vagy, egy segítőkész magyar nyelvű asszisztens: rendszergazda, programozó és hálózati szakértő."


def choose_base(hw: Hardware) -> str:
    vram = hw.vram_gb if hw.device == "cuda" else 0
    return [m for need, m, _ in BASE_MODELS if vram >= need][-1]


def paths(cfg: Config) -> dict[str, Path]:
    root = model_dir(cfg.root) / "alap"
    return {"root": root, "adapter": root / "adapter", "model": root / "modell", "info": root / "info.json"}


def _hf_env(cfg: Config) -> None:
    # a letöltött alapmodellek is a D: meghajtóra kerüljenek
    os.environ.setdefault("HF_HOME", str(Path(cfg.root) / "hf_cache"))


# ---------------------------------------------------------------- tanítóanyag
def build_examples(cfg: Config, tok, max_len: int, log: Callable[[str], None] = print) -> list[dict]:
    """Példák: {"ids": [...], "labels": [...]} – a beszélgetéseknél csak a válaszrészből tanul."""
    kb = KnowledgeBase(cfg.db_path)
    examples: list[dict] = []

    def enc(text: str) -> list[int]:
        return tok(text, add_special_tokens=False)["input_ids"]

    # 1) jónak értékelt beszélgetések (3x súllyal: ezek a legértékesebbek)
    n_chat = 0
    for q, a in kb.db.execute("SELECT question, answer FROM conversations WHERE rating > 0"):
        msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": q}]
        prompt = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True, enable_thinking=False)
        full = tok.apply_chat_template(msgs + [{"role": "assistant", "content": a}], tokenize=False,
                                       enable_thinking=False)
        p_ids, f_ids = enc(prompt), enc(full)[:max_len]
        labels = [-100] * min(len(p_ids), len(f_ids)) + f_ids[len(p_ids):]
        examples += [{"ids": f_ids, "labels": labels}] * 3
        n_chat += 1
    # 2) tudásbázis: forrásonként összefűzve, max_len hosszú szeletekben (a megbízhatóbbak előbb)
    n_doc = 0
    for sid, title in kb.db.execute("SELECT id, title FROM sources ORDER BY trust DESC, id"):
        text = "\n".join(r[0] for r in kb.db.execute("SELECT text FROM chunks WHERE source_id=? ORDER BY seq",
                                                     (sid,)))
        ids = enc((f"# {title}\n\n" if title else "") + text) + [tok.eos_token_id]
        for i in range(0, len(ids), max_len):
            part = ids[i:i + max_len]
            if len(part) >= 32:
                examples.append({"ids": part, "labels": list(part)})
        n_doc += 1
    # 3) emlékek (tények a te környezetedről)
    mems = [r[0] for r in kb.db.execute("SELECT text FROM memories ORDER BY confidence DESC LIMIT 2000")]
    for i in range(0, len(mems), 40):
        ids = enc("Tények:\n" + "\n".join(f"- {m}" for m in mems[i:i + 40]))[:max_len]
        examples.append({"ids": ids, "labels": list(ids)})
    kb.close()
    log(f"Tanítóanyag: {n_chat} jó beszélgetés, {n_doc} dokumentum, {len(mems)} emlék -> {len(examples)} példa")
    return examples


# ---------------------------------------------------------------- tanítás
def finetune(cfg: Config, minutes: float = 120, base: str | None = None, max_len: int = 1024,
             log: Callable[[str], None] = print, stop: threading.Event | None = None) -> dict:
    import torch
    from peft import LoraConfig, PeftModel, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer

    _hf_env(cfg)
    hw = detect()
    p = paths(cfg)
    p["root"].mkdir(parents=True, exist_ok=True)
    info = json.loads(p["info"].read_text()) if p["info"].exists() else {}
    base = base or info.get("base") or choose_base(hw)
    if info.get("base") and info["base"] != base:
        log(f"Új alapmodell ({info['base']} -> {base}): a korábbi hangolás nem vihető át, újrakezdés.")
        shutil.rmtree(p["adapter"], ignore_errors=True)
        info = {}
    device = hw.device
    dtype = (torch.bfloat16 if hw.bf16 else torch.float16) if device == "cuda" else torch.float32
    log(f"Alapmodell: {base} (letöltés az első alkalommal, a {os.environ['HF_HOME']} mappába)")
    tok = AutoTokenizer.from_pretrained(base)
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(base, dtype=dtype)
    if device == "cuda":
        free_gpu_memory(log)
    model.to(device)
    if device == "cuda":
        model.gradient_checkpointing_enable()
        model.enable_input_require_grads()
    if (p["adapter"] / "adapter_config.json").exists():
        log("Folytatás a legutóbbi saját hangolásból.")
        model = PeftModel.from_pretrained(model, str(p["adapter"]), is_trainable=True)
    else:
        model = get_peft_model(model, LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05,
                                                 target_modules="all-linear", task_type="CAUSAL_LM"))
    trainable = sum(x.numel() for x in model.parameters() if x.requires_grad)
    log(f"Hangolható paraméterek: {trainable / 1e6:.1f}M (az alapmodell súlyai változatlanok)")

    examples = build_examples(cfg, tok, max_len, log)
    if len(examples) < 4:
        raise RuntimeError("Túl kevés a tanítóanyag. Tölts le alaptudást (tecf bootstrap), értékelj válaszokat.")
    random.seed(0)
    random.shuffle(examples)
    n_val = max(2, len(examples) // 20)
    val, train_set = examples[:n_val], examples[n_val:]

    accum, peak_lr = 8, 2e-4
    opt = torch.optim.AdamW([x for x in model.parameters() if x.requires_grad], lr=peak_lr, weight_decay=0.0)
    amp = torch.autocast("cuda", dtype=dtype) if device == "cuda" else torch.autocast("cpu", enabled=False)

    def loss_of(ex: dict):
        ids = torch.tensor([ex["ids"]], device=device)
        labels = torch.tensor([ex["labels"]], device=device)
        with amp:
            return model(input_ids=ids, labels=labels).loss

    @torch.no_grad()
    def evaluate() -> float:
        model.eval()
        losses = [loss_of(ex).item() for ex in val[:50]]
        model.train()
        return sum(losses) / len(losses)

    best = info.get("val_loss", float("inf")) if info else float("inf")
    start_val = evaluate()
    log(f"Kiinduló ellenőrző veszteség: {start_val:.3f}")
    best = min(best, start_val) if (p["adapter"] / "adapter_config.json").exists() else float("inf")
    budget, start, last_eval = minutes * 60, time.time(), time.time()
    eval_every = max(60.0, min(600.0, budget / 8))
    step, i, improved_any = 0, 0, False
    model.train()
    while True:
        frac = (time.time() - start) / budget
        if frac >= 1 or (stop is not None and stop.is_set()):
            break
        lr = peak_lr * (frac / 0.05 if frac < 0.05 else 0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * frac)))
        for g in opt.param_groups:
            g["lr"] = lr
        for _ in range(accum):
            loss = loss_of(train_set[i % len(train_set)]) / accum
            loss.backward()
            i += 1
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        opt.zero_grad(set_to_none=True)
        step += 1
        if time.time() - last_eval >= eval_every:
            v = evaluate()
            if v < best:
                best, improved_any = v, True
                model.save_pretrained(str(p["adapter"]))
            last_eval = time.time()
            log(f"  lépés {step} ({i} példa): ellenőrző veszteség {v:.3f}{' ★' if v <= best else ''} [{int(frac * 100)}%]")
    v = evaluate()
    if v < best or not (p["adapter"] / "adapter_config.json").exists():
        best, improved_any = min(best, v), True
        model.save_pretrained(str(p["adapter"]))
    log(f"Végső ellenőrző veszteség: {v:.3f} (kiinduló: {start_val:.3f})")

    if improved_any or not p["model"].exists():
        log("Önálló saját modell mentése (alapmodell + hangolás egyesítése)...")
        merged = PeftModel.from_pretrained(
            AutoModelForCausalLM.from_pretrained(base, dtype=dtype), str(p["adapter"])).merge_and_unload()
        shutil.rmtree(p["model"], ignore_errors=True)
        merged.save_pretrained(str(p["model"]))
        tok.save_pretrained(str(p["model"]))
    info = {"base": base, "val_loss": best, "start_val_loss": start_val, "steps": info.get("steps", 0) + step,
            "examples": len(examples), "updated": time.strftime("%Y-%m-%d %H:%M")}
    p["info"].write_text(json.dumps(info, indent=2), encoding="utf-8")
    log(f"✓ Saját modell kész: {p['model']}")
    return info


# ---------------------------------------------------------------- használat
class BaseModelRunner:
    _cache: dict[str, "BaseModelRunner"] = {}
    _lock = threading.Lock()

    def __init__(self, path: Path):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        hw = detect()
        self.device = hw.device
        dtype = (torch.bfloat16 if hw.bf16 else torch.float16) if hw.device == "cuda" else torch.float32
        self.tok = AutoTokenizer.from_pretrained(str(path))
        self.model = AutoModelForCausalLM.from_pretrained(str(path), dtype=dtype).to(self.device).eval()

    @classmethod
    def get(cls, path: Path) -> "BaseModelRunner":
        with cls._lock:
            key = f"{path}:{(path / 'config.json').stat().st_mtime}"
            if key not in cls._cache:
                cls._cache.clear()
                cls._cache[key] = cls(path)
            return cls._cache[key]

    def chat(self, messages: list[dict], system: str = "", temperature: float = 0.7, max_tokens: int = 1024,
             cancel=None) -> str:
        import torch
        from transformers import StoppingCriteria, StoppingCriteriaList

        class _Stop(StoppingCriteria):  # leállítás gombra a generálás a következő szónál megáll
            def __call__(self, input_ids, scores, **kwargs):
                flag = cancel is not None and cancel.is_set()
                return torch.full((input_ids.shape[0],), flag, dtype=torch.bool, device=input_ids.device)
        msgs = [{"role": "system", "content": system or SYSTEM}] + messages
        text = self.tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True, enable_thinking=False)
        ids = self.tok(text, return_tensors="pt", add_special_tokens=False).to(self.device)
        with torch.no_grad():
            out = self.model.generate(**ids, max_new_tokens=max_tokens, do_sample=temperature > 0,
                                      temperature=max(temperature, 0.01), top_p=0.9,
                                      pad_token_id=self.tok.pad_token_id or self.tok.eos_token_id,
                                      stopping_criteria=StoppingCriteriaList([_Stop()]))
        answer = self.tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True)
        return re.sub(r"<think>.*?</think>", "", answer, flags=re.S).strip()


def export_to_ollama(cfg: Config, name: str = "tecf-agy", quantize: str = "q4_K_M",
                     log: Callable[[str], None] = print) -> bool:
    """A saját modell átadása az Ollamának (gyorsabb, kevesebb memória, eszközhasználat)."""
    p = paths(cfg)
    if not p["model"].exists():
        raise RuntimeError("Még nincs saját modell: tecf model base")
    modelfile = p["root"] / "Modelfile"
    modelfile.write_text(f'FROM "{p["model"]}"\nSYSTEM """{SYSTEM}"""\n', encoding="utf-8")
    cmd = ["ollama", "create", name, "-f", str(modelfile)] + (["--quantize", quantize] if quantize else [])
    log("Ollama import: " + " ".join(cmd))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    except FileNotFoundError:
        log("Az Ollama nincs telepítve.")
        return False
    log((r.stdout + r.stderr)[-1500:])
    return r.returncode == 0
