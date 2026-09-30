"""In-memory secret store.

This provider is the test double and the explicit development fallback. It
does not write a file.
"""

from __future__ import annotations

from omne.secrets.model import SecretScope


class MemorySecretProvider:
    """Hold credentials in this process only."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], tuple[str, tuple[str, ...]]] = {}

    @property
    def available(self) -> bool:
        return True

    def put(
        self,
        scope: SecretScope,
        name: str,
        value: str,
        agents: tuple[str, ...],
    ) -> None:
        self._records[(scope.value, name)] = (value, agents)

    def get(self, scope: SecretScope, name: str) -> tuple[str, tuple[str, ...]] | None:
        return self._records.get((scope.value, name))

    def remove(self, scope: SecretScope, name: str) -> bool:
        return self._records.pop((scope.value, name), None) is not None

    def contains(self, scope: SecretScope, name: str) -> bool:
        return (scope.value, name) in self._records
