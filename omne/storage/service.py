"""Publish storage changes. The first read is a baseline.

Events name a disk, a partition, or a mount. They do not contain file contents.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from omne.storage.model import StorageEvent, StorageEventType, StorageState
from omne.storage.provider import StorageProvider

EventSink = Callable[[str, dict[str, Any]], None]


class StorageService:
    """Inspect storage and emit events when the published layout changes."""

    def __init__(self, provider: StorageProvider, sink: EventSink | None = None) -> None:
        self._provider = provider
        self._sink = sink
        self._previous: StorageState | None = None

    def inspect(self) -> StorageState:
        current = self._provider.inspect()
        previous = self._previous
        self._previous = current
        if previous is None or not current.observed or self._sink is None:
            return current
        for event in _diff(previous, current):
            self._sink(event.type, dict(event.payload))
        return current


def _diff(before: StorageState, after: StorageState) -> list[StorageEvent]:
    events: list[StorageEvent] = []
    events.extend(
        _identity_diff(
            {item.id: item.name for item in before.disks},
            {item.id: item.name for item in after.disks},
            "storage.disk.added",
            "storage.disk.removed",
            "disk",
        )
    )
    events.extend(
        _identity_diff(
            {item.id: item.name for item in before.partitions},
            {item.id: item.name for item in after.partitions},
            "storage.partition.added",
            "storage.partition.removed",
            "partition",
        )
    )
    events.extend(
        _identity_diff(
            {item.id: item.mount for item in before.filesystems},
            {item.id: item.mount for item in after.filesystems},
            "storage.mount.added",
            "storage.mount.removed",
            "mount",
        )
    )
    previous = {item.id: item for item in before.filesystems}
    for item in after.filesystems:
        prior = previous.get(item.id)
        if prior is None:
            continue
        if prior.used_bytes == item.used_bytes and prior.free_bytes == item.free_bytes:
            continue
        events.append(
            StorageEvent(
                type="storage.space.changed",
                payload={
                    "mount": item.mount,
                    "used_bytes": item.used_bytes,
                    "free_bytes": item.free_bytes,
                },
            )
        )
    return events


def _identity_diff(
    before: dict[str, str],
    after: dict[str, str],
    added: StorageEventType,
    removed: StorageEventType,
    field: str,
) -> list[StorageEvent]:
    events: list[StorageEvent] = []
    for item_id in sorted(set(after) - set(before)):
        events.append(StorageEvent(type=added, payload={"id": item_id, field: after[item_id]}))
    for item_id in sorted(set(before) - set(after)):
        events.append(StorageEvent(type=removed, payload={"id": item_id, field: before[item_id]}))
    return events
