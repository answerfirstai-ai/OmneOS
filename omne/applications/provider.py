"""Application provider interface.

Core calls this protocol. A provider does not start a shell.
"""

from __future__ import annotations

from typing import Protocol

from omne.applications.model import ApplicationCatalog, ApplicationRequest, ApplyOutcome


class ApplicationProvider(Protocol):
    """Report installed applications and record a session action."""

    def catalog(self) -> ApplicationCatalog:
        """Return installed applications. Do not launch one."""

    def apply(self, request: ApplicationRequest) -> ApplyOutcome:
        """Record launch, focus, or close. Do not invoke a shell."""
