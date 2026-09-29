"""Diff hardware inventories and publish hotplug events."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from omne.hardware.model import HardwareDevice, HardwareEvent, HardwareInventory
from omne.hardware.provider import HardwareProvider

EventSink = Callable[[str, dict[str, Any]], None]


class HardwareService:
    """Remember the last inventory so a later read can report hotplug."""

    def __init__(self, provider: HardwareProvider, sink: EventSink | None = None) -> None:
        self._provider = provider
        self._sink = sink
        self._previous: dict[str, HardwareDevice] | None = None

    def inventory(self) -> HardwareInventory:
        current = self._provider.inventory()
        if not current.observed:
            return current
        indexed = {device.id: device for device in current.devices}
        previous = self._previous
        self._previous = indexed
        if previous is None:
            return current
        for event in _diff(previous, indexed):
            if self._sink is not None:
                self._sink(event.type, dict(event.payload))
        return current


def _diff(
    previous: dict[str, HardwareDevice],
    current: dict[str, HardwareDevice],
) -> list[HardwareEvent]:
    events: list[HardwareEvent] = []
    for device_id in sorted(set(current) - set(previous)):
        device = current[device_id]
        events.append(
            HardwareEvent(
                type="hardware.added",
                payload={"id": device.id, "type": device.type},
            )
        )
    for device_id in sorted(set(previous) - set(current)):
        device = previous[device_id]
        events.append(
            HardwareEvent(
                type="hardware.removed",
                payload={"id": device.id, "type": device.type},
            )
        )
    for device_id in sorted(set(previous) & set(current)):
        fields = _changed_fields(previous[device_id], current[device_id])
        if not fields:
            continue
        events.append(
            HardwareEvent(
                type="hardware.changed",
                payload={"id": device_id, "type": current[device_id].type, "fields": fields},
            )
        )
    return events


def _changed_fields(before: HardwareDevice, after: HardwareDevice) -> list[str]:
    left = before.model_dump(mode="json")
    right = after.model_dump(mode="json")
    return sorted(key for key in left if left[key] != right.get(key))
