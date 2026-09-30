"""Installed applications. A record names a program. It is not a shell command.

Launch, focus, and close go through a permission check. The host process is
not started by this model.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ProviderName = Literal["mock", "linux"]
ApplicationState = Literal["installed", "running", "focused", "hidden"]
ApplicationAction = Literal["launch", "focus", "close"]
ApplicationEventType = Literal[
    "application.discovered",
    "application.launched",
    "application.focused",
    "application.closed",
]


class AppProcess(BaseModel):
    """A running process that belongs to one application."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    pid: int = Field(ge=1)
    executable: str = Field(min_length=1)


class AppWindow(BaseModel):
    """A window whose application id matches one installed application."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    app_id: str = Field(min_length=1)
    focused: bool = False


class Application(BaseModel):
    """One desktop application and the processes and windows observed for it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    desktop_entry: str = Field(min_length=1)
    executable: str | None = None
    icon: str = ""
    categories: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    processes: list[AppProcess] = Field(default_factory=list)
    windows: list[AppWindow] = Field(default_factory=list)
    state: ApplicationState
    launchable: bool = False
    commanded: bool = False

    @field_validator("commanded")
    @classmethod
    def _not_commanded(cls, value: bool) -> bool:
        if value:
            raise ValueError("application launch must not command a shell")
        return value


class ApplicationCatalog(BaseModel):
    """One read of installed applications."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: ProviderName
    observed: bool
    applications: list[Application] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    commanded: bool = False

    @field_validator("commanded")
    @classmethod
    def _not_commanded(cls, value: bool) -> bool:
        if value:
            raise ValueError("application launch must not command a shell")
        return value


class ApplicationRequest(BaseModel):
    """A named application action. The request has no command string."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: ApplicationAction
    application_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)

    def public_arguments(self) -> dict[str, object]:
        """Arguments safe to hand to the permission policy."""

        return {"application_id": self.application_id}


class ApplicationReport(BaseModel):
    """The stages of one open request, from intent through observation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: Literal["application.open"] = "application.open"
    query: str
    application_id: str | None = None
    permission: Literal["ALLOW", "DENY", "CONFIRM", "absent"]
    launched: bool
    process_observed: bool
    window_observed: bool
    report: str
    application: Application | None = None


class ApplicationEvent(BaseModel):
    """One application event. The payload names an application, not a command."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: ApplicationEventType
    payload: dict[str, Any] = Field(default_factory=dict)


class ApplyOutcome(BaseModel):
    """Whether a request changed the recorded application session."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    applied: bool
    reason: str
    catalog: ApplicationCatalog
    events: list[ApplicationEvent] = Field(default_factory=list)
