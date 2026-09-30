"""What one discovered machine can actually do.

The profile is derived from an inventory. It does not assume a vendor, a GPU,
or a peripheral that the inventory did not report. A category that could not
be read stays null. CUDA is true only when the NVIDIA kernel driver is bound.
This module does not call NVIDIA and does not load a driver.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from omne.hardware.model import HardwareDevice, HardwareInventory

_PCI_VENDORS = {
    "0x10de": "NVIDIA",
    "0x1002": "AMD",
    "0x8086": "Intel",
    "0x1af4": "Red Hat",
    "0x1234": "QEMU",
    "0x1b36": "Red Hat",
    "0x1414": "Microsoft",
    "0x15ad": "VMware",
}
_DRIVER_TYPES = frozenset(
    {
        "gpu",
        "pci",
        "usb",
        "storage",
        "ethernet",
        "wifi",
        "bluetooth",
        "audio",
        "camera",
        "microphone",
        "keyboard",
        "mouse",
        "input",
    }
)
_UNITS = ("B", "KB", "MB", "GB", "TB")


class CpuCapability(BaseModel):
    """One CPU package that was present in the inventory."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    vendor: str | None = None
    model: str | None = None
    cores: int | None = None
    threads: int | None = None
    driver: str | None = None


class MemoryCapability(BaseModel):
    """Installed memory. The text form is omitted when the byte count is unknown."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    total_bytes: int | None = None
    total: str | None = None


class BoardCapability(BaseModel):
    """Motherboard identity published by firmware."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    vendor: str | None = None
    model: str | None = None


class GpuCapability(BaseModel):
    """One graphics device. ``cuda`` is driver detection, not an inference call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    vendor: str | None = None
    vendor_id: str | None = None
    model: str | None = None
    driver: str | None = None
    vram_bytes: int | None = None
    vram: str | None = None
    cuda: bool = False


class DriverReport(BaseModel):
    """Kernel drivers that were bound, and devices that had none."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    known: bool
    bound: list[str] = Field(default_factory=list)
    unbound: list[str] = Field(default_factory=list)


Feature = CpuCapability | list[CpuCapability] | Literal[False] | None
GpuFeature = GpuCapability | list[GpuCapability] | Literal[False] | None
MemoryFeature = MemoryCapability | Literal[False] | None
BoardFeature = BoardCapability | Literal[False] | None
Flag = bool | None


class MachineCapabilities(BaseModel):
    """The capability registry for the machine that was just discovered."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    observed: bool
    cpu: Feature = None
    memory: MemoryFeature = None
    motherboard: BoardFeature = None
    gpu: GpuFeature = None
    storage: Flag = None
    wifi: Flag = None
    ethernet: Flag = None
    bluetooth: Flag = None
    audio: Flag = None
    microphone: Flag = None
    keyboard: Flag = None
    mouse: Flag = None
    display: Flag = None
    usb: Flag = None
    camera: Flag = None
    drivers: DriverReport


def machine_capabilities(inventory: HardwareInventory) -> MachineCapabilities:
    """Build the registry from one inventory. An unread machine stays unknown."""

    if not inventory.observed:
        return MachineCapabilities(
            observed=False,
            drivers=DriverReport(known=False),
        )
    devices = inventory.devices
    gaps = set(inventory.gaps)
    return MachineCapabilities(
        observed=True,
        cpu=_processors(devices, "cpu" in gaps),
        memory=_memory(devices, "memory" in gaps),
        motherboard=_board(devices, "motherboard" in gaps),
        gpu=_gpus(devices, "gpu" in gaps),
        storage=_flag(devices, gaps, "storage", types=("storage",)),
        wifi=_flag(devices, gaps, "network", types=("wifi",)),
        ethernet=_flag(devices, gaps, "network", types=("ethernet",)),
        bluetooth=_flag(devices, gaps, "bluetooth", types=("bluetooth",)),
        audio=_flag(devices, gaps, "audio", types=("audio",)),
        microphone=_microphone(devices, gaps),
        keyboard=_pointer(devices, gaps, "keyboard"),
        mouse=_pointer(devices, gaps, "mouse"),
        display=_flag(devices, gaps, "monitor", types=("monitor",)),
        usb=_flag(devices, gaps, "usb", types=("usb",)),
        camera=_flag(devices, gaps, "camera", types=("camera",)),
        drivers=_drivers(devices),
    )


def format_bytes(value: int | None) -> str | None:
    """Render a byte count. Unknown stays null."""

    if value is None:
        return None
    amount = float(value)
    unit = _UNITS[0]
    for name in _UNITS:
        unit = name
        if amount < 1024 or name == _UNITS[-1]:
            break
        amount /= 1024
    if unit == "B":
        return f"{int(amount)} B"
    return f"{amount:.1f} {unit}"


def _processors(devices: list[HardwareDevice], blocked: bool) -> Feature:
    if blocked:
        return None
    found = [
        CpuCapability(
            id=device.id,
            vendor=device.vendor,
            model=device.model,
            cores=_labeled(device, "cores:"),
            threads=_labeled(device, "threads:"),
            driver=device.driver,
        )
        for device in devices
        if device.type == "cpu"
    ]
    return _one_or_many(found)


def _memory(devices: list[HardwareDevice], blocked: bool) -> MemoryFeature:
    if blocked:
        return None
    found = next((device for device in devices if device.type == "memory"), None)
    if found is None:
        return False
    total = found.usage.total_bytes
    return MemoryCapability(id=found.id, total_bytes=total, total=format_bytes(total))


def _board(devices: list[HardwareDevice], blocked: bool) -> BoardFeature:
    if blocked:
        return None
    found = next((device for device in devices if device.type == "motherboard"), None)
    if found is None:
        return False
    return BoardCapability(id=found.id, vendor=found.vendor, model=found.model)


def _gpus(devices: list[HardwareDevice], blocked: bool) -> GpuFeature:
    if blocked:
        return None
    found = [_gpu(device) for device in devices if device.type == "gpu"]
    return _one_or_many(found)


def _gpu(device: HardwareDevice) -> GpuCapability:
    vendor, vendor_id = _vendor(device)
    total = device.usage.vram_total_bytes
    return GpuCapability(
        id=device.id,
        vendor=vendor,
        vendor_id=vendor_id,
        model=device.model,
        driver=device.driver,
        vram_bytes=total,
        vram=format_bytes(total),
        cuda=device.driver == "nvidia",
    )


def _vendor(device: HardwareDevice) -> tuple[str | None, str | None]:
    raw = device.vendor
    if raw is not None and raw.lower() in _PCI_VENDORS:
        return _PCI_VENDORS[raw.lower()], raw
    if device.driver == "nvidia":
        return "NVIDIA", raw
    return raw, None


def _microphone(devices: list[HardwareDevice], gaps: set[str]) -> Flag:
    if "microphone" in gaps or "audio" in gaps:
        return None
    return any(
        device.type == "microphone" or "capture" in device.capabilities for device in devices
    )


def _pointer(devices: list[HardwareDevice], gaps: set[str], name: str) -> Flag:
    if "input" in gaps:
        return None
    return any(device.type == name or name in device.capabilities for device in devices)


def _flag(
    devices: list[HardwareDevice],
    gaps: set[str],
    gap: str,
    *,
    types: tuple[str, ...],
) -> Flag:
    if gap in gaps:
        return None
    return any(device.type in types for device in devices)


def _drivers(devices: list[HardwareDevice]) -> DriverReport:
    bound = sorted({device.driver for device in devices if device.driver})
    unbound = sorted(
        device.id for device in devices if device.type in _DRIVER_TYPES and device.driver is None
    )
    return DriverReport(known=True, bound=bound, unbound=unbound)


def _labeled(device: HardwareDevice, prefix: str) -> int | None:
    for item in device.capabilities:
        if not item.startswith(prefix):
            continue
        try:
            return int(item.removeprefix(prefix))
        except ValueError:
            return None
    return None


def _one_or_many[T](found: list[T]) -> T | list[T] | Literal[False]:
    if not found:
        return False
    if len(found) == 1:
        return found[0]
    return found
