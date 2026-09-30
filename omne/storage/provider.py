"""Storage provider interface.

Core calls this protocol. A provider does not format, partition, or open a raw device.
"""

from __future__ import annotations

from typing import Protocol

from omne.storage.model import StorageState


class StorageProvider(Protocol):
    """Report disks, partitions, and mounts."""

    def inspect(self) -> StorageState:
        """Return the published storage layout. Do not modify it."""
