"""Browser provider interface.

Core calls this protocol. A provider does not import Playwright and does not
start a shell.
"""

from __future__ import annotations

from typing import Protocol

from omne.browser.model import BrowserOutcome, BrowserRequest, BrowserState


class BrowserProvider(Protocol):
    """Report browser availability and record a session action."""

    def status(self) -> BrowserState:
        """Return layer availability. Do not launch a browser."""

    def apply(self, request: BrowserRequest) -> BrowserOutcome:
        """Record one browser action. Do not invoke a shell."""
