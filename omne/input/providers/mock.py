"""In-memory input devices for tests and non-Linux hosts.

The mock starts with no devices. It does not record keystrokes.
"""

from __future__ import annotations

from omne.input.model import DeviceReport, InputDevice, InputRequest


class MockInputProvider:
    """A device list whose changes stay inside the record."""

    def __init__(self) -> None:
        self._devices: list[InputDevice] = []

    def inspect(self) -> DeviceReport:
        return DeviceReport(
            provider="mock",
            observed=True,
            compositor="unknown",
            portal="unknown",
            devices=sorted(self._devices, key=lambda item: item.id),
            devices_known=True,
        )

    def set_devices(self, devices: list[InputDevice]) -> None:
        self._devices = list(devices)

    def apply(self, request: InputRequest) -> None:
        if request.action == "bind":
            return None
        return None
