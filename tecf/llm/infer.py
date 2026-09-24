"""A saját modell használata szöveggenerálásra / beszélgetésre."""
from __future__ import annotations

import threading
from pathlib import Path

import torch

from tecf.llm.hardware import detect
from tecf.llm.model import GPT, GPTConfig
from tecf.llm.tokenizer import END, EOT, Tokenizer, format_chat

_cache: dict[str, "OwnModel"] = {}
_lock = threading.Lock()


class OwnModel:
    def __init__(self, root: Path):
        self.device = detect().device
        ck = torch.load(root / "model.pt", map_location="cpu", weights_only=False)
        self.cfg = GPTConfig(**ck["config"])
        self.model = GPT(self.cfg)
        self.model.load_state_dict(ck["model"])
        self.model.to(self.device).eval()
        self.tok = Tokenizer.load(root / "tokenizer.json")
        self.info = {"stage": ck.get("stage"), "val_loss": ck.get("val_loss"), "step": ck.get("step"),
                     "params_m": round(self.model.num_params() / 1e6, 1)}
        self.stop_ids = {self.tok.token_id(END), self.tok.token_id(EOT)}

    @classmethod
    def get(cls, root: Path) -> "OwnModel":
        key = str(root)
        with _lock:
            path = root / "model.pt"
            m = _cache.get(key)
            if m is None or m.mtime != path.stat().st_mtime:  # új tanítás után újratölt
                m = cls(root)
                m.mtime = path.stat().st_mtime
                _cache[key] = m
            return m

    def complete(self, prompt: str, max_tokens: int = 200, temperature: float = 0.8, cancel=None) -> str:
        ids = self.tok.encode(prompt)
        room = max(16, self.cfg.block_size - min(max_tokens, self.cfg.block_size // 2))
        ids = ids[-room:]  # a kontextusba nem férő eleje levágva
        x = torch.tensor([ids], dtype=torch.long, device=self.device)
        out = self.model.generate(x, min(max_tokens, self.cfg.block_size), temperature=temperature,
                                  stop_ids=self.stop_ids, cancel=cancel)[0].tolist()[len(ids):]
        out = [i for i in out if i not in self.stop_ids]
        return self.tok.decode(out).strip()

    def chat(self, messages: list[dict], system: str = "", temperature: float = 0.7,
             max_tokens: int = 400, cancel=None) -> str:
        # kis kontextusú modellnél a hosszú rendszerüzenet elfoglalná a helyet: csak az eleje marad
        sys_short = system[: self.cfg.block_size]
        return self.complete(format_chat(messages[-6:], sys_short, add_generation_prompt=True), max_tokens,
                             temperature, cancel)
