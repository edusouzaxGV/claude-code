"""Time-based reminders for ZEMARK.

A tiny SQLite-backed store (same database file as memory). Reminders are created
by the ``set_reminder`` tool and surfaced by the proactive engine's
``ReminderDueTrigger`` when their time arrives — so ZEMARK actually says
"lembrete: reunião" out loud instead of just storing a note.
"""

from __future__ import annotations

import contextlib
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reminders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    text        TEXT NOT NULL,
    due_ts      REAL NOT NULL,
    created_at  REAL NOT NULL,
    fired       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(fired, due_ts);
"""


@dataclass
class Reminder:
    id: int
    text: str
    due_ts: float
    created_at: float
    fired: bool


class ReminderStore:
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

    def add(self, text: str, due_ts: float) -> int:
        cur = self._conn.execute(
            "INSERT INTO reminders(text, due_ts, created_at, fired) VALUES(?,?,?,0)",
            (text.strip(), float(due_ts), time.time()),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def due(self, now_ts: float | None = None) -> list[Reminder]:
        now_ts = time.time() if now_ts is None else now_ts
        rows = self._conn.execute(
            "SELECT * FROM reminders WHERE fired=0 AND due_ts<=? ORDER BY due_ts",
            (now_ts,),
        ).fetchall()
        return [self._row(r) for r in rows]

    def mark_fired(self, reminder_id: int) -> None:
        self._conn.execute("UPDATE reminders SET fired=1 WHERE id=?", (reminder_id,))
        self._conn.commit()

    def upcoming(self, *, limit: int = 10) -> list[Reminder]:
        rows = self._conn.execute(
            "SELECT * FROM reminders WHERE fired=0 ORDER BY due_ts LIMIT ?", (limit,)
        ).fetchall()
        return [self._row(r) for r in rows]

    def cancel(self, reminder_id: int) -> bool:
        cur = self._conn.execute("DELETE FROM reminders WHERE id=?", (reminder_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def cancel_matching(self, query: str) -> int:
        like = f"%{query.strip()}%"
        cur = self._conn.execute(
            "DELETE FROM reminders WHERE fired=0 AND text LIKE ?", (like,)
        )
        self._conn.commit()
        return cur.rowcount

    @staticmethod
    def _row(r: sqlite3.Row) -> Reminder:
        return Reminder(
            id=r["id"],
            text=r["text"],
            due_ts=r["due_ts"],
            created_at=r["created_at"],
            fired=bool(r["fired"]),
        )
