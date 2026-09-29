"""Choose a window provider without exposing compositor types to Core."""

from __future__ import annotations

import sys
from pathlib import Path

from omne.windowing.provider import WindowProvider
from omne.windowing.providers.linux import LinuxWindowProvider
from omne.windowing.providers.mock import MockWindowProvider
from omne.windowing.service import EventSink, WindowingService


def select_provider(environment: str, *, root: Path | None = None) -> WindowProvider:
    """Use the mock provider in tests and on non-Linux hosts.

    Development and production on Linux use the labwc snapshot provider.
    That provider does not start a session and does not command labwc.
    """

    if environment == "testing" or not sys.platform.startswith("linux"):
        return MockWindowProvider()
    return LinuxWindowProvider(root=root)


def windowing_service(
    environment: str,
    *,
    sink: EventSink | None = None,
    root: Path | None = None,
) -> WindowingService:
    """Return a service bound to the selected provider."""

    return WindowingService(select_provider(environment, root=root), sink=sink)
