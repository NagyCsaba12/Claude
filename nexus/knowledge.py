"""Saját tudásbázis: SQLite + FTS5 teljes szöveges keresés (BM25), teljesen offline.

Táblák:
  sources      – honnan jött a tudás (weboldal, fájl, AI szolgáltató, beszélgetés)
  chunks       – feldarabolt szövegrészek (FTS5 indexszel)
  memories     – tömör tények / tanulságok, megbízhatósági pontszámmal
  conversations– minden kérdés-válasz, értékeléssel (önfejlesztéshez)
  topics       – tanulási sor (mit kell még megtanulni)
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,              -- web | file | ai | chat | manual
    uri TEXT NOT NULL,
    title TEXT,
    content_hash TEXT UNIQUE,
    trust REAL DEFAULT 0.5,
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    text TEXT NOT NULL,
    uses INTEGER DEFAULT 0
);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text, content='chunks', content_rowid='id', tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY,
    text TEXT NOT NULL UNIQUE,
    category TEXT DEFAULT 'general',
    confidence REAL DEFAULT 0.5,
    created REAL NOT NULL,
    updated REAL NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    text, category, content='memories', content_rowid='id', tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, text, category) VALUES (new.id, new.text, new.category);
END;
CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, text, category) VALUES ('delete', old.id, old.text, old.category);
END;
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    model TEXT,
    context_hits INTEGER DEFAULT 0,
    rating INTEGER,                  -- -1 rossz, 0 semleges, 1 jó
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY,
    topic TEXT NOT NULL UNIQUE,
    priority INTEGER DEFAULT 5,
    status TEXT DEFAULT 'pending',   -- pending | done | failed
    reason TEXT,
    created REAL NOT NULL,
    learned REAL
);
"""


@dataclass
class Hit:
    text: str
    score: float
    source: str
    kind: str
    chunk_id: int


def chunk_text(text: str, size: int = 900, overlap: int = 150) -> list[str]:
    """Bekezdés-tudatos darabolás kb. `size` karakteres, átfedő részekre."""
    text = re.sub(r"\r\n?", "\n", text)
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for p in paras:
        if len(buf) + len(p) + 2 <= size:
            buf = f"{buf}\n\n{p}" if buf else p
            continue
        if buf:
            chunks.append(buf)
            buf = buf[-overlap:] + "\n\n" if overlap else ""
        while len(p) > size:
            chunks.append((buf + p[:size]).strip())
            p = p[size - overlap:]
            buf = ""
        buf = (buf + p).strip()
    if buf:
        chunks.append(buf)
    return chunks


def _fts_query(q: str) -> str:
    words = re.findall(r"\w{2,}", q.lower())
    # Elavult szavak kiszűrése nélkül: OR kapcsolat, prefix egyezéssel (ragozott magyar szavak miatt)
    return " OR ".join(f'"{w}"*' for w in dict.fromkeys(words)) or '""'


class KnowledgeBase:
    def __init__(self, path: str | Path, threaded: bool = False):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # threaded=True: több szálból is használható (a hívó felel a zárolásért)
        self.db = sqlite3.connect(str(self.path), check_same_thread=not threaded)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # ---------------- tudás felvétele ----------------
    def add_document(self, text: str, uri: str, kind: str = "manual", title: str | None = None,
                     trust: float = 0.5) -> int | None:
        """Szöveg felvétele. Visszaadja a source id-t, vagy None-t ha már ismert (duplikátum)."""
        text = text.strip()
        if len(text) < 20:
            return None
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if self.db.execute("SELECT 1 FROM sources WHERE content_hash=?", (h,)).fetchone():
            return None
        cur = self.db.execute(
            "INSERT INTO sources(kind, uri, title, content_hash, trust, created) VALUES (?,?,?,?,?,?)",
            (kind, uri, title, h, trust, time.time()),
        )
        sid = cur.lastrowid
        self.db.executemany(
            "INSERT INTO chunks(source_id, seq, text) VALUES (?,?,?)",
            [(sid, i, c) for i, c in enumerate(chunk_text(text))],
        )
        self.db.commit()
        return sid

    def remember(self, fact: str, category: str = "general", confidence: float = 0.6) -> None:
        """Tömör tény/tanulság mentése; ismételt megerősítés növeli a megbízhatóságot."""
        now = time.time()
        row = self.db.execute("SELECT id, confidence FROM memories WHERE text=?", (fact,)).fetchone()
        if row:
            conf = min(1.0, row["confidence"] + (1 - row["confidence"]) * 0.3)
            self.db.execute("UPDATE memories SET confidence=?, updated=? WHERE id=?", (conf, now, row["id"]))
        else:
            self.db.execute(
                "INSERT INTO memories(text, category, confidence, created, updated) VALUES (?,?,?,?,?)",
                (fact, category, confidence, now, now),
            )
        self.db.commit()

    def forget(self, memory_id: int) -> None:
        self.db.execute("DELETE FROM memories WHERE id=?", (memory_id,))
        self.db.commit()

    # ---------------- keresés ----------------
    def search(self, query: str, k: int = 6) -> list[Hit]:
        q = _fts_query(query)
        rows = self.db.execute(
            """SELECT c.id, c.text, bm25(chunks_fts) AS rank, s.uri, s.kind, s.trust
               FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid
               JOIN sources s ON s.id = c.source_id
               WHERE chunks_fts MATCH ? ORDER BY rank LIMIT ?""",
            (q, k * 3),
        ).fetchall()
        hits = []
        for r in rows:
            # bm25: kisebb = jobb. Megbízhatóság és korábbi hasznosság súlyozása.
            score = -r["rank"] * (0.5 + r["trust"])
            hits.append(Hit(r["text"], score, r["uri"], r["kind"], r["id"]))
        hits.sort(key=lambda h: h.score, reverse=True)
        hits = hits[:k]
        if hits:
            self.db.executemany("UPDATE chunks SET uses = uses + 1 WHERE id=?", [(h.chunk_id,) for h in hits])
            self.db.commit()
        return hits

    def recall(self, query: str, k: int = 5) -> list[sqlite3.Row]:
        return self.db.execute(
            """SELECT m.id, m.text, m.category, m.confidence FROM memories_fts
               JOIN memories m ON m.id = memories_fts.rowid
               WHERE memories_fts MATCH ? ORDER BY bm25(memories_fts) / (0.5 + m.confidence) LIMIT ?""",
            (_fts_query(query), k),
        ).fetchall()

    # ---------------- beszélgetések, önértékelés ----------------
    def log_conversation(self, question: str, answer: str, model: str, context_hits: int) -> int:
        cur = self.db.execute(
            "INSERT INTO conversations(question, answer, model, context_hits, created) VALUES (?,?,?,?,?)",
            (question, answer, model, context_hits, time.time()),
        )
        self.db.commit()
        return cur.lastrowid

    def rate(self, conv_id: int, rating: int) -> None:
        self.db.execute("UPDATE conversations SET rating=? WHERE id=?", (rating, conv_id))
        row = self.db.execute("SELECT question, answer FROM conversations WHERE id=?", (conv_id,)).fetchone()
        self.db.commit()
        if row and rating > 0:
            # A jónak értékelt válasz maga is tudássá válik
            self.add_document(f"K: {row['question']}\n\nV: {row['answer']}", f"chat:{conv_id}", "chat",
                              title=row["question"][:80], trust=0.8)
        elif row and rating < 0:
            self.queue_topic(row["question"], priority=8, reason="rossznak értékelt válasz")

    def export_training_data(self, path: str | Path) -> int:
        """Jónak értékelt beszélgetések exportja JSONL-be (LoRA finomhangoláshoz)."""
        rows = self.db.execute("SELECT question, answer FROM conversations WHERE rating > 0").fetchall()
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps({"messages": [
                    {"role": "user", "content": r["question"]},
                    {"role": "assistant", "content": r["answer"]},
                ]}, ensure_ascii=False) + "\n")
        return len(rows)

    # ---------------- tanulási sor ----------------
    def queue_topic(self, topic: str, priority: int = 5, reason: str = "") -> None:
        self.db.execute(
            """INSERT INTO topics(topic, priority, reason, created) VALUES (?,?,?,?)
               ON CONFLICT(topic) DO UPDATE SET priority=max(priority, excluded.priority), status='pending'""",
            (topic.strip(), priority, reason, time.time()),
        )
        self.db.commit()

    def next_topics(self, n: int = 5) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM topics WHERE status='pending' ORDER BY priority DESC, created LIMIT ?", (n,)
        ).fetchall()

    def mark_topic(self, topic_id: int, status: str) -> None:
        self.db.execute("UPDATE topics SET status=?, learned=? WHERE id=?", (status, time.time(), topic_id))
        self.db.commit()

    def stats(self) -> dict[str, int]:
        q = lambda sql: self.db.execute(sql).fetchone()[0]  # noqa: E731
        return {
            "források": q("SELECT count(*) FROM sources"),
            "szövegrészek": q("SELECT count(*) FROM chunks"),
            "emlékek": q("SELECT count(*) FROM memories"),
            "beszélgetések": q("SELECT count(*) FROM conversations"),
            "jó értékelés": q("SELECT count(*) FROM conversations WHERE rating > 0"),
            "tanulandó téma": q("SELECT count(*) FROM topics WHERE status='pending'"),
            "megtanult téma": q("SELECT count(*) FROM topics WHERE status='done'"),
        }
