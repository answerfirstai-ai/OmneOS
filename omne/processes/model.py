"""Processes OMNE can name. A record is not a shell command.

Command lines stay empty unless a caller is permitted to see them. Lifecycle
actions do not signal a protected process.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ProviderName = Literal["mock", "linux"]
ProcessAction = Literal["start", "stop", "restart", "command"]
ProcessStateName = Literal[
    "running",
    "sleeping",
    "disk_sleep",
    "zombie",
    "stopped",
    "tracing",
    "idle",
    "dead",
    "unknown",
]
Protection = Literal[
    "pid1",
    "kernel",
    "system_service",
    "omne_core",
    "security",
    "desktop_session",
]
ProcessEventType = Literal[
    "process.started",
    "process.stopped",
    "process.restarted",
    "process.protected",
]


class ResourceLimits(BaseModel):
    """Limits read for one process. Unlimited values stay null."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cpu_seconds: int | None = None
    address_bytes: int | None = None
    open_files: int | None = None
    processes: int | None = None


class ProcessOwnership(BaseModel):
    """The OMNE worker and task that launched a process, when one did."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_id: str | None = None
    worker_id: str | None = None
    task_id: str | None = None
    application_id: str | None = None


class ProcessRecord(BaseModel):
    """One process. ``command_line`` is null unless the caller may see it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    pid: int = Field(ge=1)
    executable: str = Field(min_length=1)
    command_line: str | None = None
    command_permitted: bool = False
    cpu_percent: float | None = None
    cpu_seconds: float | None = None
    ram_bytes: int | None = Field(default=None, ge=0)
    owner: str = Field(min_length=1)
    parent_pid: int | None = Field(default=None, ge=0)
    children: list[int] = Field(default_factory=list)
    state: ProcessStateName
    started_at: str | None = None
    limits: ResourceLimits = Field(default_factory=ResourceLimits)
    protection: Protection | None = None
    ownership: ProcessOwnership = Field(default_factory=ProcessOwnership)
    owned: bool = False
    synthetic: bool = False

    @model_validator(mode="after")
    def _command_requires_permission(self) -> ProcessRecord:
        if self.command_line is not None and not self.command_permitted:
            raise ValueError("command line requires permission")
        return self


class ProcessSnapshot(BaseModel):
    """One read of the process table."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: ProviderName
    observed: bool
    processes: list[ProcessRecord] = Field(default_factory=list)
    control_installed: bool = False
    gaps: list[str] = Field(default_factory=list)
    commanded: bool = False

    @field_validator("commanded")
    @classmethod
    def _not_commanded(cls, value: bool) -> bool:
        if value:
            raise ValueError("process control must not command a shell")
        return value

    @field_validator("control_installed")
    @classmethod
    def _host_control_closed(cls, value: bool) -> bool:
        if value:
            raise ValueError("host process control is not installed")
        return value


class ProcessRequest(BaseModel):
    """A lifecycle request. It carries no shell string."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: ProcessAction
    agent_id: str = Field(min_length=1)
    task_id: str | None = None
    worker_id: str | None = None
    application_id: str | None = None
    pid: int | None = Field(default=None, ge=1)
    argv: list[str] | None = None
    reveal: bool = False

    def public_arguments(self) -> dict[str, object]:
        """Arguments safe for the permission policy. The command line stays out."""

        arguments: dict[str, object] = {"action": self.action}
        if self.pid is not None:
            arguments["pid"] = self.pid
        if self.argv:
            arguments["argv"] = [self.argv[0]]
        return arguments


class ProcessEvent(BaseModel):
    """One process event. The payload names a pid, not a command line."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: ProcessEventType
    payload: dict[str, Any] = Field(default_factory=dict)


class ProcessOutcome(BaseModel):
    """The result of one lifecycle action."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    applied: bool
    permitted: bool
    reason: str
    state: ProcessSnapshot
    command_line: str | None = None
    events: list[ProcessEvent] = Field(default_factory=list)
