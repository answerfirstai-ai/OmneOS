"""In-memory disks and mounts for tests and non-Linux hosts.

The mock starts empty. It has no format or raw-write operation.
"""

from __future__ import annotations

from omne.storage.model import StorageState


class MockStorageProvider:
    """A storage snapshot whose changes stay inside the record."""

    def __init__(self) -> None:
        self._state = StorageState(provider="mock", observed=True, gaps=[])

    def inspect(self) -> StorageState:
        return self._state

    def set_state(self, state: StorageState) -> None:
        self._state = state
