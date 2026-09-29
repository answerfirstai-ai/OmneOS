"""Display, monitor, window, workspace, surface, and fullscreen state."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ProviderName = Literal["mock", "labwc"]
Presence = Literal["present", "absent", "unavailable"]
SessionState = Literal["not_running", "running"]


class Monitor(BaseModel):
    """One connected display connector."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str
    connected: bool
    width: int | None = None
    height: int | None = None
    refresh_hz: float | None = None
    primary: bool = False


class Window(BaseModel):
    """One application window known to the display provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    title: str
    app_id: str
    workspace_id: str
    monitor_id: str | None = None
    x: int | None = None
    y: int | None = None
    width: int | None = None
    height: int | None = None
    fullscreen: bool = False
    focused: bool = False
    mapped: bool = False


class Workspace(BaseModel):
    """A set of windows on the compositor."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str
    active: bool
    window_ids: list[str] = Field(default_factory=list)


class Surface(BaseModel):
    """A Wayland surface OMNE expects the shell to occupy later."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    role: Literal["desktop", "window"]
    active: bool
    fullscreen: bool
    uri: str


class FullscreenState(BaseModel):
    """Whether a window currently owns a whole monitor."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    known: bool
    active: bool
    window_id: str | None = None
    monitor_id: str | None = None


class Display(BaseModel):
    """One read of the graphical session. Missing hardware stays absent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: ProviderName
    platform: str
    linux: bool
    wayland: bool
    session: SessionState
    drm: Presence
    gpu_acceleration: Presence
    compositor: str
    compositor_present: bool
    input: Presence
    monitors: list[Monitor] = Field(default_factory=list)
    windows: list[Window] = Field(default_factory=list)
    windows_known: bool
    workspaces: list[Workspace] = Field(default_factory=list)
    fullscreen: FullscreenState
    surface: Surface
    can_launch: bool
    missing: list[str] = Field(default_factory=list)
