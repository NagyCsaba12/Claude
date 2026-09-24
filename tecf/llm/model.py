"""GPT típusú, csak dekóderes transzformer nyelvi modell (a GPT-2 felépítését követi)."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import torch
import torch.nn as nn
from torch.nn import functional as F


@dataclass
class GPTConfig:
    n_layer: int = 6
    n_head: int = 6
    n_embd: int = 384
    block_size: int = 512      # kontextus hossza tokenben
    vocab_size: int = 16384
    dropout: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


class SelfAttention(nn.Module):
    def __init__(self, c: GPTConfig):
        super().__init__()
        assert c.n_embd % c.n_head == 0
        self.qkv = nn.Linear(c.n_embd, 3 * c.n_embd, bias=False)
        self.proj = nn.Linear(c.n_embd, c.n_embd, bias=False)
        self.n_head, self.dropout = c.n_head, c.dropout
        self.resid_drop = nn.Dropout(c.dropout)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, T, C = x.shape
        q, k, v = self.qkv(x).split(C, dim=2)
        q, k, v = (t.view(B, T, self.n_head, C // self.n_head).transpose(1, 2) for t in (q, k, v))
        y = F.scaled_dot_product_attention(q, k, v, is_causal=True,
                                           dropout_p=self.dropout if self.training else 0.0)
        return self.resid_drop(self.proj(y.transpose(1, 2).contiguous().view(B, T, C)))


class MLP(nn.Module):
    def __init__(self, c: GPTConfig):
        super().__init__()
        self.fc = nn.Linear(c.n_embd, 4 * c.n_embd, bias=False)
        self.proj = nn.Linear(4 * c.n_embd, c.n_embd, bias=False)
        self.drop = nn.Dropout(c.dropout)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.drop(self.proj(F.gelu(self.fc(x))))


class Block(nn.Module):
    def __init__(self, c: GPTConfig):
        super().__init__()
        self.ln1, self.ln2 = nn.LayerNorm(c.n_embd), nn.LayerNorm(c.n_embd)
        self.attn, self.mlp = SelfAttention(c), MLP(c)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x + self.attn(self.ln1(x))
        return x + self.mlp(self.ln2(x))


class GPT(nn.Module):
    def __init__(self, c: GPTConfig):
        super().__init__()
        self.config = c
        self.wte = nn.Embedding(c.vocab_size, c.n_embd)
        self.wpe = nn.Embedding(c.block_size, c.n_embd)
        self.drop = nn.Dropout(c.dropout)
        self.blocks = nn.ModuleList(Block(c) for _ in range(c.n_layer))
        self.ln_f = nn.LayerNorm(c.n_embd)
        self.lm_head = nn.Linear(c.n_embd, c.vocab_size, bias=False)
        self.lm_head.weight = self.wte.weight  # súlymegosztás: kevesebb paraméter, jobb általánosítás
        self.apply(self._init)
        for name, p in self.named_parameters():
            if name.endswith("proj.weight"):
                nn.init.normal_(p, mean=0.0, std=0.02 / math.sqrt(2 * c.n_layer))

    @staticmethod
    def _init(m: nn.Module) -> None:
        if isinstance(m, (nn.Linear, nn.Embedding)):
            nn.init.normal_(m.weight, mean=0.0, std=0.02)

    def num_params(self) -> int:
        return sum(p.numel() for p in self.parameters()) - self.wpe.weight.numel()

    def forward(self, idx: torch.Tensor, targets: torch.Tensor | None = None):
        T = idx.size(1)
        pos = torch.arange(T, device=idx.device)
        x = self.drop(self.wte(idx) + self.wpe(pos))
        for b in self.blocks:
            x = b(x)
        x = self.ln_f(x)
        if targets is None:
            return self.lm_head(x[:, [-1], :]), None
        logits = self.lm_head(x)
        loss = F.cross_entropy(logits.view(-1, logits.size(-1)), targets.view(-1), ignore_index=-1)
        return logits, loss

    def optimizer(self, lr: float, weight_decay: float, device: str) -> torch.optim.Optimizer:
        decay = [p for p in self.parameters() if p.requires_grad and p.dim() >= 2]
        no_decay = [p for p in self.parameters() if p.requires_grad and p.dim() < 2]
        groups = [{"params": decay, "weight_decay": weight_decay}, {"params": no_decay, "weight_decay": 0.0}]
        return torch.optim.AdamW(groups, lr=lr, betas=(0.9, 0.95), fused=device == "cuda")

    @torch.no_grad()
    def generate(self, idx: torch.Tensor, max_new_tokens: int, temperature: float = 0.8, top_k: int = 50,
                 top_p: float = 0.95, stop_ids: set[int] | None = None) -> torch.Tensor:
        for _ in range(max_new_tokens):
            cond = idx[:, -self.config.block_size:]
            logits, _ = self(cond)
            logits = logits[:, -1, :] / max(temperature, 1e-5)
            if top_k:
                v, _ = torch.topk(logits, min(top_k, logits.size(-1)))
                logits[logits < v[:, [-1]]] = -float("inf")
            probs = F.softmax(logits, dim=-1)
            if top_p < 1.0:
                sp, si = torch.sort(probs, descending=True)
                mask = torch.cumsum(sp, dim=-1) - sp > top_p
                sp[mask] = 0.0
                probs = torch.zeros_like(probs).scatter(-1, si, sp)
                probs = probs / probs.sum(dim=-1, keepdim=True)
            nxt = torch.multinomial(probs, 1)
            idx = torch.cat([idx, nxt], dim=1)
            if stop_ids and nxt.item() in stop_ids:
                break
        return idx
