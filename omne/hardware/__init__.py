"""Hardware discovery. Linux keeps the drivers.

Providers read CPU, memory, buses, and peripherals. The capability registry
says what that read can actually do. Neither one configures a device.
"""

from omne.hardware.capabilities import MachineCapabilities, machine_capabilities
from omne.hardware.model import HardwareDevice, HardwareInventory, PowerInfo, ResourceUsage
from omne.hardware.select import hardware_service, select_provider
from omne.hardware.service import HardwareService

__all__ = [
    "HardwareDevice",
    "HardwareInventory",
    "HardwareService",
    "MachineCapabilities",
    "PowerInfo",
    "ResourceUsage",
    "hardware_service",
    "machine_capabilities",
    "select_provider",
]
