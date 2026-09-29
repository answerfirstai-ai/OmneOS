"""Append-only permission audit log."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditEntry(BaseModel):
    """One permission decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timestamp: datetime
    decision: str
    policy_id: str
    reason: str
    tool_id: str
    task_id: str | None
    agent_id: str | None
    user: str
    arguments: dict[str, Any]


class AuditLog:
    """Record permission decisions in memory and, when configured, on disk."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._entries: list[AuditEntry] = []
        self._lock = threading.Lock()

    def record(self, entry: AuditEntry) -> None:
        line = json.dumps(entry.model_dump(mode="json"), sort_keys=True)
        with self._lock:
            self._entries.append(entry)
            path = self._path
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def entries(self) -> list[AuditEntry]:
        with self._lock:
            return list(self._entries)


def audit_now() -> datetime:
    return datetime.now(UTC)
