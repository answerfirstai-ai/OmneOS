"""SQLite state shared by the HTTP server, planner and scheduler."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.sqlite import configure_sqlite
from omne.secrets.redact import redact_text


class Store:
    def __init__(self, path: Path, emit: Callable[[str, str | None], None] | None = None) -> None:
        self.emit = emit
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        configure_sqlite(self.db)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, data TEXT, 
                PRIMARY KEY(kind,id));
            CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, 
                time REAL, harness TEXT, message TEXT);
            CREATE TABLE IF NOT EXISTS usage (day TEXT PRIMARY KEY, tokens INTEGER NOT NULL);
        """)
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS artifact_harness "
            "ON records(kind, json_extract(data, '$.harness_id'))"
        )
        self.db.commit()

    def put(self, kind: str, data: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            self.db.execute(
                "INSERT INTO records VALUES (?,?,?) "
                "ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data "
                "WHERE records.data != excluded.data",
                (kind, data["id"], json.dumps(data)),
            )
            self.db.commit()
        return data

    def get(self, kind: str, id: str) -> dict[str, Any] | None:
        with self.lock:
            row = self.db.execute(
                "SELECT data FROM records WHERE kind=? AND id=?", (kind, id)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def all(self, kind: str) -> list[dict[str, Any]]:
        with self.lock:
            return [
                json.loads(row[0])
                for row in self.db.execute(
                    "SELECT data FROM records WHERE kind=? ORDER BY rowid", (kind,)
                )
            ]

    def recent(self, kind: str, limit: int = 30) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.db.execute(
                "SELECT data FROM records WHERE kind=? ORDER BY rowid DESC LIMIT ?",
                (kind, limit),
            ).fetchall()
        return [json.loads(row[0]) for row in reversed(rows)]

    def artifacts(self, harness_id: str) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.db.execute(
                "SELECT data FROM records WHERE kind='artifact' "
                "AND json_extract(data, '$.harness_id')=? ORDER BY rowid",
                (harness_id,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def event(self, message: str, harness: str | None = None) -> None:
        message = redact_text(message)
        with self.lock:
            self.db.execute(
                "INSERT INTO events(time,harness,message) VALUES (?,?,?)",
                (time.time(), harness, message[:2000]),
            )
            self.db.execute("DELETE FROM events WHERE seq < (SELECT MAX(seq)-5000 FROM events)")
            self.db.commit()

        if self.emit:
            self.emit(message, harness)

    def events(self, after: int = 0) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.db.execute(
                "SELECT seq,time,harness,message FROM events "
                "WHERE seq>? ORDER BY seq DESC LIMIT 150",
                (after,),
            ).fetchall()
        return [
            dict(zip(("seq", "time", "harness", "message"), row, strict=True))
            for row in reversed(rows)
        ]

    def reserve(self, count: int, ceiling: int) -> str:
        day = time.strftime("%Y-%m-%d", time.gmtime())
        with self.lock:
            used = self.db.execute("SELECT tokens FROM usage WHERE day=?", (day,)).fetchone()
            used = used[0] if used else 0
            if used + count > ceiling:
                raise ValueError(
                    "Daily token guard reached. Increase it or wait for the next UTC day."
                )
            self.db.execute("INSERT OR REPLACE INTO usage VALUES (?,?)", (day, used + count))
            self.db.commit()
        return day

    def settle(self, day: str, reserved: int, actual: int) -> None:
        with self.lock:
            self.db.execute(
                "UPDATE usage SET tokens=MAX(0,tokens+?) WHERE day=?", (actual - reserved, day)
            )
            self.db.commit()

    def used(self) -> int:
        with self.lock:
            row = self.db.execute(
                "SELECT tokens FROM usage WHERE day=?", (time.strftime("%Y-%m-%d", time.gmtime()),)
            ).fetchone()
        return int(row[0]) if row else 0


def new_id(prefix: str) -> str:
    return prefix + "_" + uuid.uuid4().hex[:12]
