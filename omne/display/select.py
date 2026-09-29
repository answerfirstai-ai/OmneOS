"""Choose a display provider without exposing compositor types to Core."""

from __future__ import annotations

import sys
from pathlib import Path

from omne.display.model import Display
from omne.display.provider import DisplayProvider
from omne.display.providers.linux import LinuxDisplayProvider
from omne.display.providers.mock import MockDisplayProvider


def select_provider(environment: str, *, root: Path | None = None) -> DisplayProvider:
    """Use the mock provider in tests and on non-Linux hosts.

    Development and production on Linux use the labwc diagnostics provider.
    That provider still does not start a session.
    """

    if environment == "testing" or not sys.platform.startswith("linux"):
        return MockDisplayProvider()
    return LinuxDisplayProvider(root=root)


def diagnose_display(environment: str, *, root: Path | None = None) -> Display:
    """Return the selected provider's display report."""

    return select_provider(environment, root=root).diagnose()
