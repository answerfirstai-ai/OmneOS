"""Secret storage interface.

A provider keeps the credential and its audience. It does not log either one.
"""

from __future__ import annotations

from typing import Protocol

from omne.secrets.model import SecretScope


class SecretProvider(Protocol):
    """Store one scoped credential."""

    @property
    def available(self) -> bool:
        """True when this provider can complete an operation."""

    def put(
        self,
        scope: SecretScope,
        name: str,
        value: str,
        agents: tuple[str, ...],
    ) -> None:
        """Create or replace the credential and its audience."""

    def get(self, scope: SecretScope, name: str) -> tuple[str, tuple[str, ...]] | None:
        """Return the credential and audience, or None when it is absent."""

    def remove(self, scope: SecretScope, name: str) -> bool:
        """Delete the credential. Return whether a record was removed."""

    def contains(self, scope: SecretScope, name: str) -> bool:
        """Report whether both the credential and its audience exist."""
