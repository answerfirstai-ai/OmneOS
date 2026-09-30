"""Choose a network provider without exposing the host stack to Core."""

from __future__ import annotations

import sys
from pathlib import Path

from omne.network.provider import NetworkProvider
from omne.network.providers.linux import LinuxNetworkProvider
from omne.network.providers.mock import MockNetworkProvider
from omne.network.service import Authorize, EventSink, NetworkService


def select_provider(environment: str, *, root: Path | None = None) -> NetworkProvider:
    """Use the mock provider in tests and on non-Linux hosts.

    Development and production on Linux read sysfs and proc. That read does not
    change interfaces, routes, or Wi-Fi.
    """

    if environment == "testing" or not sys.platform.startswith("linux"):
        return MockNetworkProvider()
    return LinuxNetworkProvider(root=root)


def network_service(
    environment: str,
    *,
    sink: EventSink | None = None,
    authorize: Authorize | None = None,
    root: Path | None = None,
) -> NetworkService:
    """Return a service bound to the selected provider."""

    return NetworkService(select_provider(environment, root=root), sink=sink, authorize=authorize)
