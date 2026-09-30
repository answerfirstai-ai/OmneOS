"""Scoped memory records."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from core.memory.database import MemoryDatabase
from core.memory.retrieval import AccessGrant, like_pattern
from omne.secrets.redact import redact_object, redact_text


class MemoryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    scope: str
    scope_key: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    trace_id: str = ""
    source: str = ""


class MemoryStore:
    """Persist and retrieve memory without mixing scopes."""

    def __init__(self, database: MemoryDatabase) -> None:
        self._database = database

    def add(
        self,
        grant: AccessGrant,
        *,
        scope: str,
        scope_key: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        trace_id: str = "",
        source: str = "",
    ) -> MemoryRecord:
        grant.require(scope)
        if not scope_key:
            raise ValueError("scope_key is required")
        record = MemoryRecord(
            id=str(uuid4()),
            scope=scope,
            scope_key=scope_key,
            content=redact_text(content),
            metadata=redact_object(dict(metadata or {})),
            created_at=datetime.now(UTC),
            trace_id=trace_id,
            source=source,
        )
        with self._database.lock():
            self._database.connection.execute(
                """
                INSERT INTO records (
                    id, scope, scope_key, content, metadata_json, created_at, trace_id, source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.scope,
                    record.scope_key,
                    record.content,
                    json.dumps(record.metadata, sort_keys=True),
                    record.created_at.isoformat(),
                    record.trace_id,
                    record.source,
                ),
            )
            self._database.connection.commit()
        return record

    def retrieve(
        self,
        grant: AccessGrant,
        *,
        scope: str,
        scope_key: str,
        query: str = "",
        limit: int = 20,
    ) -> list[MemoryRecord]:
        grant.require(scope)
        if limit < 1:
            raise ValueError("limit must be at least 1")
        pattern = like_pattern(query) if query else ""
        with self._database.lock():
            rows = self._database.connection.execute(
                """
                SELECT id, scope, scope_key, content, metadata_json, created_at, trace_id, source
                FROM records
                WHERE scope = ? AND scope_key = ?
                  AND (? = '' OR content LIKE ? ESCAPE '\\')
                ORDER BY created_at ASC, id ASC
                LIMIT ?
                """,
                (scope, scope_key, query, pattern, limit),
            ).fetchall()
        return [
            MemoryRecord(
                id=row["id"],
                scope=row["scope"],
                scope_key=row["scope_key"],
                content=row["content"],
                metadata=json.loads(row["metadata_json"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                trace_id=str(row["trace_id"] or ""),
                source=str(row["source"] or ""),
            )
            for row in rows
        ]
