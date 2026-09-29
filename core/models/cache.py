"""Small response cache for provider calls.

This stores prior normalized responses. It is not a weight cache.
"""

from __future__ import annotations

from core.models.types import GenerateRequest, GenerateResponse


class ResponseCache:
    """Remember the last response for an identical request."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str, str], GenerateResponse] = {}

    def get(self, provider: str, request: GenerateRequest) -> GenerateResponse | None:
        return self._items.get(_key(provider, request))

    def put(self, provider: str, request: GenerateRequest, response: GenerateResponse) -> None:
        self._items[_key(provider, request)] = response


def _key(provider: str, request: GenerateRequest) -> tuple[str, str, str]:
    return provider, request.model, request.prompt
