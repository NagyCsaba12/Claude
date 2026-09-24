"""Tanítóanyag gyűjtése és tokenfájlok készítése.

Könyvtárszerkezet (D:\\TecFAi\\sajat_modell):
  corpus/*.txt    előtanító szövegek (dokumentumok \\n<|endoftext|>\\n elválasztással)
  sft/*.txt       beszélgetések a modell saját formátumában
  tokenizer.json  saját tokenizáló
  data/{pretrain,sft}_{train,val}.bin  tokenek (uint16 / uint32)
"""
from __future__ import annotations

import json
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable, Iterator

from tecf.knowledge import KnowledgeBase
from tecf.llm.tokenizer import EOT, Tokenizer, format_chat

SEP = f"\n{EOT}\n"

# Nyílt szöveggyűjtemények a Hugging Face-ről (a parquet API-n keresztül, fiók nélkül)
# név: (adatkészlet, konfiguráció, split, oszlop, fajta, leírás)
SOURCES: dict[str, tuple[str, str, str, str, str, str]] = {
    "wiki-hu": ("wikimedia/wikipedia", "20231101.hu", "train", "text", "pretrain", "Magyar Wikipédia"),
    "wiki-en": ("wikimedia/wikipedia", "20231101.en", "train", "text", "pretrain", "Angol Wikipédia"),
    "fineweb2-hu": ("HuggingFaceFW/fineweb-2", "hun_Latn", "train", "text", "pretrain",
                    "Szűrt, jó minőségű magyar webes szöveg"),
    "fineweb-edu": ("HuggingFaceFW/fineweb-edu", "sample-10BT", "train", "text", "pretrain",
                    "Oktatási minőségű angol webes szöveg"),
    "code": ("codeparrot/codeparrot-clean", "default", "train", "content", "pretrain", "Python forráskód"),
    "smoltalk": ("HuggingFaceTB/smoltalk", "all", "train", "messages", "sft",
                 "Utasításkövető beszélgetések (angol)"),
}
# Alapértelmezett keverék: magyar + angol + kód + beszélgetés
DEFAULT_MIX = {"wiki-hu": 400, "fineweb2-hu": 600, "fineweb-edu": 600, "wiki-en": 200, "code": 200,
               "smoltalk": 300}


def export_knowledge(kb: KnowledgeBase, out: Path) -> tuple[int, int]:
    """A TecF Ai saját tudásbázisa és jónak értékelt beszélgetései -> tanítóanyag."""
    (out / "corpus").mkdir(parents=True, exist_ok=True)
    (out / "sft").mkdir(parents=True, exist_ok=True)
    n_doc = 0
    with open(out / "corpus" / "tudasbazis.txt", "w", encoding="utf-8") as f:
        for sid, in kb.db.execute("SELECT id FROM sources ORDER BY id"):
            text = "\n".join(r[0] for r in kb.db.execute(
                "SELECT text FROM chunks WHERE source_id=? ORDER BY seq", (sid,)))
            f.write(text + SEP)
            n_doc += 1
        mems = [r[0] for r in kb.db.execute("SELECT text FROM memories ORDER BY confidence DESC")]
        if mems:
            f.write("\n".join(mems) + SEP)
    n_chat = 0
    with open(out / "sft" / "sajat_beszelgetesek.txt", "w", encoding="utf-8") as f:
        for q, a in kb.db.execute("SELECT question, answer FROM conversations WHERE rating > 0"):
            f.write(format_chat([{"role": "user", "content": q}, {"role": "assistant", "content": a}]) + SEP)
            n_chat += 1
    return n_doc, n_chat


def _get_json(url: str) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": "TecFAi/0.1"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def download_source(name: str, out: Path, max_mb: int, log: Callable[[str], None] = print) -> int:
    """Egy nyílt gyűjtemény letöltése legfeljebb `max_mb` MB szövegig. Visszaadja a kiírt MB-ot."""
    try:
        import pyarrow.parquet as pq
    except ImportError as e:
        raise RuntimeError("Letöltéshez: pip install pyarrow") from e
    repo, config, split, column, kind, desc = SOURCES[name]
    target = out / ("sft" if kind == "sft" else "corpus") / f"{name}.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    have = target.stat().st_size if target.exists() else 0
    limit = max_mb * 2**20
    if have >= limit:
        log(f"  {desc}: már megvan ({have / 2**20:.0f} MB)")
        return have // 2**20
    urls = _get_json(f"https://huggingface.co/api/datasets/{repo}/parquet/{config}/{split}")
    log(f"⬇ {desc}: {len(urls)} fájl elérhető, cél {max_mb} MB")
    state_path = target.with_suffix(".state.json")
    done = json.loads(state_path.read_text())["files_done"] if state_path.exists() and have else 0
    written = have
    with open(target, "a", encoding="utf-8") as f:
        # folytatás: a korábban már teljesen feldolgozott parquet fájlokat átugorja
        for k, url in enumerate(urls):
            if written >= limit:
                break
            if k < done:
                continue
            with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "TecFAi/0.1"})
                with urllib.request.urlopen(req, timeout=300) as r, open(tmp_path, "wb") as w:
                    while chunk := r.read(1 << 20):
                        w.write(chunk)
                pf = pq.ParquetFile(tmp_path)
                for batch in pf.iter_batches(columns=[column], batch_size=1000):
                    for item in batch.column(0).to_pylist():
                        text = format_chat(item) if kind == "sft" else item
                        if text and (kind == "sft" or len(text) > 200):
                            data = text.strip() + SEP
                            f.write(data)
                            written += len(data.encode("utf-8"))
                    if written >= limit:
                        break
                f.flush()
                state_path.write_text(json.dumps({"files_done": k + 1}))
                log(f"  … {written / 2**20:.0f} MB")
            finally:
                tmp_path.unlink(missing_ok=True)
    return written // 2**20


def iter_documents(folder: Path) -> Iterator[str]:
    for p in sorted(folder.glob("*.txt")):
        buf: list[str] = []
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.strip() == EOT:
                    if buf:
                        yield "".join(buf).strip()
                    buf = []
                else:
                    buf.append(line)
        if buf and "".join(buf).strip():
            yield "".join(buf).strip()


def corpus_chars(root: Path) -> int:
    return sum(p.stat().st_size for d in ("corpus", "sft") for p in (root / d).glob("*.txt"))


def build_bins(root: Path, tok: Tokenizer, log: Callable[[str], None] = print) -> dict:
    """Szövegek -> tokenfájlok. Minden 100. dokumentum az ellenőrző (val) halmazba kerül."""
    import numpy as np
    (root / "data").mkdir(exist_ok=True)
    dtype = np.uint16 if tok.vocab_size < 65535 else np.uint32
    eot = tok.token_id(EOT)
    meta = {"vocab_size": tok.vocab_size, "dtype": np.dtype(dtype).name}
    for stage, folder in (("pretrain", "corpus"), ("sft", "sft")):
        counts = {"train": 0, "val": 0}
        files = {s: open(root / "data" / f"{stage}_{s}.bin", "wb") for s in counts}
        batch: list[str] = []
        n = 0

        def flush():
            for i, ids in enumerate(tok.encode_batch(batch)):
                split = "val" if (n - len(batch) + i) % 100 == 99 else "train"
                arr = np.array(ids + [eot], dtype=dtype)
                arr.tofile(files[split])
                counts[split] += len(arr)

        for doc in iter_documents(root / folder):
            batch.append(doc)
            n += 1
            if len(batch) >= 2000:
                flush()
                batch = []
                log(f"  {stage}: {n} dokumentum, {sum(counts.values()) / 1e6:.1f}M token")
        if batch:
            flush()
        for fh in files.values():
            fh.close()
        meta[stage] = counts
        log(f"✓ {stage}: {n} dokumentum, {counts['train'] / 1e6:.2f}M tanító + {counts['val'] / 1e6:.2f}M "
            "ellenőrző token")
    (root / "data" / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta
