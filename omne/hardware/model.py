"""Hardware records discovered from Linux.

Missing fields stay null. This model does not describe a configuration change.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ProviderName = Literal["mock", "linux"]
DeviceType = Literal[
    "cpu",
    "memory",
    "gpu",
    "monitor",
    "keyboard",
    "mouse",
    "input",
    "usb",
    "pci",
    "storage",
    "ethernet",
    "wifi",
    "bluetooth",
    "audio",
    "camera",
    "battery",
    "power",
]
HardwareEventType = Literal["hardware.added", "hardware.removed", "hardware.changed"]


class ResourceUsage(BaseModel):
    """Measurements a Linux source actually published."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    total_bytes: int | None = None
    used_bytes: int | None = None
    available_bytes: int | None = None
    usage_percent: float | None = None
    frequency_hz: int | None = None
    vram_total_bytes: int | None = None
    vram_used_bytes: int | None = None


class PowerInfo(BaseModel):
    """Power-supply values with the kernel's units left intact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: str | None = None
    online: bool | None = None
    capacity_percent: float | None = None
    energy_now_uwh: int | None = None
    energy_full_uwh: int | None = None
    voltage_uv: int | None = None
    power_uw: int | None = None
    current_ua: int | None = None

    def known(self) -> bool:
        return any(value is not None for value in self.model_dump().values())


class HardwareDevice(BaseModel):
    """One device Linux exposed through sysfs or proc."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    type: DeviceType
    vendor: str | None = None
    model: str | None = None
    driver: str | None = None
    state: str = Field(min_length=1)
    capabilities: list[str] = Field(default_factory=list)
    usage: ResourceUsage = Field(default_factory=ResourceUsage)
    temperature_c: float | None = None
    power: PowerInfo | None = None


class HardwareInventory(BaseModel):
    """One read of hardware. An unread category is a gap, not an empty claim."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: ProviderName
    observed: bool
    drivers_modified: bool = False
    devices: list[HardwareDevice] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)

    @field_validator("drivers_modified")
    @classmethod
    def _read_only(cls, value: bool) -> bool:
        if value:
            raise ValueError("drivers_modified must be false")
        return value


class HardwareEvent(BaseModel):
    """One hotplug difference between two inventories."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: HardwareEventType
    payload: dict[str, Any] = Field(default_factory=dict)
