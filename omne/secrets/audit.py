"""Append-only record of secret access.

An entry names the action, scope, name, agent, and decision. It has no field
for the credential.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class SecretAuditEntry(BaseModel):
    """One secret decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timestamp: datetime
    action: str
    scope: str
    name: str
    agent_id: str
    decision: str
    reason: str


class SecretAuditLog:
    """Record secret decisions in memory and, when configured, on disk."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._entries: list[SecretAuditEntry] = []
        self._lock = threading.Lock()

    def record(self, entry: SecretAuditEntry) -> None:
        line = json.dumps(entry.model_dump(mode="json"), sort_keys=True)
        with self._lock:
            self._entries.append(entry)
            path = self._path
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def entries(self) -> list[SecretAuditEntry]:
        with self._lock:
            return list(self._entries)


def audit_now() -> datetime:
    return datetime.now(UTC)
