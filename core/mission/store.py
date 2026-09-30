"""SQLite persistence for missions."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from core.mission.model import Mission, MissionStatus, transition_mission
from core.sqlite import configure_sqlite, ensure_schema
from omne.secrets.redact import redact_object


class MissionStore:
    """Save missions without dropping an existing database."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        configure_sqlite(self._connection)
        ensure_schema(
            self._connection,
            "missions",
            1,
            """
            CREATE TABLE IF NOT EXISTS missions (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                document TEXT NOT NULL
            )
            """,
        )
        self._connection.execute("CREATE INDEX IF NOT EXISTS missions_status ON missions (status)")
        self._connection.commit()
        self._cache: dict[str, Mission] = {}

    def save(self, mission: Mission) -> Mission:
        mission = Mission.model_validate(redact_object(mission.model_dump(mode="json")))
        document = json.dumps(mission.model_dump(mode="json"), sort_keys=True)
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO missions (id, status, document)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status = excluded.status,
                    document = excluded.document
                """,
                (mission.id, mission.status.value, document),
            )
            self._connection.commit()
            self._cache[mission.id] = mission
        return mission

    def get(self, mission_id: str) -> Mission:
        with self._lock:
            cached = self._cache.get(mission_id)
            if cached is not None:
                return cached
            row = self._connection.execute(
                "SELECT document FROM missions WHERE id = ?",
                (mission_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown mission: {mission_id}")
            mission = Mission.model_validate_json(row["document"])
            self._cache[mission_id] = mission
            return mission

    def list_missions(self) -> list[Mission]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT id, document FROM missions ORDER BY id"
            ).fetchall()
            missions: list[Mission] = []
            for row in rows:
                cached = self._cache.get(str(row["id"]))
                if cached is None:
                    cached = Mission.model_validate_json(row["document"])
                    self._cache[str(row["id"])] = cached
                missions.append(cached)
            return missions

    def transition(self, mission: Mission, status: MissionStatus, **updates: object) -> Mission:
        updated = transition_mission(mission, status, now=datetime.now(UTC), **updates)
        return self.save(updated)
