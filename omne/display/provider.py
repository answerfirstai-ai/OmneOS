"""Display provider interface.

Core calls this protocol. A provider owns its compositor types.
"""

from __future__ import annotations

from typing import Protocol

from omne.display.model import Display


class DisplayProvider(Protocol):
    """Report monitors, windows, and whether a graphical session can launch."""

    def diagnose(self) -> Display:
        """Return the current display state without starting a session."""
