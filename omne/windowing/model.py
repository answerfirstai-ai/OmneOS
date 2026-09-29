"""Window, workspace, and monitor state known to OMNE.

These records describe a compositor session. They do not place windows.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ProviderName = Literal["mock", "labwc"]
WindowAction = Literal[
    "launch",
    "focus",
    "close",
    "move",
    "resize",
    "minimize",
    "maximize",
    "fullscreen",
    "workspace",
]
WindowEventType = Literal[
    "window.created",
    "window.focused",
    "window.closed",
    "window.changed",
    "workspace.changed",
]


class ManagedWindow(BaseModel):
    """One window OMNE can name, focus, or ask to close."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    app_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    monitor_id: str | None = None
    x: int | None = None
    y: int | None = None
    width: int | None = None
    height: int | None = None
    fullscreen: bool = False
    minimized: bool = False
    maximized: bool = False
    focused: bool = False
    mapped: bool = False
    owner: str | None = None


class WorkspaceRecord(BaseModel):
    """One workspace and the windows currently on it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    active: bool
    window_ids: list[str] = Field(default_factory=list)


class MonitorRecord(BaseModel):
    """One output a window can be assigned to."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    x: int
    y: int
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class WindowingState(BaseModel):
    """One read of window state. An unknown list is not an empty desktop."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: ProviderName
    known: bool
    compositor: str
    compositor_commanded: bool = False
    focused_window_id: str | None = None
    active_workspace_id: str | None = None
    windows: list[ManagedWindow] = Field(default_factory=list)
    workspaces: list[WorkspaceRecord] = Field(default_factory=list)
    monitors: list[MonitorRecord] = Field(default_factory=list)
    fullscreen_window_id: str | None = None
    detail: str | None = None

    @field_validator("compositor_commanded")
    @classmethod
    def _record_only(cls, value: bool) -> bool:
        if value:
            raise ValueError("compositor_commanded must be false")
        return value


class WindowRequest(BaseModel):
    """One requested change. The service checks a grant before it is applied."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: WindowAction
    agent_id: str = Field(min_length=1)
    app_id: str | None = None
    title: str | None = None
    window_id: str | None = None
    x: int | None = None
    y: int | None = None
    width: int | None = None
    height: int | None = None
    monitor_id: str | None = None
    workspace_id: str | None = None
    fullscreen: bool | None = None


class WindowingEvent(BaseModel):
    """One windowing event ready for the OMNE event bus."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: WindowEventType
    payload: dict[str, Any] = Field(default_factory=dict)


class ApplyOutcome(BaseModel):
    """Whether a request changed the recorded session."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    applied: bool
    reason: str
    state: WindowingState
    events: list[WindowingEvent] = Field(default_factory=list)
