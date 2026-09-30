"""Recovery records. A failed start is explained. User data stays in place.

The states are the only modes OMNE reports. Erase and reinstall are refused
by the model, not offered as successful outcomes.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

RecoveryState = Literal["NORMAL", "DEGRADED", "SAFE_MODE", "RECOVERY"]
CheckName = Literal[
    "linux",
    "systemd",
    "service",
    "core",
    "ipc",
    "graphics",
    "network",
    "storage",
]
FailureKind = Literal[
    "core",
    "shell",
    "update",
    "model",
    "configuration",
    "graphics",
    "runaway",
]
BootPhase = Literal["starting", "ready", "stopped", "failed"]
IncidentSource = Literal["startup", "check", "operator"]
RecoveryMode = Literal["auto", "safe"]

CHECKS: tuple[CheckName, ...] = (
    "linux",
    "systemd",
    "service",
    "core",
    "ipc",
    "graphics",
    "network",
    "storage",
)
REQUIRED_CHECKS = frozenset[CheckName]({"linux", "systemd", "service", "core", "ipc", "storage"})
CHECK_REASONS: dict[CheckName, str] = {
    "linux": "linux is not running",
    "systemd": "systemd is not running",
    "service": "omne system service is not active",
    "core": "core is not running",
    "ipc": "core IPC is not accepting connections",
    "graphics": "graphics are unavailable",
    "network": "network is not ready",
    "storage": "storage is not usable",
}
BUILTIN_AGENTS = frozenset({"system", "coding", "research", "browser", "browser-worker"})
STARTUP_FAILURE_LIMIT = 3
REFUSED_ACTIONS = ("erase", "reinstall")
OPERATOR_COMMANDS = ("status", "check", "safe", "explain", "normal", "rollback")


class CheckResult(BaseModel):
    """One health check. A failed required check keeps OMNE out of normal mode."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: CheckName
    ok: bool
    required: bool
    reason: str = ""


class Incident(BaseModel):
    """One recorded failure. Closing it does not delete user files."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    kind: FailureKind
    reason: str
    open: bool = True
    source: IncidentSource = "operator"
    agent_id: str = ""
    model_id: str = ""


class BootRecord(BaseModel):
    """One core start. A start that never reaches ready counts as a failure."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    phase: BootPhase
    reason: str = ""


class Journal(BaseModel):
    """Persisted recovery history. It is not a copy of the user's files."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    boots: list[BootRecord] = Field(default_factory=list)
    incidents: list[Incident] = Field(default_factory=list)
    mode: RecoveryMode = "auto"
    mode_reason: str = ""
    forced_checks: dict[str, str] = Field(default_factory=dict)


class ProbeReport(BaseModel):
    """What the host probe observed. Shell failure is an incident, not a ninth check."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    checks: list[CheckResult]
    shell_failed: bool = False
    shell_reason: str = ""


class RecoveryStatus(BaseModel):
    """The explanation of the current mode. Diagnostics stay available."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: RecoveryState
    explanation: str
    previous_failure: str = ""
    checks: list[CheckResult]
    incidents: list[Incident] = Field(default_factory=list)
    startup_failures: int = Field(ge=0)
    minimal_services: bool
    third_party_agents_enabled: bool
    optional_models_enabled: bool
    shell_reduced: bool
    diagnostics_available: bool = True
    data_erased: bool = False
    os_reinstalled: bool = False
    disabled_models: list[str] = Field(default_factory=list)
    disabled_agents: list[str] = Field(default_factory=list)
    commands: list[str] = Field(default_factory=list)
    refused_actions: list[str] = Field(default_factory=lambda: list(REFUSED_ACTIONS))

    @field_validator("data_erased", "os_reinstalled")
    @classmethod
    def _stay_closed(cls, value: bool) -> bool:
        if value:
            raise ValueError("recovery must not erase user data or reinstall the os")
        return value

    @field_validator("diagnostics_available")
    @classmethod
    def _diagnostics_stay(cls, value: bool) -> bool:
        if not value:
            raise ValueError("diagnostics stay available")
        return value


def check_result(name: CheckName, *, ok: bool, reason: str = "") -> CheckResult:
    """Build one check. A passing check has an empty reason."""

    return CheckResult(
        name=name,
        ok=ok,
        required=name in REQUIRED_CHECKS,
        reason="" if ok else (reason or CHECK_REASONS[name]),
    )


def explain_text(status: RecoveryStatus) -> str:
    """Return the sentence an operator should read.

    A healthy start still names the last failed start when one was recorded.
    """

    if status.state == "NORMAL" and status.previous_failure:
        return f"{status.explanation}. the last failed start was: {status.previous_failure}"
    return status.explanation
