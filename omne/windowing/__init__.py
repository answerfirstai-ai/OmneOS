"""Window records for labwc. OMNE does not implement a window manager.

Providers report windows, focus, workspaces, and monitors. A grant is required
before a request changes that record. The record is not sent to the compositor.
"""

from omne.windowing.model import (
    ApplyOutcome,
    ManagedWindow,
    MonitorRecord,
    WindowingState,
    WindowRequest,
    WorkspaceRecord,
)
from omne.windowing.select import select_provider, windowing_service
from omne.windowing.service import WindowingService

__all__ = [
    "ApplyOutcome",
    "ManagedWindow",
    "MonitorRecord",
    "WindowRequest",
    "WindowingService",
    "WindowingState",
    "WorkspaceRecord",
    "select_provider",
    "windowing_service",
]
