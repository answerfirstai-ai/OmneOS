"""A store that refuses every operation.

Used when Linux secret storage is unavailable and the development fallback
was not explicitly enabled.
"""

from __future__ import annotations

from omne.secrets.model import SecretScope, SecretUnavailable


class ClosedSecretProvider:
    """Fail closed. No credential is stored or returned."""

    @property
    def available(self) -> bool:
        return False

    def put(
        self,
        scope: SecretScope,
        name: str,
        value: str,
        agents: tuple[str, ...],
    ) -> None:
        del scope, name, value, agents
        raise SecretUnavailable()

    def get(self, scope: SecretScope, name: str) -> tuple[str, tuple[str, ...]] | None:
        del scope, name
        raise SecretUnavailable()

    def remove(self, scope: SecretScope, name: str) -> bool:
        del scope, name
        raise SecretUnavailable()

    def contains(self, scope: SecretScope, name: str) -> bool:
        del scope, name
        raise SecretUnavailable()
