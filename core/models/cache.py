"""Context-aware cache for model text.

Tool results, permission decisions, and live telemetry are not stored here.
"""

from __future__ import annotations

import time

from pydantic import BaseModel, ConfigDict

from core.models.types import GenerateRequest, GenerateResponse


class CacheContext(BaseModel):
    """Parts of the world that change the meaning of a prompt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_version: str = ""
    system: str = ""
    tools: str = ""
    world_revision: int = 0
    context_revision: int = 0
    settings: str = ""


class ResponseCache:
    """Remember a response only for an identical context."""

    def __init__(self, *, ttl_seconds: float = 0) -> None:
        self._items: dict[tuple[object, ...], GenerateResponse] = {}
        self._stored_at: dict[tuple[object, ...], float] = {}
        self._ttl = ttl_seconds
        self.events: list[dict[str, object]] = []

    def get(
        self,
        provider: str,
        request: GenerateRequest,
        *,
        context: CacheContext | None = None,
    ) -> GenerateResponse | None:
        key = _key(provider, request, context or CacheContext())
        found = self._items.get(key)
        if found is not None and self._ttl > 0:
            stored = self._stored_at.get(key, 0.0)
            if time.monotonic() - stored > self._ttl:
                self._items.pop(key, None)
                found = None
                self.events.append({"type": "cache.invalidation", "reason": "ttl"})
        self.events.append(
            {
                "type": "cache.hit" if found is not None else "cache.miss",
                "provider": provider,
                "model": request.model,
            }
        )
        return found

    def put(
        self,
        provider: str,
        request: GenerateRequest,
        response: GenerateResponse,
        *,
        context: CacheContext | None = None,
    ) -> None:
        key = _key(provider, request, context or CacheContext())
        self._items[key] = response
        self._stored_at[key] = time.monotonic()

    def invalidate(self) -> None:
        self._items.clear()
        self._stored_at.clear()
        self.events.append({"type": "cache.invalidation"})

    def bypass(self, *, reason: str) -> None:
        self.events.append({"type": "cache.bypass", "reason": reason})


def _key(provider: str, request: GenerateRequest, context: CacheContext) -> tuple[object, ...]:
    return (
        provider,
        request.model,
        context.model_version,
        request.system or context.system,
        request.prompt,
        context.tools,
        context.world_revision,
        context.context_revision,
        context.settings,
    )
