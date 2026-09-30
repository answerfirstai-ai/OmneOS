"""In-memory event bus with optional JSONL persistence."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from core.trace import current_mission_id, current_trace_id
from omne.secrets.redact import redact_object

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
    trace_id: str | None = None
    mission_id: str | None = None
    worker_id: str | None = None
    source: str = "OMNE"
    schema_version: int = 1
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
        self._handle: TextIO | None = None
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
        trace_id: str | None = None,
        mission_id: str | None = None,
        worker_id: str | None = None,
        source: str = "OMNE",
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
            trace_id=current_trace_id() if trace_id is None else trace_id,
            mission_id=current_mission_id() if mission_id is None else mission_id,
            worker_id=worker_id,
            source=source,
            payload=redact_object(dict(payload or {})),
        )
        with self._lock:
            self._events.append(event)
            if len(self._events) > self._limit:
                self._events = self._events[-self._limit :]
            subscribers = list(self._subscribers)
            self._write_locked(event)
        for subscriber in subscribers:
            subscriber(event)
        return event

    def list_events(self, *, after: str | None = None, limit: int | None = None) -> list[Event]:
        with self._lock:
            events = list(self._events)
        if after is not None:
            for index, event in enumerate(events):
                if event.id == after:
                    events = events[index + 1 :]
                    break
        if limit is None:
            return events
        if limit <= 0:
            return []
        return events[-limit:]

    def _write_locked(self, event: Event) -> None:
        path = self._persist_path
        if path is None:
            return
        handle = self._handle
        if handle is None:
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = path.open("a", encoding="utf-8")
            self._handle = handle
        line = json.dumps(event.model_dump(mode="json"), sort_keys=True)
        handle.write(line + "\n")
        handle.flush()
