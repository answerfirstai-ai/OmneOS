"""Choose a storage provider without formatting a disk."""

from __future__ import annotations

import sys
from pathlib import Path

from omne.storage.provider import StorageProvider
from omne.storage.providers.linux import LinuxStorageProvider
from omne.storage.providers.mock import MockStorageProvider
from omne.storage.service import EventSink, StorageService


def select_provider(environment: str, *, root: Path | None = None) -> StorageProvider:
    """Use the mock provider in tests and on non-Linux hosts.

    Development and production on Linux read sysfs and the mount table. That
    read does not open a raw device.
    """

    if environment == "testing" or not sys.platform.startswith("linux"):
        return MockStorageProvider()
    return LinuxStorageProvider(root=root)


def storage_service(
    environment: str,
    *,
    sink: EventSink | None = None,
    root: Path | None = None,
) -> StorageService:
    """Return a service bound to the selected provider."""

    return StorageService(select_provider(environment, root=root), sink=sink)
