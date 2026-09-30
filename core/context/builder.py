"""Assemble a bounded prompt context."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from omne.secrets.redact import redact_text


class ContextItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str
    scope: str
    relevance: int
    timestamp: datetime | None = None
    priority: int
    text: str


class BuiltContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: list[ContextItem] = Field(default_factory=list)
    revision: int = 0

    def render(self, *, char_limit: int) -> str:
        lines: list[str] = []
        used = 0
        for item in self.items:
            line = f"[{item.source}:{item.scope}] {item.text}"
            if used + len(line) > char_limit:
                break
            lines.append(line)
            used += len(line) + 1
        return "\n".join(lines)


def build_context(
    *,
    request: str,
    memories: list[dict[str, Any]],
    project_name: str,
    world_revision: int,
    item_limit: int,
    char_limit: int,
) -> BuiltContext:
    """Rank a few relevant notes. The full memory database is never included."""

    del char_limit
    request = redact_text(request)
    ranked: list[ContextItem] = []
    terms = {word.lower() for word in request.split() if len(word) > 2}
    for memory in memories:
        content = redact_text(str(memory.get("content", "")))
        overlap = sum(1 for term in terms if term in content.lower())
        if terms and overlap == 0:
            continue
        created = memory.get("created_at")
        timestamp = created if isinstance(created, datetime) else None
        ranked.append(
            ContextItem(
                source=str(memory.get("source", "memory")),
                scope=str(memory.get("scope", "task")),
                relevance=overlap + int(memory.get("priority", 0)),
                timestamp=timestamp,
                priority=int(memory.get("priority", 0)),
                text=content[:400],
            )
        )
    ranked.sort(key=lambda item: (item.relevance, item.priority), reverse=True)
    items = ranked[:item_limit]
    if project_name:
        items = [
            ContextItem(
                source="project",
                scope="project",
                relevance=1,
                priority=1,
                text=project_name,
            ),
            *items,
        ][:item_limit]
    return BuiltContext(items=items, revision=world_revision)
