"""SQLite connection for scoped memory."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path


class MemoryDatabase:
    """Own one SQLite file for memory records."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS records (
                id TEXT PRIMARY KEY,
                scope TEXT NOT NULL,
                scope_key TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS records_scope ON records (scope, scope_key, created_at, id)"
        )
        self._connection.commit()

    def lock(self) -> threading.Lock:
        return self._lock

    @property
    def connection(self) -> sqlite3.Connection:
        return self._connection
