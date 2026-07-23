"""Persistent, self-updating memory for ZEMARK.

Backed by a single local SQLite file — zero external services, zero API keys.
Recall uses SQLite's built-in FTS5 full-text index (fast, dependency-free). A
semantic-embedding backend can be layered on later behind the same interface,
but keyword recall is more than enough to make the assistant feel like it
knows you, and it never leaves your machine.

Two tables matter:
    * ``memories``   — durable facts/preferences ZEMARK has learned.
    * ``turns``      — a rolling log of conversation turns, used by the
                       reflection pass (auto-learning) and by the proactive
                       engine to find loose threads.
"""

from __future__ import annotations

import contextlib
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Memory:
    id: int
    text: str
    kind: str
    confidence: float
    source: str
    created_at: float
    updated_at: float
    hits: int

    def as_line(self) -> str:
        """Render for injection into the system prompt."""
        return self.text


@dataclass
class Turn:
    id: int
    role: str  # "user" | "assistant"
    text: str
    created_at: float


_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    text        TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'fact',
    confidence  REAL NOT NULL DEFAULT 0.7,
    source      TEXT NOT NULL DEFAULT 'user',
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL,
    hits        INTEGER NOT NULL DEFAULT 0
);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
    USING fts5(text, content='memories', content_rowid='id', tokenize='unicode61');

-- keep the FTS index in sync with the base table
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, text) VALUES ('delete', old.id, old.text);
    INSERT INTO memories_fts(rowid, text) VALUES (new.id, new.text);
END;

CREATE TABLE IF NOT EXISTS turns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    role        TEXT NOT NULL,
    text        TEXT NOT NULL,
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# characters FTS5 treats as query syntax; strip them so user speech never
# produces a malformed MATCH expression.
_FTS_SPECIALS = str.maketrans({c: " " for c in '"*():^-+'})


class MemoryStore:
    """A thread-safe-enough (single connection, check_same_thread=False) store."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._conn.close()

    # -- writing ----------------------------------------------------------
    def remember(
        self,
        text: str,
        *,
        kind: str = "fact",
        confidence: float = 0.7,
        source: str = "user",
        dedupe: bool = True,
    ) -> int:
        """Store a durable memory. Returns its id.

        If ``dedupe`` and a near-identical memory already exists, the existing
        one is reinforced (confidence bumped, timestamp refreshed) instead of
        creating a duplicate — this is what keeps auto-learning from bloating.
        """
        text = text.strip()
        if not text:
            return -1

        if dedupe:
            existing = self._find_similar(text)
            if existing is not None:
                new_conf = min(1.0, max(existing.confidence, confidence) + 0.05)
                self._conn.execute(
                    "UPDATE memories SET confidence=?, updated_at=?, hits=hits+1 WHERE id=?",
                    (new_conf, time.time(), existing.id),
                )
                self._conn.commit()
                return existing.id

        now = time.time()
        cur = self._conn.execute(
            "INSERT INTO memories(text, kind, confidence, source, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?)",
            (text, kind, float(confidence), source, now, now),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def forget(self, memory_id: int) -> bool:
        cur = self._conn.execute("DELETE FROM memories WHERE id=?", (memory_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def forget_matching(self, query: str) -> int:
        """Delete memories matching a free-text query. Returns count removed."""
        hits = self.recall(query, limit=50)
        for m in hits:
            self._conn.execute("DELETE FROM memories WHERE id=?", (m.id,))
        self._conn.commit()
        return len(hits)

    # -- reading ----------------------------------------------------------
    def recall(self, query: str, *, limit: int = 6) -> list[Memory]:
        """Full-text recall, most relevant first. Bumps hit counts."""
        match = self._to_match(query)
        if not match:
            return self.recent(limit=limit)
        try:
            rows = self._conn.execute(
                "SELECT m.* FROM memories_fts f JOIN memories m ON m.id=f.rowid"
                " WHERE memories_fts MATCH ? ORDER BY bm25(memories_fts), m.confidence DESC"
                " LIMIT ?",
                (match, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            # malformed MATCH despite sanitising — fall back to recency
            return self.recent(limit=limit)

        memories = [self._row_to_memory(r) for r in rows]
        for m in memories:
            self._conn.execute("UPDATE memories SET hits=hits+1 WHERE id=?", (m.id,))
        self._conn.commit()
        return memories

    def recent(self, *, limit: int = 6) -> list[Memory]:
        rows = self._conn.execute(
            "SELECT * FROM memories ORDER BY confidence DESC, updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_memory(r) for r in rows]

    def all(self) -> list[Memory]:
        rows = self._conn.execute("SELECT * FROM memories ORDER BY created_at").fetchall()
        return [self._row_to_memory(r) for r in rows]

    def count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0])

    # -- conversation log (for reflection + proactivity) ------------------
    def log_turn(self, role: str, text: str) -> None:
        text = text.strip()
        if not text:
            return
        self._conn.execute(
            "INSERT INTO turns(role, text, created_at) VALUES(?,?,?)",
            (role, text, time.time()),
        )
        self._conn.commit()

    def recent_turns(self, *, limit: int = 20) -> list[Turn]:
        rows = self._conn.execute(
            "SELECT * FROM turns ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        turns = [
            Turn(id=r["id"], role=r["role"], text=r["text"], created_at=r["created_at"])
            for r in rows
        ]
        turns.reverse()  # chronological
        return turns

    def turns_since(self, since_ts: float) -> list[Turn]:
        rows = self._conn.execute(
            "SELECT * FROM turns WHERE created_at > ? ORDER BY id", (since_ts,)
        ).fetchall()
        return [
            Turn(id=r["id"], role=r["role"], text=r["text"], created_at=r["created_at"])
            for r in rows
        ]

    # -- simple key/value meta -------------------------------------------
    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta(key, value) VALUES(?,?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self._conn.commit()

    # -- helpers ----------------------------------------------------------
    def _find_similar(self, text: str) -> Memory | None:
        hits = self.recall(text, limit=1)
        if not hits:
            return None
        candidate = hits[0]
        if _normalized_overlap(candidate.text, text) >= 0.6:
            return candidate
        return None

    @staticmethod
    def _to_match(query: str) -> str:
        cleaned = query.translate(_FTS_SPECIALS).strip()
        tokens = [t for t in cleaned.split() if len(t) > 1]
        if not tokens:
            return ""
        # OR the tokens so partial matches still surface relevant memories.
        return " OR ".join(tokens)

    @staticmethod
    def _row_to_memory(r: sqlite3.Row) -> Memory:
        return Memory(
            id=r["id"],
            text=r["text"],
            kind=r["kind"],
            confidence=r["confidence"],
            source=r["source"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
            hits=r["hits"],
        )


def _normalized_overlap(a: str, b: str) -> float:
    """Cheap token-set Jaccard overlap, used only for dedupe."""
    sa = {t for t in a.lower().split() if len(t) > 2}
    sb = {t for t in b.lower().split() if len(t) > 2}
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)
