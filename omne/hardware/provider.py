"""Hardware provider interface.

Core calls this protocol. A provider only reads device state.
"""

from __future__ import annotations

from typing import Protocol

from omne.hardware.model import HardwareInventory


class HardwareProvider(Protocol):
    """Discover hardware without configuring it."""

    def inventory(self) -> HardwareInventory:
        """Return the current hardware record."""
