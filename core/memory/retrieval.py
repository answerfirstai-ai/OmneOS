"""Deterministic memory retrieval."""

from __future__ import annotations

SCOPES = frozenset({"conversation", "task", "project", "long_term", "system"})


class MemoryAccessError(Exception):
    """Raised when a caller touches a scope it was not granted."""


class AccessGrant:
    """Scopes a caller may read and write."""

    def __init__(self, scopes: set[str]) -> None:
        unknown = scopes - SCOPES
        if unknown:
            raise MemoryAccessError(f"unknown memory scopes: {', '.join(sorted(unknown))}")
        self.scopes = frozenset(scopes)

    def require(self, scope: str) -> None:
        if scope not in SCOPES:
            raise MemoryAccessError(f"unknown memory scope: {scope}")
        if scope not in self.scopes:
            raise MemoryAccessError(f"access to memory scope {scope} is denied")


def like_pattern(query: str) -> str:
    """Build a LIKE pattern that treats user characters as literals."""

    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
