"""Saját tokenizáló: bájt szintű BPE, a saját szövegeken tanítva (a magyar ékezeteket is jól kezeli).
Ha a `tokenizers` csomag hiányzik, egyszerű bájt tokenizálóra vált (lassabb tanulás, de működik)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

EOT, SYS, USER, ASSISTANT, END = "<|endoftext|>", "<|system|>", "<|user|>", "<|assistant|>", "<|end|>"
SPECIAL = [EOT, SYS, USER, ASSISTANT, END]


class Tokenizer:
    def __init__(self, hf=None):
        self.hf = hf  # tokenizers.Tokenizer vagy None (bájt mód)

    # ---------- betöltés / tanítás ----------
    @classmethod
    def train(cls, texts: Iterable[str], vocab_size: int, path: str | Path) -> "Tokenizer":
        try:
            from tokenizers import Tokenizer as HFTok
            from tokenizers import decoders, models, pre_tokenizers, trainers
        except ImportError:
            Path(path).write_text(json.dumps({"type": "bytes"}), encoding="utf-8")
            return cls(None)
        tok = HFTok(models.BPE())
        tok.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
        tok.decoder = decoders.ByteLevel()
        trainer = trainers.BpeTrainer(vocab_size=vocab_size, special_tokens=SPECIAL, min_frequency=2,
                                      initial_alphabet=pre_tokenizers.ByteLevel.alphabet())
        tok.train_from_iterator(texts, trainer=trainer)
        tok.save(str(path))
        return cls(tok)

    @classmethod
    def load(cls, path: str | Path) -> "Tokenizer":
        raw = Path(path).read_text(encoding="utf-8")
        if json.loads(raw).get("type") == "bytes":
            return cls(None)
        from tokenizers import Tokenizer as HFTok
        return cls(HFTok.from_str(raw))

    # ---------- használat ----------
    @property
    def vocab_size(self) -> int:
        return self.hf.get_vocab_size() if self.hf else 256 + len(SPECIAL)

    def token_id(self, special: str) -> int:
        return self.hf.token_to_id(special) if self.hf else 256 + SPECIAL.index(special)

    def encode(self, text: str) -> list[int]:
        if self.hf:
            return self.hf.encode(text).ids
        # bájt mód: a speciális jelöléseket külön azonosítóra képezi
        ids: list[int] = []
        rest = text
        while rest:
            pos = [(rest.find(s), s) for s in SPECIAL if s in rest]
            if not pos:
                ids.extend(rest.encode("utf-8"))
                break
            i, s = min(pos)
            ids.extend(rest[:i].encode("utf-8"))
            ids.append(self.token_id(s))
            rest = rest[i + len(s):]
        return ids

    def encode_batch(self, texts: list[str]) -> list[list[int]]:
        if self.hf:
            return [e.ids for e in self.hf.encode_batch(texts)]
        return [self.encode(t) for t in texts]

    def decode(self, ids: list[int]) -> str:
        if self.hf:
            return self.hf.decode(ids, skip_special_tokens=False)
        out, buf = [], bytearray()
        for i in ids:
            if i < 256:
                buf.append(i)
            else:
                out.append(buf.decode("utf-8", "replace"))
                buf = bytearray()
                out.append(SPECIAL[i - 256] if i - 256 < len(SPECIAL) else "")
        out.append(buf.decode("utf-8", "replace"))
        return "".join(out)


def format_chat(messages: list[dict], system: str = "", add_generation_prompt: bool = False) -> str:
    """Beszélgetés szöveggé alakítása a modell saját formátumában."""
    tag = {"system": SYS, "user": USER, "assistant": ASSISTANT}
    parts = [f"{SYS}\n{system}{END}\n"] if system else []
    for m in messages:
        if m.get("role") in tag and m.get("content"):
            parts.append(f"{tag[m['role']]}\n{m['content'].strip()}{END}\n")
    if add_generation_prompt:
        parts.append(f"{ASSISTANT}\n")
    return "".join(parts)
