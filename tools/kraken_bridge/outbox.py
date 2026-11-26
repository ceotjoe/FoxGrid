"""Persistent outbox: messages survive a lost mobile connection and a reboot.

Every message is stored in SQLite before it is sent and removed only after the broker acknowledged
it (QoS 1). Bearing IDs are generated once and kept, so a message that is delivered twice is
recognised by the FoxGrid ingest and ignored.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Item:
    id: str
    topic: str
    payload: str


class Outbox:
    def __init__(self, path: str = ":memory:") -> None:
        self._db = sqlite3.connect(path)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS outbox ("
            " id TEXT PRIMARY KEY, topic TEXT NOT NULL, payload TEXT NOT NULL,"
            " created_at REAL NOT NULL)"
        )
        self._db.commit()

    def enqueue(self, item_id: str, topic: str, payload: dict[str, Any]) -> None:
        self._db.execute(
            "INSERT OR IGNORE INTO outbox (id, topic, payload, created_at) VALUES (?, ?, ?, ?)",
            (item_id, topic, json.dumps(payload), time.time()),
        )
        self._db.commit()

    def pending(self, limit: int = 50) -> list[Item]:
        rows = self._db.execute(
            "SELECT id, topic, payload FROM outbox ORDER BY created_at, rowid LIMIT ?", (limit,)
        ).fetchall()
        return [Item(*row) for row in rows]

    def done(self, item_id: str) -> None:
        self._db.execute("DELETE FROM outbox WHERE id = ?", (item_id,))
        self._db.commit()

    def __len__(self) -> int:
        return int(self._db.execute("SELECT count(*) FROM outbox").fetchone()[0])

    def close(self) -> None:
        self._db.close()
