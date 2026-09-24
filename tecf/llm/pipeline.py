"""A teljes folyamat egyben: szöveggyűjtés -> tokenizáló -> tanítás -> beállítás."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Callable

from tecf.config import Config
from tecf.knowledge import KnowledgeBase
from tecf.llm import model_dir
from tecf.llm.corpus import DEFAULT_MIX, SOURCES, build_bins, corpus_chars, download_source, export_knowledge, \
    iter_documents
from tecf.llm.hardware import ORDER, PRESETS, choose, detect, hardware_limit, n_params
from tecf.llm.tokenizer import Tokenizer

TOKENIZER_SAMPLE_BYTES = 300 * 2**20


def status(cfg: Config) -> str:
    root = model_dir(cfg.root)
    hw = detect()
    lines = ["== Hardver ==", hw.describe(), "",
             f"A gép által tanítható legnagyobb modell: {hardware_limit(hw)} "
             f"(~{n_params(PRESETS[hardware_limit(hw)]) / 1e6:.0f}M paraméter)",
             "Méretek: " + ", ".join(f"{n} ~{n_params(PRESETS[n]) / 1e6:.0f}M" for n in ORDER), "",
             "== Tanítóanyag ==", f"Összegyűjtött szöveg: {corpus_chars(root) / 2**20:.0f} MB"]
    meta_p = root / "data" / "meta.json"
    if meta_p.exists():
        meta = json.loads(meta_p.read_text())
        tokens = meta["pretrain"]["train"]
        name, why = choose(hw, tokens)
        lines += [f"Tokenek: {tokens / 1e6:.1f}M előtanító, {meta['sft']['train'] / 1e6:.1f}M beszélgetés",
                  f"Ajánlott modell: {name} ({why})"]
    lines += ["", "== Modell =="]
    if (root / "model.pt").exists():
        import torch
        ck = torch.load(root / "model.pt", map_location="cpu", weights_only=False)
        c = ck["config"]
        lines.append(f"Van betanított modell: {c['n_layer']} réteg, {c['n_embd']} dim, kontextus {c['block_size']}, "
                     f"fázis: {ck.get('stage')}, lépés: {ck.get('step')}, ellenőrző veszteség: {ck.get('val_loss'):.3f}")
    else:
        lines.append("Még nincs betanított modell.")
    base_info = model_dir(cfg.root) / "alap" / "info.json"
    if base_info.exists():
        bi = json.loads(base_info.read_text())
        lines.append(f"Van alaptudásos saját modell: {bi['base']} alapon, {bi['steps']} lépés, ellenőrző veszteség "
                     f"{bi['start_val_loss']:.3f} -> {bi['val_loss']:.3f}, frissítve: {bi['updated']}")
    else:
        from tecf.llm.base import BASE_MODELS, choose_base
        lines.append(f"Alaptudásos saját modell még nincs. Ajánlott alap ehhez a géphez: {choose_base(hw)} "
                     f"({next(d for _, m, d in BASE_MODELS if m == choose_base(hw))}) – tecf model base")
    lines.append(f"Használatban: {'IGEN' if cfg.local_provider == 'tecf-sajat' else 'nem'} (tecf model use)")
    return "\n".join(lines)


def collect(cfg: Config, sources: dict[str, int] | None = None, log: Callable[[str], None] = print) -> None:
    root = model_dir(cfg.root)
    kb = KnowledgeBase(cfg.db_path)
    n_doc, n_chat = export_knowledge(kb, root)
    kb.close()
    log(f"✓ Saját tudásbázis: {n_doc} dokumentum, {n_chat} jónak értékelt beszélgetés")
    for name, mb in (sources if sources is not None else DEFAULT_MIX).items():
        if name not in SOURCES:
            log(f"× ismeretlen forrás: {name}")
            continue
        try:
            download_source(name, root, mb, log)
        except Exception as e:  # egy forrás hibája ne állítsa meg a többit
            log(f"× {SOURCES[name][5]}: {type(e).__name__}: {e}")


def prepare(cfg: Config, log: Callable[[str], None] = print) -> dict:
    """Tokenizáló + tokenfájlok. A meglévő tokenizálót megtartja, hogy a modell tovább tanulhasson."""
    root = model_dir(cfg.root)
    if (root / "tokenizer.json").exists():
        log("Meglévő tokenizáló használata (a modell folytatja a tanulást).")
        return build_bins(root, Tokenizer.load(root / "tokenizer.json"), log)
    est_tokens = corpus_chars(root) // 4
    if est_tokens < 10_000:
        raise RuntimeError("Túl kevés a szöveg. Futtasd: tecf model corpus (vagy tölts le alaptudást: tecf bootstrap)")
    name, _ = choose(detect(), est_tokens)
    vocab = PRESETS[name]["vocab_size"]

    def sample():
        used = 0
        for folder in ("corpus", "sft"):
            for doc in iter_documents(root / folder):
                used += len(doc)
                yield doc
                if used > TOKENIZER_SAMPLE_BYTES:
                    return
    log(f"Tokenizáló tanítása ({vocab} szótári elem)...")
    tok = Tokenizer.train(sample(), vocab, root / "tokenizer.json")
    log(f"✓ Tokenizáló kész: {tok.vocab_size} elem")
    return build_bins(root, tok, log)


def reset(cfg: Config) -> None:
    """Új modell a nulláról: törli a tokenizálót és a modellfájlokat (a letöltött szövegek megmaradnak)."""
    root = model_dir(cfg.root)
    for name in ("tokenizer.json", "checkpoint.pt", "model.pt"):
        (root / name).unlink(missing_ok=True)


def build(cfg: Config, hours: float = 4, sources: dict[str, int] | None = None, download: bool = True,
          fresh: bool = False, log: Callable[[str], None] = print, stop: threading.Event | None = None) -> dict:
    """Egy parancsos modellépítés a gép kapacitásához igazítva. Újrafuttatva tovább tanítja a modellt."""
    from tecf.llm.train import train
    root = model_dir(cfg.root)
    if fresh:
        reset(cfg)
    if download:
        collect(cfg, sources, log)
    else:
        kb = KnowledgeBase(cfg.db_path)
        export_knowledge(kb, root)
        kb.close()
    meta = prepare(cfg, log)
    total = hours * 60
    has_sft = meta["sft"]["train"] > 1000
    res = train(root, "pretrain", total * (0.85 if has_sft else 1.0), log=log, stop=stop)
    if has_sft and not (stop and stop.is_set()):
        res = train(root, "sft", total * 0.15, log=log, stop=stop)
    return res


def use(cfg: Config, on: bool = True) -> None:
    if on:
        root = model_dir(cfg.root)
        if not ((root / "model.pt").exists() or (root / "alap" / "modell" / "config.json").exists()):
            raise RuntimeError("Még nincs saját modell: tecf model base (ajánlott) vagy tecf model build")
        cfg.local_provider = "tecf-sajat"
    else:
        cfg.local_provider = "ollama"
    cfg.save()
