"""TecF Ai saját nyelvi modell – nulláról tanított GPT típusú transzformer.

Lépések (egyben: `tecf model build`):
  1. corpus   – szöveggyűjtés: saját tudásbázis + nyílt szöveggyűjtemények (Wikipedia, FineWeb, kód)
  2. prepare  – saját tokenizáló tanítása (BPE) és a szöveg bináris tokenfájlokká alakítása
  3. train    – előtanítás (pretrain), majd beszélgetésre hangolás (sft), a gép kapacitásához méretezve
  4. use      – beállítás a TecF Ai modelljeként

Szükséges csomagok: torch, numpy, tokenizers, pyarrow (requirements-train.txt)
"""
from pathlib import Path


def model_dir(root: str | Path) -> Path:
    d = Path(root) / "sajat_modell"
    d.mkdir(parents=True, exist_ok=True)
    return d
