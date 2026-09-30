"""Choose the update service.

Every environment protects the host. Status and dry-run do not call apt.
"""

from __future__ import annotations

from pathlib import Path

from omne.updates.service import UpdateService


def update_service(environment: str, state_dir: Path) -> UpdateService:
    """Return a service that will not install packages on this machine."""

    del environment
    return UpdateService(state_dir, host_protected=True)
