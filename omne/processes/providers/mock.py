"""In-memory processes for tests and non-Linux hosts.

Start, stop, and restart change the record only. Nothing is signaled.
"""

from __future__ import annotations

from typing import Any

from omne.processes.model import (
    ProcessEvent,
    ProcessEventType,
    ProcessOutcome,
    ProcessOwnership,
    ProcessRecord,
    ProcessRequest,
    ProcessSnapshot,
    ProcessStateName,
    ResourceLimits,
)
from omne.processes.protect import protection_for, protection_reason, refused_program

_NOT_OWNED = "process is not owned by an OMNE worker"
_MISSING = "process was not found"
HOST_CONTROL = "host process control is not installed"


class MockProcessProvider:
    """A process table whose lifecycle stays inside the record."""

    def __init__(self) -> None:
        self._hidden: dict[int, str] = {}
        self._processes = {item.pid: item for item in _seed()}
        self._next_pid = 61000

    def snapshot(self) -> ProcessSnapshot:
        return ProcessSnapshot(
            provider="mock",
            observed=True,
            processes=_public(self._processes),
            gaps=[HOST_CONTROL],
        )

    def apply(self, request: ProcessRequest) -> ProcessOutcome:
        if request.action == "start":
            return self._start(request)
        if request.action == "stop":
            return self._stop(request)
        if request.action == "restart":
            return self._restart(request)
        return self._command(request)

    def _start(self, request: ProcessRequest) -> ProcessOutcome:
        refusal = refused_program(request.argv)
        if refusal is not None:
            return self._refuse(refusal, None)
        if not request.argv:
            return self._refuse("process start requires a program", None)
        self._next_pid += 1
        record = ProcessRecord(
            pid=self._next_pid,
            executable=request.argv[0],
            cpu_percent=0.0,
            cpu_seconds=0.0,
            ram_bytes=0,
            owner="omne",
            parent_pid=None,
            state="running",
            started_at="2026-01-01T00:00:00+00:00",
            limits=ResourceLimits(open_files=1024, processes=256),
            ownership=_ownership(request),
            owned=True,
            synthetic=True,
        )
        self._hidden[record.pid] = " ".join(request.argv)
        self._processes[record.pid] = record
        return self._done(
            "started",
            "process.started",
            {"pid": record.pid, "agent_id": request.agent_id},
        )

    def _stop(self, request: ProcessRequest) -> ProcessOutcome:
        record, refusal = self._mutable(request)
        if record is None:
            return self._refuse(refusal or _MISSING, request.pid)
        self._processes[record.pid] = record.model_copy(update={"state": "stopped"})
        return self._done("stopped", "process.stopped", {"pid": record.pid})

    def _restart(self, request: ProcessRequest) -> ProcessOutcome:
        record, refusal = self._mutable(request)
        if record is None:
            return self._refuse(refusal or _MISSING, request.pid)
        self._processes[record.pid] = record.model_copy(update={"state": "running"})
        return self._done("restarted", "process.restarted", {"pid": record.pid})

    def _command(self, request: ProcessRequest) -> ProcessOutcome:
        if request.pid is None or request.pid not in self._processes:
            return self._refuse(_MISSING, request.pid)
        stored = self._hidden.get(request.pid)
        line = stored if request.reveal else None
        permitted = "command line is permitted"
        hidden = "command line is not permitted"
        return ProcessOutcome(
            applied=request.reveal and line is not None,
            permitted=request.reveal,
            reason=permitted if request.reveal else hidden,
            state=self.snapshot(),
            command_line=line,
        )

    def _mutable(self, request: ProcessRequest) -> tuple[ProcessRecord | None, str | None]:
        if request.pid is None or request.pid not in self._processes:
            return None, _MISSING
        record = self._processes[request.pid]
        if record.protection is not None:
            return None, protection_reason(record.protection)
        if not record.owned:
            return None, _NOT_OWNED
        return record, None

    def _refuse(self, reason: str, pid: int | None) -> ProcessOutcome:
        events: list[ProcessEvent] = []
        if "protected" in reason:
            payload: dict[str, Any] = {}
            if pid is not None:
                payload["pid"] = pid
            events.append(ProcessEvent(type="process.protected", payload=payload))
        return ProcessOutcome(
            applied=False,
            permitted=False,
            reason=reason,
            state=self.snapshot(),
            events=events,
        )

    def _done(
        self, reason: str, event_type: ProcessEventType, payload: dict[str, Any]
    ) -> ProcessOutcome:
        return ProcessOutcome(
            applied=True,
            permitted=True,
            reason=reason,
            state=self.snapshot(),
            events=[ProcessEvent(type=event_type, payload=payload)],
        )


def _seed() -> list[ProcessRecord]:
    rows = [
        (1, "systemd", 0, "root", "sleeping"),
        (2, "kthreadd", 0, "root", "sleeping"),
        (100, "systemd-logind", 1, "root", "sleeping"),
        (200, "sshd", 1, "root", "sleeping"),
        (300, "labwc", 1, "omne", "running"),
        (400, "OMNE", 1, "omne", "running"),
        (500, "firefox", 300, "omne", "running"),
    ]
    found: list[ProcessRecord] = []
    for pid, name, parent, owner, state in rows:
        kind = protection_for(pid=pid, parent_pid=parent, name=name, core_pid=400)
        running: ProcessStateName = "running" if state == "running" else "sleeping"
        found.append(
            ProcessRecord(
                pid=pid,
                executable=name,
                cpu_percent=0.1 if pid == 500 else 0.0,
                cpu_seconds=0.2 if pid == 500 else 0.0,
                ram_bytes=4096 if pid == 500 else 1024,
                owner=owner,
                parent_pid=parent,
                state=running,
                started_at="2026-01-01T00:00:00+00:00",
                limits=ResourceLimits(open_files=1024),
                protection=kind,
                ownership=_firefox_owner(pid),
            )
        )
    return found


def _firefox_owner(pid: int) -> ProcessOwnership:
    if pid == 500:
        return ProcessOwnership(application_id="firefox")
    return ProcessOwnership()


def _public(processes: dict[int, ProcessRecord]) -> list[ProcessRecord]:
    children: dict[int, list[int]] = {}
    for record in processes.values():
        if record.parent_pid is not None:
            children.setdefault(record.parent_pid, []).append(record.pid)
    published: list[ProcessRecord] = []
    for record in processes.values():
        published.append(
            record.model_copy(
                update={
                    "children": sorted(children.get(record.pid, [])),
                    "command_line": None,
                    "command_permitted": False,
                }
            )
        )
    return sorted(published, key=lambda item: item.pid)


def _ownership(request: ProcessRequest) -> ProcessOwnership:
    return ProcessOwnership(
        agent_id=request.agent_id,
        worker_id=request.worker_id,
        task_id=request.task_id,
        application_id=request.application_id,
    )
