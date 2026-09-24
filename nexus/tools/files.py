"""Fájlkezelő eszközök."""
from __future__ import annotations

import fnmatch
import os
from pathlib import Path

from nexus.tools import tool


@tool("Szöveges fájl olvasása.")
def read_file(path: str, max_chars: int = 20000) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")[:max_chars]


@tool("Fájl írása / felülírása (programkód, szkript, konfiguráció).", dangerous=True)
def write_file(path: str, content: str) -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Mentve: {p} ({len(content)} karakter)"


@tool("Könyvtár tartalma.")
def list_dir(path: str = ".") -> str:
    out = []
    for e in sorted(Path(path).iterdir()):
        out.append(f"{'[D]' if e.is_dir() else '   '} {e.name}" + ("" if e.is_dir() else f"  {e.stat().st_size} B"))
    return "\n".join(out)


@tool("Fájlok keresése minta alapján (pl. *.log), opcionálisan szövegre is.")
def find_files(root: str, pattern: str = "*", contains: str = "", limit: int = 200) -> str:
    hits = []
    for dirpath, _, names in os.walk(root):
        for n in fnmatch.filter(names, pattern):
            p = os.path.join(dirpath, n)
            if contains:
                try:
                    if contains not in Path(p).read_text(encoding="utf-8", errors="ignore"):
                        continue
                except OSError:
                    continue
            hits.append(p)
            if len(hits) >= limit:
                return "\n".join(hits)
    return "\n".join(hits) or "Nincs találat."
