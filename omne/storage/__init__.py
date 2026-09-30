"""Disk and filesystem inspection. Formatting and raw device writes are absent.

Providers report disks, partitions, mounts, and free space. Path classification
keeps filesystem tools inside OMNE space and away from system, boot, and device
paths.
"""

from omne.storage.classify import PathClass, PathVerdict, classify_path
from omne.storage.model import Disk, FilesystemMount, Partition, StorageState
from omne.storage.select import select_provider, storage_service
from omne.storage.service import StorageService

__all__ = [
    "Disk",
    "FilesystemMount",
    "Partition",
    "PathClass",
    "PathVerdict",
    "StorageService",
    "StorageState",
    "classify_path",
    "select_provider",
    "storage_service",
]
