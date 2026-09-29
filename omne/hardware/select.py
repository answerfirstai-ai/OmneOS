"""Choose a hardware provider without exposing sysfs paths to Core."""

from __future__ import annotations

import sys
from pathlib import Path

from omne.hardware.provider import HardwareProvider
from omne.hardware.providers.linux import LinuxHardwareProvider
from omne.hardware.providers.mock import MockHardwareProvider
from omne.hardware.service import EventSink, HardwareService


def select_provider(environment: str, *, root: Path | None = None) -> HardwareProvider:
    """Use the mock provider in tests and on non-Linux hosts.

    Development and production on Linux read sysfs and proc. That read does not
    configure devices or load drivers.
    """

    if environment == "testing" or not sys.platform.startswith("linux"):
        return MockHardwareProvider()
    return LinuxHardwareProvider(root=root)


def hardware_service(
    environment: str,
    *,
    sink: EventSink | None = None,
    root: Path | None = None,
) -> HardwareService:
    """Return a service bound to the selected provider."""

    return HardwareService(select_provider(environment, root=root), sink=sink)
