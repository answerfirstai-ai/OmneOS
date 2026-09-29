"""In-memory hardware provider for tests and non-Linux hosts.

The mock starts with no devices. It does not invent a CPU, GPU, or battery.
"""

from __future__ import annotations

from omne.hardware.model import HardwareDevice, HardwareInventory


class MockHardwareProvider:
    """A hardware record tests can change without reading the host."""

    def __init__(self, devices: list[HardwareDevice] | None = None) -> None:
        self._devices = list(devices or [])

    def inventory(self) -> HardwareInventory:
        devices = sorted(self._devices, key=lambda device: (device.type, device.id))
        return HardwareInventory(provider="mock", observed=True, devices=devices, gaps=[])

    def set_devices(self, devices: list[HardwareDevice]) -> None:
        self._devices = list(devices)
