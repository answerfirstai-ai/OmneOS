"""In-memory event bus with optional JSONL persistence."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

Subscriber = Callable[["Event"], None]


class Event(BaseModel):
    """One machine-readable event."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    type: str
    timestamp: datetime
    task_id: str | None = None
    agent_id: str | None = None
    model_id: str | None = None
    tool_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class EventBus:
    """Publish and retain structured events."""

    def __init__(
        self,
        *,
        persist_path: Path | None = None,
        now: Callable[[], datetime] | None = None,
        limit: int = 1000,
    ) -> None:
        self._events: list[Event] = []
        self._subscribers: list[Subscriber] = []
        self._lock = threading.Lock()
        self._persist_path = persist_path
        self._now = now or (lambda: datetime.now(UTC))
        self._limit = limit

    def subscribe(self, subscriber: Subscriber) -> None:
        with self._lock:
            self._subscribers.append(subscriber)

    def publish(
        self,
        event_type: str,
        *,
        task_id: str | None = None,
        agent_id: str | None = None,
        model_id: str | None = None,
        tool_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Event:
        event = Event(
            id=str(uuid4()),
            type=event_type,
            timestamp=self._now(),
            task_id=task_id,
            agent_id=agent_id,
            model_id=model_id,
            tool_id=tool_id,
            payload=dict(payload or {}),
        )
        with self._lock:
            self._events.append(event)
            if len(self._events) > self._limit:
                self._events = self._events[-self._limit :]
            subscribers = list(self._subscribers)
            persist_path = self._persist_path
        if persist_path is not None:
            _append_jsonl(persist_path, event)
        for subscriber in subscribers:
            subscriber(event)
        return event

    def list_events(self, *, after: str | None = None) -> list[Event]:
        with self._lock:
            events = list(self._events)
        if after is None:
            return events
        for index, event in enumerate(events):
            if event.id == after:
                return events[index + 1 :]
        return events


def _append_jsonl(path: Path, event: Event) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event.model_dump(mode="json"), sort_keys=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
