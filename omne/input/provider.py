"""Input provider interface.

Core calls this protocol. A provider does not read the keyboard stream.
"""

from __future__ import annotations

from typing import Protocol

from omne.input.model import DeviceReport, InputRequest


class InputProvider(Protocol):
    """Report keyboards and mice, and refuse a host grab."""

    def inspect(self) -> DeviceReport:
        """Return published devices. Do not open an event node."""

    def apply(self, request: InputRequest) -> None:
        """Refuse a host binding. Session actions are handled by the service."""
