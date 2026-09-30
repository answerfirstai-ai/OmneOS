"""Choose a browser provider without starting a browser."""

from __future__ import annotations

import sys
from pathlib import Path

from omne.browser.provider import BrowserProvider
from omne.browser.providers.linux import LinuxBrowserProvider
from omne.browser.providers.mock import MockBrowserProvider
from omne.browser.service import Authorize, BrowserService, EventSink


def select_provider(environment: str, *, root: Path | None = None) -> BrowserProvider:
    """Use the mock session in tests and on non-Linux hosts.

    Development and production on Linux read desktop entries. That read does
    not launch a browser and does not import Playwright.
    """

    if environment == "testing" or not sys.platform.startswith("linux"):
        return MockBrowserProvider()
    return LinuxBrowserProvider(root=root)


def browser_service(
    environment: str,
    *,
    sink: EventSink | None = None,
    authorize: Authorize | None = None,
    root: Path | None = None,
) -> BrowserService:
    """Return a service bound to the selected provider."""

    return BrowserService(
        select_provider(environment, root=root),
        sink=sink,
        authorize=authorize,
    )
