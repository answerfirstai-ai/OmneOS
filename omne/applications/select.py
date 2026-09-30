"""Choose an application provider without starting a program."""

from __future__ import annotations

import sys
from pathlib import Path

from omne.applications.provider import ApplicationProvider
from omne.applications.providers.linux import LinuxApplicationProvider
from omne.applications.providers.mock import MockApplicationProvider
from omne.applications.service import ApplicationService, Authorize, EventSink


def select_provider(environment: str, *, root: Path | None = None) -> ApplicationProvider:
    """Use the mock catalog in tests and on non-Linux hosts.

    Development and production on Linux read desktop files. That read does not
    launch an application.
    """

    if environment == "testing" or not sys.platform.startswith("linux"):
        return MockApplicationProvider()
    return LinuxApplicationProvider(root=root)


def application_service(
    environment: str,
    *,
    sink: EventSink | None = None,
    authorize: Authorize | None = None,
    root: Path | None = None,
) -> ApplicationService:
    """Return a service bound to the selected provider."""

    return ApplicationService(
        select_provider(environment, root=root),
        sink=sink,
        authorize=authorize,
    )
