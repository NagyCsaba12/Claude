"""Önfrissítés GitHubról: újratelepítés nélkül lecseréli a programfájlokat.

Csak a program (D:\\TecFAi\\app) cserélődik; a tudásbázis, a beállítások, a letöltött modellek,
a saját modell és a Python környezet megmarad. Az új csomagfüggőségeket is feltelepíti.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

REPO = "NagyCsaba12/Claude"
BRANCH = "claude/zen-curie-2u6xui"
UA = {"User-Agent": "TecFAi-updater"}
# a zip-ből átvett fájlok / mappák (az app mappába)
PAYLOAD = ["tecf", "requirements-optional.txt", "requirements-train.txt", "README.md"]


def app_dir() -> Path:
    """A telepített program mappája (D:\\TecFAi\\app)."""
    return Path(__file__).resolve().parent.parent


def is_installed_copy() -> bool:
    # fejlesztői példányt (git munkakönyvtár) nem írunk felül – ott git pull a frissítés
    d = app_dir()
    return d.name == "app" and not (d / ".git").exists()


def installed_version() -> str:
    p = app_dir() / ".version"
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


def latest_version(timeout: float = 10) -> str:
    url = f"https://api.github.com/repos/{REPO}/commits/{urllib.parse.quote(BRANCH, safe='')}"
    req = urllib.request.Request(url, headers={**UA, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))["sha"]


def check(log: Callable[[str], None] = print) -> str | None:
    """Visszaadja az új változat azonosítóját, ha van frissítés; hálózati hibánál None."""
    try:
        latest = latest_version()
    except Exception:
        return None
    return latest if latest != installed_version() else None


def mark_current(log: Callable[[str], None] = print) -> None:
    """Telepítéskor: a most telepített változat rögzítése."""
    try:
        sha = latest_version()
    except Exception as e:
        log(f"Verzió rögzítése kihagyva ({e})")
        return
    (app_dir() / ".version").write_text(sha, encoding="utf-8")


def apply_zip(zip_path: Path, target: Path, version: str, log: Callable[[str], None] = print) -> list[str]:
    """A letöltött forráskód-zip telepítése a `target` mappába. Visszaadja a megváltozott követelményfájlokat."""
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp)
        roots = [p for p in Path(tmp).iterdir() if p.is_dir()]
        if len(roots) != 1 or not (roots[0] / "tecf" / "__init__.py").exists():
            raise RuntimeError("A letöltött csomag nem a TecF Ai programja.")
        src = roots[0]
        changed_reqs = []
        for name in PAYLOAD:
            s, d = src / name, target / name
            if not s.exists():
                continue
            if name.startswith("requirements") and (not d.exists() or d.read_bytes() != s.read_bytes()):
                changed_reqs.append(name)
            if s.is_dir():
                # előbb egy ideiglenes helyre, majd csere – egy félbeszakadt másolás ne hagyjon félkész programot
                staging = target / f".{name}.uj"
                shutil.rmtree(staging, ignore_errors=True)
                shutil.copytree(s, staging, ignore=shutil.ignore_patterns("__pycache__"))
                old = target / f".{name}.regi"
                shutil.rmtree(old, ignore_errors=True)
                if d.exists():
                    d.rename(old)
                staging.rename(d)
                shutil.rmtree(old, ignore_errors=True)
            else:
                shutil.copy2(s, d)
        # az indító .bat-ot futás közben nem szabad felülírni (a cmd soronként olvassa), ezért mellé tesszük
        bat_src, bat_dst = src / "scripts" / "tecf.bat", target.parent / "tecf.bat"
        if bat_src.exists() and bat_dst.exists() and bat_src.read_bytes() != bat_dst.read_bytes():
            shutil.copy2(bat_src, target.parent / "tecf.bat.uj")
            log("Az indító (tecf.bat) is frissült: a tecf.bat.uj fájllal cseréld le, amikor a program nem fut.")
        (target / ".version").write_text(version, encoding="utf-8")
    return changed_reqs


def update(log: Callable[[str], None] = print, force: bool = False) -> bool:
    """Frissítés a legújabb változatra. True, ha történt frissítés (újraindítás kell)."""
    if not is_installed_copy():
        log("Ez fejlesztői példány (nem a D:\\TecFAi\\app mappából fut) – itt a 'git pull' a frissítés.")
        return False
    latest = latest_version()
    if latest == installed_version() and not force:
        log("A TecF Ai naprakész.")
        return False
    log(f"Új változat letöltése ({latest[:7]})...")
    with tempfile.TemporaryDirectory() as tmp:
        zp = Path(tmp) / "tecf.zip"
        req = urllib.request.Request(f"https://codeload.github.com/{REPO}/zip/{latest}", headers=UA)
        with urllib.request.urlopen(req, timeout=120) as r, open(zp, "wb") as f:
            shutil.copyfileobj(r, f)
        changed = apply_zip(zp, app_dir(), latest, log)
    for req_file in changed:
        if req_file == "requirements-train.txt":
            try:
                import torch  # noqa: F401  – csak ha a modelltanítás telepítve van
            except ImportError:
                continue
        log(f"Új csomagok telepítése ({req_file})...")
        py = Path(sys.executable)
        py = py.with_name("python.exe") if py.name.lower() == "pythonw.exe" else py  # ablakos indításnál is
        subprocess.run([str(py), "-m", "pip", "install", "-q", "-r", str(app_dir() / req_file)],
                       check=False)
    log("✓ Frissítve. Indítsd újra a TecF Ai-t.")
    return True

