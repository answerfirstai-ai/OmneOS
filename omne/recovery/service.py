"""Decide NORMAL, DEGRADED, SAFE_MODE, or RECOVERY.

Mutations write the journal and, when asked, the update slot record. They do
not erase user data and they do not reinstall the operating system.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

from omne.recovery.journal import RecoveryJournal
from omne.recovery.model import (
    BUILTIN_AGENTS,
    CHECKS,
    OPERATOR_COMMANDS,
    REFUSED_ACTIONS,
    REQUIRED_CHECKS,
    STARTUP_FAILURE_LIMIT,
    BootPhase,
    BootRecord,
    CheckName,
    CheckResult,
    FailureKind,
    Incident,
    IncidentSource,
    Journal,
    ProbeReport,
    RecoveryState,
    RecoveryStatus,
    check_result,
)
from omne.recovery.probe import MockRecoveryProbe, RecoveryProbe
from omne.updates.model import UpdatePhase
from omne.updates.service import UpdateRejected, UpdateService
from omne.updates.state import UpdateStore

EventSink = Callable[[str, dict[str, Any]], None]


class RecoveryRefused(Exception):
    """A recovery command cannot proceed. Nothing was erased."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.code = "rejected"


class RecoveryService:
    """Health, startup history, safe mode, and recovery commands."""

    def __init__(
        self,
        state_dir: Path | None,
        probe: RecoveryProbe | None = None,
        *,
        updates_dir: Path | None = None,
        port: int = 8787,
        sink: EventSink | None = None,
    ) -> None:
        self._journal = RecoveryJournal(state_dir)
        self._probe = probe if probe is not None else MockRecoveryProbe()
        self._updates_dir = updates_dir
        self._port = port
        self._state_dir = state_dir
        self._sink = sink

    def assess(self) -> RecoveryStatus:
        """Read checks and history. This does not start a service or delete a file."""

        journal = self._journal.load()
        report = self._probe.probe(data_dir=_data_dir(self._state_dir), port=self._port)
        return _status(journal, report, self._updates_dir)

    def begin_boot(self) -> RecoveryStatus:
        """Record a start. An unfinished previous start becomes a failure."""

        journal = self._journal.load()
        if journal.boots:
            previous = journal.boots[-1]
            if previous.phase == "starting":
                journal = _fail_boot(journal, previous.id, "core stopped before it was ready")
            elif previous.phase == "ready":
                journal = _fail_boot(journal, previous.id, "core stopped without a clean shutdown")
        boot_id = str(uuid4())
        journal = journal.model_copy(
            update={
                "boots": [*journal.boots, _boot(boot_id, "starting", "")][-20:],
            }
        )
        self._journal.save(journal)
        status = self.assess()
        self._emit("recovery.startup", status)
        return status

    def mark_ready(self) -> RecoveryStatus:
        """The process accepted connections. Startup crashes from this boot close."""

        journal = self._journal.load()
        boots = list(journal.boots)
        if boots and boots[-1].phase == "starting":
            boots[-1] = boots[-1].model_copy(update={"phase": "ready", "reason": ""})
        incidents = [
            item.model_copy(update={"open": False})
            if item.open and item.source == "startup"
            else item
            for item in journal.incidents
        ]
        self._journal.save(journal.model_copy(update={"boots": boots, "incidents": incidents}))
        return self.assess()

    def mark_stopped(self) -> RecoveryStatus:
        """A clean shutdown. The next start does not treat it as a crash."""

        journal = self._journal.load()
        boots = list(journal.boots)
        if boots and boots[-1].phase == "ready":
            boots[-1] = boots[-1].model_copy(update={"phase": "stopped"})
        self._journal.save(journal.model_copy(update={"boots": boots}))
        return self.assess()

    def fail_boot(self, reason: str) -> RecoveryStatus:
        """Record why this start stopped. The reason is kept for the next boot."""

        journal = self._journal.load()
        if journal.boots and journal.boots[-1].phase == "starting":
            journal = _fail_boot(journal, journal.boots[-1].id, reason)
        else:
            journal = _append_incident(journal, "core", reason, source="startup")
        self._journal.save(journal)
        status = self.assess()
        self._emit("recovery.startup", status)
        return status

    def inject(
        self,
        *,
        check: CheckName | None = None,
        kind: FailureKind | None = None,
        reason: str,
        agent_id: str = "",
        model_id: str = "",
        ram_mb: int | None = None,
        limit_mb: int | None = None,
    ) -> RecoveryStatus:
        """Record one injected failure. The host packages and user files stay."""

        if check is None and kind is None:
            raise RecoveryRefused("a failure injection needs a check or a kind")
        journal = self._journal.load()
        if check is not None:
            forced = dict(journal.forced_checks)
            forced[check] = reason or check_result(check, ok=False).reason
            journal = journal.model_copy(update={"forced_checks": forced})
        if kind == "runaway":
            limit = 0 if limit_mb is None else limit_mb
            used = 0 if ram_mb is None else ram_mb
            target = agent_id or "agent"
            reason = f"agent {target} used {used} MB of memory above the {limit} MB limit"
            journal = _append_incident(journal, kind, reason, agent_id=target)
        elif kind is not None:
            journal = _append_incident(
                journal,
                kind,
                reason,
                agent_id=agent_id,
                model_id=model_id,
            )
        self._journal.save(journal)
        status = self.assess()
        self._emit("recovery.injected", status)
        return status

    def execute(self, command: str) -> RecoveryStatus:
        """Run one recovery command. Erase and reinstall are refused."""

        if command == "erase":
            raise RecoveryRefused("refusing to erase user data")
        if command == "reinstall":
            raise RecoveryRefused("refusing to reinstall the operating system")
        if command in {"status", "check", "explain"}:
            return self.assess()
        if command == "safe":
            return self.enter_safe("operator requested safe mode")
        if command == "normal":
            return self.request_normal()
        if command == "rollback":
            return self.rollback_update()
        raise RecoveryRefused(f"unknown recovery command: {command}")

    def enter_safe(self, reason: str) -> RecoveryStatus:
        """Start with minimal services. User files are not removed."""

        journal = self._journal.load()
        self._journal.save(journal.model_copy(update={"mode": "safe", "mode_reason": reason}))
        status = self.assess()
        self._emit("recovery.safe_mode", status)
        return status

    def request_normal(self) -> RecoveryStatus:
        """Leave safe mode when required checks pass. Blocking failures stay explained."""

        current = self.assess()
        if _blocked(current):
            raise RecoveryRefused(current.explanation)
        journal = self._journal.load()
        boots = list(journal.boots)
        if boots and boots[-1].phase == "starting":
            boots[-1] = boots[-1].model_copy(update={"phase": "ready", "reason": ""})
        incidents = [item.model_copy(update={"open": False}) for item in journal.incidents]
        self._journal.save(
            journal.model_copy(
                update={
                    "mode": "auto",
                    "mode_reason": "",
                    "forced_checks": {},
                    "boots": boots,
                    "incidents": incidents,
                }
            )
        )
        status = self.assess()
        self._emit("recovery.normal", status)
        return status

    def rollback_update(self) -> RecoveryStatus:
        """Roll the update slot record back. This does not reinstall the OS."""

        if self._updates_dir is None:
            raise RecoveryRefused("rollback is not available")
        try:
            UpdateService(self._updates_dir, host_protected=True).rollback()
        except UpdateRejected as exc:
            raise RecoveryRefused(str(exc)) from exc
        status = self.assess()
        self._emit("recovery.rollback", status)
        return status

    def disabled_agent_ids(self, agent_ids: Iterable[str]) -> list[str]:
        """Agents that must not run in this mode. ``system`` stays for diagnostics."""

        status = self.assess()
        blocked: set[str] = set(status.disabled_agents)
        if not status.third_party_agents_enabled:
            blocked.update(agent_id for agent_id in agent_ids if agent_id not in BUILTIN_AGENTS)
        return sorted(blocked)

    def disabled_model_ids(self, models: Iterable[tuple[str, str]]) -> list[str]:
        """Optional models stay unloaded in safe mode and recovery. Mock stays."""

        status = self.assess()
        blocked = set(status.disabled_models)
        if not status.optional_models_enabled:
            blocked.update(model_id for model_id, provider in models if provider != "mock")
        return sorted(blocked)

    def _emit(self, event_type: str, status: RecoveryStatus) -> None:
        if self._sink is None:
            return
        self._sink(event_type, {"state": status.state, "explanation": status.explanation})


def configuration_status(message: str) -> RecoveryStatus:
    """Explain an invalid configuration without reading or writing the file again."""

    reason = f"configuration is invalid: {message}"
    incident = Incident(id="configuration", kind="configuration", reason=reason, source="check")
    checks = [check_result(name, ok=True) for name in CHECKS]
    status = _assemble(
        state="RECOVERY",
        checks=checks,
        incidents=[incident],
        startup_failures=0,
        previous_failure="",
        mode_reason="",
        rollback=False,
    )
    return status.model_copy(
        update={
            "minimal_services": True,
            "third_party_agents_enabled": False,
            "optional_models_enabled": False,
            "shell_reduced": True,
        }
    )


def _status(journal: Journal, report: ProbeReport, updates_dir: Path | None) -> RecoveryStatus:
    checks = _apply_forced(report.checks, journal.forced_checks)
    incidents = list(journal.incidents)
    if report.shell_failed:
        incidents.append(
            Incident(
                id="shell-probe",
                kind="shell",
                reason=report.shell_reason or "shell stopped",
                source="check",
            )
        )
    incidents.extend(_update_incidents(updates_dir))
    failures = _consecutive_failures(journal)
    previous = _previous_failure(journal)
    state = _decide(journal, checks, incidents, failures)
    return _assemble(
        state=state,
        checks=checks,
        incidents=[item for item in incidents if item.open],
        startup_failures=failures,
        previous_failure=previous,
        mode_reason=journal.mode_reason,
        rollback=_rollback_available(updates_dir),
    )


def _assemble(
    *,
    state: RecoveryState,
    checks: list[CheckResult],
    incidents: list[Incident],
    startup_failures: int,
    previous_failure: str,
    mode_reason: str,
    rollback: bool,
) -> RecoveryStatus:
    graphics_failed = any(not check.ok and check.name == "graphics" for check in checks)
    shell_open = any(item.kind == "shell" and item.open for item in incidents)
    shell_reduced = state in {"SAFE_MODE", "RECOVERY"} or graphics_failed or shell_open
    disabled_models = sorted(
        {item.model_id for item in incidents if item.kind == "model" and item.model_id}
    )
    disabled_agents = sorted(
        {
            item.agent_id
            for item in incidents
            if item.kind == "runaway" and item.agent_id and item.agent_id != "system"
        }
    )
    explanation = _explanation(state, checks, incidents, startup_failures, mode_reason)
    commands = [name for name in OPERATOR_COMMANDS if name != "rollback" or rollback]
    safe_mode = state == "SAFE_MODE"
    return RecoveryStatus(
        state=state,
        explanation=explanation,
        previous_failure=previous_failure,
        checks=list(checks),
        incidents=incidents,
        startup_failures=startup_failures,
        minimal_services=safe_mode,
        third_party_agents_enabled=not safe_mode,
        optional_models_enabled=not safe_mode,
        shell_reduced=shell_reduced,
        diagnostics_available=True,
        data_erased=False,
        os_reinstalled=False,
        disabled_models=disabled_models,
        disabled_agents=disabled_agents,
        commands=commands,
        refused_actions=list(REFUSED_ACTIONS),
    )


def _decide(
    journal: Journal,
    checks: list[CheckResult],
    incidents: list[Incident],
    failures: int,
) -> RecoveryState:
    required_failed = any(not check.ok and check.name in REQUIRED_CHECKS for check in checks)
    blocking = any(item.open and item.kind in {"configuration", "update"} for item in incidents)
    if required_failed or blocking:
        return "RECOVERY"
    runaway = any(item.open and item.kind == "runaway" for item in incidents)
    if journal.mode == "safe" or failures >= STARTUP_FAILURE_LIMIT or runaway:
        return "SAFE_MODE"
    if any(item.open and item.source == "startup" for item in incidents):
        return "RECOVERY"
    optional_failed = any(not check.ok for check in checks)
    soft = any(
        item.open and item.kind in {"shell", "model", "graphics", "core"} for item in incidents
    )
    if optional_failed or soft:
        return "DEGRADED"
    return "NORMAL"


def _blocked(status: RecoveryStatus) -> bool:
    if any(not check.ok and check.required for check in status.checks):
        return True
    return any(item.open and item.kind in {"configuration", "update"} for item in status.incidents)


def _explanation(
    state: RecoveryState,
    checks: list[CheckResult],
    incidents: list[Incident],
    failures: int,
    mode_reason: str,
) -> str:
    if state == "NORMAL":
        return "startup checks passed"
    parts: list[str] = []
    if mode_reason:
        parts.append(mode_reason)
    for incident in incidents:
        if incident.open and incident.reason:
            parts.append(incident.reason)
    for check in checks:
        if not check.ok and check.reason:
            parts.append(check.reason)
    if failures >= STARTUP_FAILURE_LIMIT:
        parts.append(f"startup failed {failures} consecutive times")
    unique = _unique(parts)
    if not unique:
        return "normal startup failed"
    return "normal startup failed: " + "; ".join(unique)


def _apply_forced(checks: list[CheckResult], forced: Mapping[str, str]) -> list[CheckResult]:
    applied = []
    for check in checks:
        if check.name in forced:
            applied.append(check.model_copy(update={"ok": False, "reason": forced[check.name]}))
        else:
            applied.append(check)
    return applied


def _consecutive_failures(journal: Journal) -> int:
    count = 0
    for boot in reversed(journal.boots):
        if boot.phase == "starting":
            continue
        if boot.phase != "failed":
            break
        count += 1
    return count


def _previous_failure(journal: Journal) -> str:
    for boot in reversed(journal.boots):
        if boot.phase == "failed" and boot.reason:
            return boot.reason
    return ""


def _fail_boot(journal: Journal, boot_id: str, reason: str) -> Journal:
    boots = []
    for boot in journal.boots:
        if boot.id == boot_id:
            boots.append(boot.model_copy(update={"phase": "failed", "reason": reason}))
        else:
            boots.append(boot)
    return _append_incident(
        journal.model_copy(update={"boots": boots}),
        "core",
        reason,
        source="startup",
    )


def _append_incident(
    journal: Journal,
    kind: FailureKind,
    reason: str,
    *,
    source: IncidentSource = "operator",
    agent_id: str = "",
    model_id: str = "",
) -> Journal:
    incident = Incident(
        id=str(uuid4()),
        kind=kind,
        reason=reason,
        source=source,
        agent_id=agent_id,
        model_id=model_id,
    )
    return journal.model_copy(update={"incidents": [*journal.incidents, incident][-50:]})


def _boot(boot_id: str, phase: BootPhase, reason: str) -> BootRecord:
    return BootRecord(id=boot_id, phase=phase, reason=reason)


def _update_incidents(directory: Path | None) -> list[Incident]:
    if directory is None:
        return []
    state = UpdateStore(directory).state
    incidents: list[Incident] = []
    for generation in state.generations:
        if generation.phase not in {
            UpdatePhase.FAILED,
            UpdatePhase.INTERRUPTED,
            UpdatePhase.REJECTED,
        }:
            continue
        incidents.append(
            Incident(
                id=generation.id,
                kind="update",
                reason=(
                    f"update {generation.version} on the {generation.channel} channel "
                    f"is {generation.phase.value}"
                ),
                source="check",
            )
        )
    return incidents


def _rollback_available(directory: Path | None) -> bool:
    if directory is None:
        return False
    return UpdateStore(directory).rollback_target().available


def _unique(parts: list[str]) -> list[str]:
    seen: list[str] = []
    for part in parts:
        if part not in seen:
            seen.append(part)
    return seen


def _data_dir(state_dir: Path | None) -> Path | None:
    if state_dir is None:
        return None
    return state_dir.parent
