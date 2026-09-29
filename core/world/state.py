"""A versioned snapshot of what OMNE currently knows."""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WorldState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    revision: int
    machine: dict[str, Any] = Field(default_factory=dict)
    resources: dict[str, Any] = Field(default_factory=dict)
    agents: list[dict[str, Any]] = Field(default_factory=list)
    workers: list[dict[str, Any]] = Field(default_factory=list)
    models: list[dict[str, Any]] = Field(default_factory=list)
    missions: list[dict[str, Any]] = Field(default_factory=list)
    tasks: list[dict[str, Any]] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    project: dict[str, Any] = Field(default_factory=dict)
    recent_events: list[dict[str, Any]] = Field(default_factory=list)
    active_errors: list[str] = Field(default_factory=list)
    configuration: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)


class WorldStateService:
    """Rebuild world state on demand and reuse it until the TTL expires."""

    def __init__(self, *, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._revision = 0
        self._cached: WorldState | None = None
        self._cached_at = 0.0
        self._builder: Any = None

    def bind(self, builder: Any) -> None:
        self._builder = builder

    def invalidate(self) -> None:
        self._cached = None

    def current(self) -> WorldState:
        now = time.monotonic()
        if self._cached is not None and now - self._cached_at < self._ttl:
            return self._cached
        if self._builder is None:
            self._revision += 1
            state = WorldState(revision=self._revision)
        else:
            self._revision += 1
            payload = self._builder(self._revision)
            state = (
                payload if isinstance(payload, WorldState) else WorldState.model_validate(payload)
            )
        self._cached = state
        self._cached_at = now
        return state
