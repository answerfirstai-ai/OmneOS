"""Window provider interface.

Core calls this protocol. A provider owns its compositor types.
"""

from __future__ import annotations

from typing import Protocol

from omne.windowing.model import ApplyOutcome, WindowingState, WindowRequest


class WindowProvider(Protocol):
    """Report windows and apply a request to the recorded session."""

    def state(self) -> WindowingState:
        """Return the current window record without commanding a compositor."""

    def apply(self, request: WindowRequest) -> ApplyOutcome:
        """Update the record. Do not send the change to a live compositor."""
