"""Eszközök, amelyeket az AI használhat: rendszer, fájlok, dokumentumok, web, hálózat.

Az eszközhívás modellfüggetlen JSON protokollal működik, így bármely helyi
vagy felhő modellel használható:

    ```tool
    {"tool": "run_command", "args": {"command": "ipconfig /all"}}
    ```
"""
from __future__ import annotations

import inspect
import json
import re
from dataclasses import dataclass
from typing import Callable


@dataclass
class Tool:
    name: str
    func: Callable[..., str]
    description: str
    dangerous: bool = False   # megerősítést kér futtatás előtt

    def signature(self) -> str:
        params = ", ".join(inspect.signature(self.func).parameters)
        return f"{self.name}({params})"


REGISTRY: dict[str, Tool] = {}


def tool(description: str, dangerous: bool = False):
    def deco(fn):
        REGISTRY[fn.__name__] = Tool(fn.__name__, fn, description, dangerous)
        return fn
    return deco


def load_all() -> dict[str, Tool]:
    from tecf.tools import documents, files, network, system, web  # noqa: F401  (regisztráció)
    return REGISTRY


def describe_tools() -> str:
    return "\n".join(f"- {t.signature()}: {t.description}" for t in load_all().values())


TOOL_RE = re.compile(r"```tool\s*(\{.*?\})\s*```", re.S)


def parse_tool_calls(text: str) -> list[dict]:
    calls = []
    for m in TOOL_RE.finditer(text):
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict) and "tool" in obj:
                calls.append(obj)
        except json.JSONDecodeError:
            continue
    return calls


def run_tool(call: dict, confirm: Callable[[str], bool] | None = None) -> str:
    t = load_all().get(call.get("tool", ""))
    if t is None:
        return f"HIBA: nincs ilyen eszköz: {call.get('tool')}"
    args = call.get("args") or {}
    if t.dangerous and confirm is not None and not confirm(f"{t.name} {json.dumps(args, ensure_ascii=False)}"):
        return "A felhasználó elutasította a műveletet."
    try:
        out = t.func(**args)
    except Exception as e:  # az eszköz hibája visszamegy a modellnek, hogy javíthasson
        return f"HIBA ({type(e).__name__}): {e}"
    out = str(out)
    return out if len(out) <= 12000 else out[:12000] + "\n...[levágva]"
