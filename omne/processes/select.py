"""Choose a process provider without signaling a process."""

from __future__ import annotations

import sys
from pathlib import Path

from omne.processes.provider import ProcessProvider
from omne.processes.providers.linux import LinuxProcessProvider
from omne.processes.providers.mock import MockProcessProvider
from omne.processes.service import (
    Admit,
    ApplicationFor,
    Authorize,
    EventSink,
    ProcessService,
    WorkerFor,
)


def select_provider(
    environment: str,
    *,
    root: Path | None = None,
    core_pid: int | None = None,
) -> ProcessProvider:
    """Use the mock table in tests and on non-Linux hosts.

    Development and production on Linux read ``/proc``. That read does not
    start a process and does not send a signal.
    """

    if environment == "testing" or not sys.platform.startswith("linux"):
        return MockProcessProvider()
    return LinuxProcessProvider(root=root, core_pid=core_pid)


def process_service(
    environment: str,
    *,
    sink: EventSink | None = None,
    authorize: Authorize | None = None,
    admit: Admit | None = None,
    worker_for: WorkerFor | None = None,
    application_for: ApplicationFor | None = None,
    root: Path | None = None,
    core_pid: int | None = None,
) -> ProcessService:
    """Return a service bound to the selected provider."""

    return ProcessService(
        select_provider(environment, root=root, core_pid=core_pid),
        sink=sink,
        authorize=authorize,
        admit=admit,
        worker_for=worker_for,
        application_for=application_for,
    )
