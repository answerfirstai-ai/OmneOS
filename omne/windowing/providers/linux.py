"""Linux window record backed by an explicit labwc snapshot.

The snapshot is a test and integration seam. This provider does not connect to
a Wayland socket, does not start labwc, and does not send a window command.
A permitted change updates the in-memory copy only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from omne.windowing.model import (
    ApplyOutcome,
    ManagedWindow,
    MonitorRecord,
    WindowingState,
    WindowRequest,
    WorkspaceRecord,
)
from omne.windowing.session import NOT_OBSERVED, WindowSession

INVALID_SNAPSHOT = "window snapshot is invalid"


class _SnapshotWorkspace(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    active: bool


class _SnapshotMonitor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    x: int
    y: int
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class _SnapshotWindow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    app_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    monitor_id: str | None
    x: int | None
    y: int | None
    width: int | None
    height: int | None
    fullscreen: bool
    minimized: bool
    maximized: bool
    focused: bool
    mapped: bool
    owner: str | None


class _Snapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    compositor: Literal["labwc"]
    workspaces: list[_SnapshotWorkspace]
    windows: list[_SnapshotWindow]
    monitors: list[_SnapshotMonitor]


class LinuxWindowProvider:
    """Read a labwc snapshot and keep later edits in memory."""

    def __init__(self, *, root: Path | None = None, snapshot_path: Path | None = None) -> None:
        self._root = root if root is not None else Path("/")
        path = resolve_snapshot_path(self._root, snapshot_path)
        session = _load(path)
        self._session = session if session is not None else _unknown(_detail_for(path))

    def state(self) -> WindowingState:
        return self._session.state()

    def apply(self, request: WindowRequest) -> ApplyOutcome:
        return self._session.apply(request)


def resolve_snapshot_path(root: Path, explicit: Path | None) -> Path | None:
    """Return the snapshot to read.

    The host root is never given a default path, so a live session is not
    observed by opening ``/run/omne/windows.json``.
    """

    if explicit is not None:
        return explicit
    if root == Path("/"):
        return None
    return root / "run" / "omne" / "windows.json"


def _detail_for(path: Path | None) -> str:
    if path is not None and path.is_file():
        return INVALID_SNAPSHOT
    return NOT_OBSERVED


def _unknown(detail: str) -> WindowSession:
    return WindowSession(
        provider="labwc",
        compositor="labwc",
        known=False,
        detail=detail,
        windows=[],
        workspaces=[],
        monitors=[],
    )


def _load(path: Path | None) -> WindowSession | None:
    if path is None or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        snapshot = _Snapshot.model_validate(payload)
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError):
        return None
    return _session(snapshot)


def _session(snapshot: _Snapshot) -> WindowSession | None:
    workspace_ids = [workspace.id for workspace in snapshot.workspaces]
    monitor_ids = [monitor.id for monitor in snapshot.monitors]
    window_ids = [window.id for window in snapshot.windows]
    if len(set(workspace_ids)) != len(workspace_ids):
        return None
    if len(set(monitor_ids)) != len(monitor_ids):
        return None
    if len(set(window_ids)) != len(window_ids):
        return None
    workspaces = [
        WorkspaceRecord(id=workspace.id, name=workspace.name, active=workspace.active)
        for workspace in snapshot.workspaces
    ]
    monitors = [
        MonitorRecord(
            id=monitor.id,
            name=monitor.name,
            x=monitor.x,
            y=monitor.y,
            width=monitor.width,
            height=monitor.height,
        )
        for monitor in snapshot.monitors
    ]
    windows: list[ManagedWindow] = []
    known_workspaces = set(workspace_ids)
    known_monitors = set(monitor_ids)
    for window in snapshot.windows:
        if window.workspace_id not in known_workspaces:
            return None
        if window.monitor_id is not None and window.monitor_id not in known_monitors:
            return None
        if window.owner is not None and not window.owner.strip():
            return None
        if _bad_extent(window.width) or _bad_extent(window.height):
            return None
        windows.append(
            ManagedWindow(
                id=window.id,
                title=window.title,
                app_id=window.app_id,
                workspace_id=window.workspace_id,
                monitor_id=window.monitor_id,
                x=window.x,
                y=window.y,
                width=window.width,
                height=window.height,
                fullscreen=window.fullscreen,
                minimized=window.minimized,
                maximized=window.maximized,
                focused=window.focused,
                mapped=window.mapped,
                owner=window.owner,
            )
        )
    return WindowSession(
        provider="labwc",
        compositor="labwc",
        known=True,
        detail=None,
        windows=windows,
        workspaces=workspaces,
        monitors=monitors,
    )


def _bad_extent(value: int | None) -> bool:
    return value is not None and value <= 0
