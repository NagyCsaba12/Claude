"""Rendszergazdai eszközök: parancs futtatás, rendszerinfó, folyamatok."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys

from tecf.tools import tool

IS_WIN = sys.platform.startswith("win")


@tool("Shell parancs futtatása (Windows: PowerShell, Linux: bash). Kimenetet ad vissza.", dangerous=True)
def run_command(command: str, timeout: int = 120) -> str:
    if IS_WIN:
        argv = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
    else:
        argv = ["bash", "-lc", command]
    p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                       encoding="utf-8", errors="replace")
    return f"[kilépési kód {p.returncode}]\n{p.stdout}{p.stderr}"


@tool("Python kód futtatása külön folyamatban (számítás, szkript teszt).", dangerous=True)
def run_python(code: str, timeout: int = 120) -> str:
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=timeout,
                       encoding="utf-8", errors="replace")
    return f"[kilépési kód {p.returncode}]\n{p.stdout}{p.stderr}"


@tool("Rendszer összefoglaló: OS, CPU, memória, lemezek.")
def system_info() -> str:
    lines = [f"OS: {platform.platform()}", f"Gép: {platform.node()}", f"CPU: {platform.processor()} "
             f"({os.cpu_count()} mag)", f"Python: {sys.version.split()[0]}"]
    drives = [f"{c}:/" for c in "CDEFGH"] if IS_WIN else ["/"]
    for d in drives:
        if os.path.exists(d):
            u = shutil.disk_usage(d)
            lines.append(f"Lemez {d}: {u.free / 2**30:.1f} GB szabad / {u.total / 2**30:.1f} GB")
    try:
        import psutil  # opcionális
        vm = psutil.virtual_memory()
        lines.append(f"RAM: {vm.available / 2**30:.1f} GB szabad / {vm.total / 2**30:.1f} GB")
    except ImportError:
        pass
    return "\n".join(lines)


@tool("Futó folyamatok listája (név szűrővel).")
def list_processes(name_filter: str = "") -> str:
    cmd = ["tasklist"] if IS_WIN else ["ps", "aux"]
    out = subprocess.run(cmd, capture_output=True, text=True, errors="replace").stdout
    if name_filter:
        out = "\n".join(line for line in out.splitlines() if name_filter.lower() in line.lower())
    return out
