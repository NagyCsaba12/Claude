"""Konfiguráció és könyvtárszerkezet.

Alapértelmezett hely Windows alatt: D:\\TecFAi (a TECF_HOME környezeti
változóval felülírható). Más rendszeren: ~/TecFAi.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path


def default_home() -> Path:
    env = os.environ.get("TECF_HOME")
    if env:
        return Path(env)
    if sys.platform.startswith("win"):
        return Path("D:/TecFAi")
    return Path.home() / "TecFAi"


@dataclass
class Config:
    home: str = ""
    # Helyi (offline) modell – Ollama vagy bármely OpenAI-kompatibilis helyi szerver
    local_provider: str = "ollama"
    local_model: str = "qwen3:8b"
    # Felhő szolgáltatók sorrendje, ha a helyi modell nem elérhető
    fallback_providers: list[str] = field(default_factory=lambda: ["anthropic", "openai", "gemini"])
    offline_only: bool = False
    # Tanuló üzem
    learn_max_pages_per_topic: int = 8
    learn_request_delay_s: float = 1.5
    learn_from_ai_providers: list[str] = field(default_factory=list)
    # Biztonság: rendszerparancs / hálózati eszköz módosítás előtt kérdezzen
    confirm_system_commands: bool = True
    confirm_network_changes: bool = True
    retrieval_top_k: int = 6
    language: str = "hu"

    # ---- útvonalak ----
    @property
    def root(self) -> Path:
        return Path(self.home) if self.home else default_home()

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "knowledge.db"

    @property
    def inbox_dir(self) -> Path:
        """Ide bemásolt dokumentumokat az `ingest` automatikusan feldolgozza."""
        return self.root / "inbox"

    @property
    def output_dir(self) -> Path:
        return self.root / "output"

    @property
    def keys_path(self) -> Path:
        return self.root / "config" / "api_keys.json"

    @property
    def config_path(self) -> Path:
        return self.root / "config" / "config.json"

    @property
    def log_dir(self) -> Path:
        return self.root / "logs"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.inbox_dir, self.output_dir, self.log_dir, self.keys_path.parent):
            d.mkdir(parents=True, exist_ok=True)

    def save(self) -> None:
        self.ensure_dirs()
        data = asdict(self)
        self.config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, home: str | None = None) -> "Config":
        root = Path(home) if home else default_home()
        path = root / "config" / "config.json"
        cfg = cls(home=str(root))
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            for k, v in data.items():
                if hasattr(cfg, k) and k != "home":
                    setattr(cfg, k, v)
        cfg.ensure_dirs()
        return cfg

    # ---- API kulcsok ----
    def load_keys(self) -> dict[str, str]:
        if self.keys_path.exists():
            return json.loads(self.keys_path.read_text(encoding="utf-8"))
        return {}

    def set_key(self, provider: str, key: str) -> None:
        keys = self.load_keys()
        keys[provider] = key
        self.keys_path.write_text(json.dumps(keys, indent=2), encoding="utf-8")
