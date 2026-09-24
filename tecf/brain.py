"""A TecF Ai "agya": modellválasztás, tudás-előhívás, eszközhasználat, önfejlesztés.

Válaszadás menete:
  1. Tudásbázis + emlékek keresése a kérdéshez (offline RAG)
  2. Modell kiválasztása: helyi (Ollama stb.) -> felhő tartalék -> tisztán offline tudásbázis mód
  3. Eszközhasználati ciklus (max. `max_steps` lépés)
  4. Naplózás; ha nem volt releváns tudás, a téma bekerül a tanulási sorba
"""
from __future__ import annotations

import json
from typing import Callable

from tecf.config import Config
from tecf.knowledge import KnowledgeBase
from tecf.providers import Provider, ProviderError, get_provider
from tecf.tools import REGISTRY, Tool, describe_tools, parse_tool_calls, run_tool

IDENTITY = """Te TecF Ai vagy, egy saját gépen futó, folyamatosan tanuló mesterséges intelligencia.
Szakterületeid:
- profi rendszergazda (Windows Server, Active Directory, Linux, virtualizáció, mentés, biztonság)
- profi programozó minden nyelven (Python, C/C++, C#, Java, JavaScript/TypeScript, Go, Rust, PHP, SQL,
  PowerShell, Bash, ...), tiszta, tesztelt, működő kódot írsz
- dokumentumok olvasása, értelmezése, összefoglalása és professzionális dokumentumok készítése
- internetes kutatás, források ellenőrzése
- hálózati eszközök (Cisco, MikroTik, Juniper, HP/Aruba, Huawei, Fortinet) konfigurálása és hibaelhárítása
- munkavégzés a gépen eszközökkel

Szabályok:
- Válaszolj a felhasználó nyelvén (alapból magyarul), tömören és pontosan.
- Ha a TUDÁSBÁZIS tartalmaz releváns részt, arra támaszkodj és hivatkozz a forrásra.
- Ha nem tudsz valamit biztosan, mondd meg, és javasold, hogy tanuld meg (learn).
- Romboló műveletet (törlés, formázás, eszköz konfiguráció módosítás) csak kifejezett kérésre végezz.

ESZKÖZÖK – ha eszközt akarsz használni, válaszodban PONTOSAN így jelezd (több blokk is lehet):
```tool
{"tool": "<név>", "args": {...}}
```
Az eszköz eredményét a következő üzenetben kapod meg. Ha kész vagy, eszközblokk nélkül adj végleges választ.
Elérhető eszközök:
"""


class Brain:
    def __init__(self, cfg: Config, kb: KnowledgeBase | None = None,
                 confirm: Callable[[str], bool] | None = None, log: Callable[[str], None] = print):
        self.cfg = cfg
        self.kb = kb or KnowledgeBase(cfg.db_path)
        self.keys = cfg.load_keys()
        self.confirm = confirm
        self.log = log
        self._provider: Provider | None = None
        self._register_knowledge_tools()

    # ---------------- modellválasztás ----------------
    def candidates(self) -> list[Provider]:
        out = [get_provider(self.cfg.local_provider, self.keys, self.cfg.local_model)]
        if not self.cfg.offline_only:
            for name in self.cfg.fallback_providers:
                try:
                    out.append(get_provider(name, self.keys))
                except ProviderError:
                    pass
        return out

    def provider(self, refresh: bool = False) -> Provider | None:
        if self._provider is None or refresh:
            self._provider = next((p for p in self.candidates() if p.available()), None)
        return self._provider

    # ---------------- tudás eszközök ----------------
    def _register_knowledge_tools(self) -> None:
        kb = self.kb

        def search_knowledge(query: str) -> str:
            hits = kb.search(query, self.cfg.retrieval_top_k)
            return "\n---\n".join(f"[{h.source}]\n{h.text}" for h in hits) or "Nincs találat a tudásbázisban."

        def remember(fact: str, category: str = "general") -> str:
            kb.remember(fact, category)
            return "Megjegyeztem."

        def queue_learning(topic: str, priority: int = 6) -> str:
            kb.queue_topic(topic, priority, "a modell kérte")
            return f"Tanulási sorba téve: {topic}"

        for fn, desc in [(search_knowledge, "Keresés a saját offline tudásbázisban."),
                         (remember, "Tartós tény/tanulság megjegyzése (felhasználó, környezet, megoldás)."),
                         (queue_learning, "Téma felvétele a tanulási sorba, amit később a netről megtanulok.")]:
            REGISTRY[fn.__name__] = Tool(fn.__name__, fn, desc)

    # ---------------- kontextus ----------------
    def build_context(self, question: str) -> tuple[str, int]:
        hits = self.kb.search(question, self.cfg.retrieval_top_k)
        mems = self.kb.recall(question, 5)
        parts = []
        if mems:
            parts.append("EMLÉKEK:\n" + "\n".join(f"- {m['text']} (bizalom {m['confidence']:.1f})" for m in mems))
        if hits:
            parts.append("TUDÁSBÁZIS:\n" + "\n---\n".join(f"[forrás: {h.source}]\n{h.text}" for h in hits))
        return "\n\n".join(parts), len(hits) + len(mems)

    def system_prompt(self, context: str) -> str:
        sp = IDENTITY + describe_tools()
        if context:
            sp += "\n\n" + context
        return sp

    # ---------------- válasz ----------------
    def ask(self, question: str, history: list[dict] | None = None, max_steps: int = 8) -> tuple[str, int]:
        """Visszaad: (válasz, beszélgetés id az értékeléshez)."""
        context, n_hits = self.build_context(question)
        prov = self.provider()
        if prov is None:
            answer = self._offline_answer(question, context)
            model = "offline-kb"
        else:
            model = prov.label
            answer = self._agent_loop(prov, question, history or [], context, max_steps)
        if n_hits == 0:
            self.kb.queue_topic(question[:200], priority=4, reason="tudáshiány a kérdésnél")
        conv_id = self.kb.log_conversation(question, answer, model, n_hits)
        return answer, conv_id

    def _agent_loop(self, prov: Provider, question: str, history: list[dict], context: str,
                    max_steps: int) -> str:
        system = self.system_prompt(context)
        msgs = list(history) + [{"role": "user", "content": question}]
        reply = ""
        for _ in range(max_steps):
            try:
                reply = prov.chat(msgs, system=system)
            except ProviderError as e:
                self.log(f"[{prov.label}] hiba: {e} – próbálom a következő modellt")
                nxt = self.provider(refresh=True)
                if nxt is None or nxt is prov:
                    return self._offline_answer(question, context)
                prov = nxt
                continue
            calls = parse_tool_calls(reply)
            if not calls:
                return reply
            results = []
            for c in calls:
                self.log(f"  ⚙ {c.get('tool')} {json.dumps(c.get('args', {}), ensure_ascii=False)[:150]}")
                t = REGISTRY.get(c.get("tool", ""))
                need_confirm = t is not None and t.dangerous and (
                    self.cfg.confirm_network_changes if t.name.startswith("device_")
                    else self.cfg.confirm_system_commands)
                results.append(f"### {c.get('tool')}\n" + run_tool(c, self.confirm if need_confirm else None))
            msgs.append({"role": "assistant", "content": reply})
            msgs.append({"role": "user", "content": "ESZKÖZ EREDMÉNYEK:\n" + "\n\n".join(results)})
        return reply + "\n\n(A lépéskorlát elérve.)"

    @staticmethod
    def _offline_answer(question: str, context: str) -> str:
        if not context:
            return ("Nincs elérhető nyelvi modell és a tudásbázisban sincs erről információ. "
                    "Indítsd el az Ollamát (offline) vagy adj meg API kulcsot, illetve futtasd a tanuló üzemet: "
                    f'tecf learn "{question[:60]}"')
        return "Offline tudásbázis mód (nincs nyelvi modell). A legrelevánsabb ismereteim:\n\n" + context
