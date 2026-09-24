"""Hardver felmérés és a gépre illő modellméret kiválasztása."""
from __future__ import annotations

import ctypes
import math
import os
import sys
from dataclasses import dataclass

# Modellméretek. A paraméterszám kb.: 12 * n_layer * n_embd^2 + vocab * n_embd
PRESETS: dict[str, dict] = {
    "teszt":   dict(n_layer=2, n_head=2, n_embd=64, block_size=64, vocab_size=512),
    "mini":    dict(n_layer=4, n_head=4, n_embd=256, block_size=256, vocab_size=8192),
    "kicsi":   dict(n_layer=6, n_head=6, n_embd=384, block_size=512, vocab_size=16384),
    "kozepes": dict(n_layer=12, n_head=12, n_embd=768, block_size=1024, vocab_size=32000),
    "nagy":    dict(n_layer=24, n_head=16, n_embd=1024, block_size=1024, vocab_size=32000),
    "xl":      dict(n_layer=24, n_head=16, n_embd=1536, block_size=2048, vocab_size=32000),
}
ORDER = ["mini", "kicsi", "kozepes", "nagy", "xl"]
# Egy optimalizálási lépésben feldolgozott tokenek száma (gradiens akkumulációval)
TOKENS_PER_STEP = {"teszt": 2048, "mini": 16384, "kicsi": 32768, "kozepes": 131072, "nagy": 262144,
                   "xl": 524288}


def n_params(p: dict) -> int:
    return 12 * p["n_layer"] * p["n_embd"] ** 2 + p["vocab_size"] * p["n_embd"] + p["block_size"] * p["n_embd"]


@dataclass
class Hardware:
    device: str            # cuda | mps | cpu
    gpu_name: str
    vram_gb: float
    ram_gb: float
    cpu_cores: int
    bf16: bool
    torch_ok: bool

    def describe(self) -> str:
        gpu = f"{self.gpu_name} ({self.vram_gb:.1f} GB VRAM)" if self.device == "cuda" else (
            "Apple GPU (MPS)" if self.device == "mps" else "nincs használható GPU – CPU-n tanít (lassú)")
        return (f"GPU: {gpu}\nRAM: {self.ram_gb:.1f} GB   CPU magok: {self.cpu_cores}\n"
                f"PyTorch: {'telepítve' if self.torch_ok else 'NINCS telepítve (pip install -r requirements-train.txt)'}")


def _ram_gb() -> float:
    try:
        import psutil
        return psutil.virtual_memory().total / 2**30
    except ImportError:
        pass
    if sys.platform.startswith("win"):
        class MEM(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        m = MEM()
        m.dwLength = ctypes.sizeof(MEM)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.ullTotalPhys / 2**30
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30
    except (ValueError, OSError, AttributeError):
        return 8.0


def detect() -> Hardware:
    ram, cores = _ram_gb(), os.cpu_count() or 1
    try:
        import torch
    except ImportError:
        return Hardware("cpu", "", 0.0, ram, cores, False, False)
    if torch.cuda.is_available():
        prop = torch.cuda.get_device_properties(0)
        return Hardware("cuda", prop.name, prop.total_memory / 2**30, ram, cores,
                        torch.cuda.is_bf16_supported(), True)
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return Hardware("mps", "Apple", 0.0, ram, cores, False, True)
    return Hardware("cpu", "", 0.0, ram, cores, False, True)


def hardware_limit(hw: Hardware) -> str:
    """A legnagyobb modell, amelyet a gép memóriája még kényelmesen tanítani tud."""
    if hw.device == "cuda":
        v = hw.vram_gb
        return "xl" if v >= 40 else "nagy" if v >= 16 else "kozepes" if v >= 6 else "kicsi"
    if hw.device == "mps":
        return "kozepes" if hw.ram_gb >= 16 else "kicsi"
    return "kicsi" if hw.cpu_cores >= 8 and hw.ram_gb >= 16 else "mini"


def data_limit(n_tokens: int) -> str:
    """Kevés adathoz kis modell kell, különben csak bemagolja a szöveget (túltanulás).
    Ökölszabály: legalább ~10 token paraméterenként."""
    best = "mini"
    for name in ORDER:
        if n_params(PRESETS[name]) * 10 <= n_tokens:
            best = name
    return best


def choose(hw: Hardware, n_tokens: int | None = None) -> tuple[str, str]:
    """Visszaad: (preset neve, indoklás)."""
    hl = hardware_limit(hw)
    if n_tokens is None:
        return hl, f"a hardver alapján: {hl}"
    dl = data_limit(n_tokens)
    name = ORDER[min(ORDER.index(hl), ORDER.index(dl))]
    why = (f"hardver korlát: {hl}, adatmennyiség korlát ({n_tokens / 1e6:.1f}M token): {dl} -> {name}")
    return name, why


def micro_batch(preset: str, hw: Hardware) -> int:
    base = {"teszt": 8, "mini": 32, "kicsi": 16, "kozepes": 8, "nagy": 4, "xl": 2}[preset]
    if hw.device == "cuda" and hw.vram_gb >= 2 * {"kozepes": 8, "nagy": 16, "xl": 40}.get(preset, 99):
        base *= 2
    if hw.device == "cpu":
        base = max(1, base // 2)
    return base


def grad_accum(preset: str, mb: int) -> int:
    return max(1, math.ceil(TOKENS_PER_STEP[preset] / (mb * PRESETS[preset]["block_size"])))
