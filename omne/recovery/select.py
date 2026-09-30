"""Choose the recovery probe.

Tests use a healthy probe. Linux development and production read the host and
do not start units.
"""

from __future__ import annotations

import sys
from pathlib import Path

from omne.recovery.probe import LinuxRecoveryProbe, MockRecoveryProbe
from omne.recovery.service import EventSink, RecoveryService


def recovery_service(
    environment: str,
    state_dir: Path | None,
    *,
    updates_dir: Path | None = None,
    port: int = 8787,
    sink: EventSink | None = None,
    probe: MockRecoveryProbe | LinuxRecoveryProbe | None = None,
) -> RecoveryService:
    """Return a service that explains startup and does not erase user data."""

    if probe is None:
        if environment == "testing" or not sys.platform.startswith("linux"):
            probe = MockRecoveryProbe()
        else:
            probe = LinuxRecoveryProbe()
    return RecoveryService(
        state_dir,
        probe,
        updates_dir=updates_dir,
        port=port,
        sink=sink,
    )
