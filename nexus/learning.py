"""Tanuló üzem és önfejlesztés.

- learn_topic:   netes keresés -> oldalak letöltése -> tudásbázisba; opcionálisan más AI-któl is
                 megkérdezi a témát; a nyelvi modellel tényeket és kapcsolódó altémákat von ki.
- learn_loop:    a tanulási sor folyamatos feldolgozása (időkorláttal)
- ingest_path:   helyi fájlok/mappák feldolgozása
- reflect:       rossznak értékelt válaszok újragondolása, javított válasz tárolása
- seed_curriculum: alap tanterv a fő szakterületekhez
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from nexus.brain import Brain
from nexus.providers import ProviderError, get_provider
from nexus.tools import web
from nexus.tools.documents import TEXT_EXT, extract_text

CURRICULUM = {
    "rendszergazda": [
        "Windows Server Active Directory administration best practices",
        "PowerShell scripting for system administrators",
        "Linux server administration systemd networking troubleshooting",
        "Group Policy troubleshooting gpresult",
        "Windows event log troubleshooting common event IDs",
        "Backup strategy 3-2-1 Veeam Windows Server Backup",
        "Hyper-V and VMware ESXi administration",
        "DNS DHCP server configuration troubleshooting",
    ],
    "programozás": [
        "Python best practices and standard library", "C# .NET modern features",
        "JavaScript TypeScript modern patterns", "Java Spring Boot basics", "Go language concurrency",
        "Rust ownership borrowing", "C++ modern C++20 features", "SQL query optimization indexes",
        "Bash scripting best practices", "Git workflow branching", "software design patterns",
        "unit testing best practices",
    ],
    "hálózat": [
        "Cisco IOS VLAN trunk configuration", "Cisco IOS OSPF configuration", "MikroTik RouterOS firewall NAT",
        "Juniper Junos basic configuration", "subnetting VLSM", "IPsec site-to-site VPN configuration",
        "WireGuard VPN setup", "network troubleshooting methodology OSI",
    ],
    "dokumentumok": [
        "technical documentation writing best practices", "IT runbook template",
        "network documentation template", "document summarization techniques",
    ],
}

EXTRACT_PROMPT = """Az alábbi szövegből (téma: {topic}) vonj ki legfeljebb 8 fontos, önállóan is érthető,
ellenőrizhető tényt vagy gyakorlati tudnivalót, valamint legfeljebb 3 kapcsolódó altémát, amit érdemes
még megtanulni. Csak JSON-t adj vissza: {{"facts": ["..."], "subtopics": ["..."]}}

SZÖVEG:
{text}"""


class Learner:
    def __init__(self, brain: Brain):
        self.brain = brain
        self.kb = brain.kb
        self.cfg = brain.cfg
        self.log = brain.log

    # ---------------- web ----------------
    def learn_topic(self, topic: str, depth: int = 1) -> int:
        """Egy téma megtanulása. Visszaadja az új források számát."""
        self.log(f"📚 Tanulás: {topic}")
        added = 0
        texts: list[str] = []
        try:
            results = web.search(topic, self.cfg.learn_max_pages_per_topic)
        except Exception as e:
            self.log(f"  keresési hiba: {e}")
            results = []
        for r in results:
            try:
                text = web.fetch_text(r["url"])
            except Exception as e:
                self.log(f"  × {r['url']} ({type(e).__name__})")
                continue
            if len(text) < 300:
                continue
            if self.kb.add_document(text[:60000], r["url"], "web", r["title"], trust=0.5):
                added += 1
                texts.append(text[:6000])
                self.log(f"  ✓ {r['title'][:70]}")
            time.sleep(self.cfg.learn_request_delay_s)
        added += self.learn_from_ais(topic, texts)
        if texts:
            self._distill(topic, "\n\n".join(texts)[:12000], depth)
        return added

    # ---------------- más AI-k ----------------
    def learn_from_ais(self, topic: str, texts: list[str] | None = None,
                       providers: list[str] | None = None) -> int:
        """A témát megkérdezi a beállított AI szolgáltatóktól; a válaszokat forrásmegjelöléssel tárolja."""
        added = 0
        for name in providers or self.cfg.learn_from_ai_providers:
            try:
                p = get_provider(name, self.brain.keys)
                if not p.available():
                    continue
                ans = p.chat([{"role": "user", "content":
                               f"Magyarázd el szakmailag pontosan, gyakorlati példákkal: {topic}"}],
                             max_tokens=1500)
            except ProviderError as e:
                self.log(f"  × {name}: {e}")
                continue
            if self.kb.add_document(ans, f"ai:{p.label}", "ai", f"{topic} ({p.spec.title})", trust=0.6):
                added += 1
                if texts is not None:
                    texts.append(ans[:4000])
                self.log(f"  ✓ {p.spec.title} válasza eltárolva")
        return added

    def _distill(self, topic: str, text: str, depth: int) -> None:
        prov = self.brain.provider()
        if prov is None:
            return
        try:
            raw = prov.chat([{"role": "user", "content": EXTRACT_PROMPT.format(topic=topic, text=text)}],
                            temperature=0.1, max_tokens=1200)
            m = re.search(r"\{.*\}", raw, re.S)
            data = json.loads(m.group(0)) if m else {}
        except (ProviderError, json.JSONDecodeError) as e:
            self.log(f"  (tény kivonás kihagyva: {e})")
            return
        for f in data.get("facts", [])[:8]:
            if isinstance(f, str) and len(f) > 15:
                self.kb.remember(f.strip(), category=topic[:60], confidence=0.55)
        if depth > 0:
            for s in data.get("subtopics", [])[:3]:
                if isinstance(s, str) and s.strip():
                    self.kb.queue_topic(s.strip(), priority=3, reason=f"altéma: {topic}")
        self.log(f"  ★ {len(data.get('facts', []))} tény, {len(data.get('subtopics', []))} altéma")

    def learn_loop(self, minutes: float = 30, max_topics: int = 50) -> int:
        """Tanulási sor feldolgozása, amíg van idő/téma."""
        deadline = time.time() + minutes * 60
        done = 0
        while time.time() < deadline and done < max_topics:
            batch = self.kb.next_topics(1)
            if not batch:
                self.log("A tanulási sor üres.")
                break
            t = batch[0]
            try:
                n = self.learn_topic(t["topic"], depth=1 if t["priority"] >= 4 else 0)
                self.kb.mark_topic(t["id"], "done" if n else "failed")
            except Exception as e:
                self.log(f"  hiba: {e}")
                self.kb.mark_topic(t["id"], "failed")
            done += 1
        return done

    def seed_curriculum(self, areas: list[str] | None = None) -> int:
        n = 0
        for area, topics in CURRICULUM.items():
            if areas and area not in areas:
                continue
            for t in topics:
                self.kb.queue_topic(t, priority=5, reason=f"alap tanterv: {area}")
                n += 1
        return n

    # ---------------- helyi fájlok ----------------
    def ingest_path(self, path: str | Path) -> int:
        p = Path(path)
        files = [p] if p.is_file() else [f for f in p.rglob("*") if f.is_file()]
        ok_ext = TEXT_EXT | {".pdf", ".docx", ".xlsx", ".pptx", ".html", ".htm"}
        added = 0
        for f in files:
            if f.suffix.lower() not in ok_ext or f.stat().st_size > 50_000_000:
                continue
            try:
                text = extract_text(f)
            except Exception as e:
                self.log(f"  × {f.name}: {e}")
                continue
            if self.kb.add_document(text, str(f), "file", f.name, trust=0.7):
                added += 1
                self.log(f"  ✓ {f.name}")
        return added

    # ---------------- önreflexió ----------------
    def reflect(self, limit: int = 10) -> int:
        """Rossznak értékelt válaszok javítása: tanul a témáról, majd újra válaszol."""
        rows = self.kb.db.execute(
            "SELECT id, question FROM conversations WHERE rating < 0 ORDER BY created DESC LIMIT ?", (limit,)
        ).fetchall()
        for r in rows:
            self.learn_topic(r["question"][:200], depth=0)
            answer, conv_id = self.brain.ask(r["question"])
            self.kb.db.execute("UPDATE conversations SET rating=0 WHERE id=?", (r["id"],))
            self.kb.db.commit()
            self.log(f"↻ Újragondolva (#{r['id']} -> #{conv_id}). Értékeld: nexus rate {conv_id} good|bad")
        return len(rows)
