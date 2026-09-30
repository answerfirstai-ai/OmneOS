"""Check permission, then record a process action.

Start, stop, and restart pass through a grant. The provider decides whether
the record changes. Command lines stay off the event payload.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from omne.processes.model import ProcessOutcome, ProcessRequest, ProcessSnapshot
from omne.processes.provider import ProcessProvider

Authorize = Callable[[str, dict[str, object], Mapping[str, Sequence[str]], str], tuple[str, str]]
EventSink = Callable[[str, dict[str, Any]], None]
Admit = Callable[[], tuple[str, str]]
WorkerFor = Callable[[str | None], str | None]
ApplicationFor = Callable[[str], str | None]

_ACTIONS = {
    "start": "process.start",
    "stop": "process.stop",
    "restart": "process.restart",
    "command": "process.command",
}


class ProcessService:
    """Read the table freely. Change a process only after permission allows it."""

    def __init__(
        self,
        provider: ProcessProvider,
        *,
        sink: EventSink | None = None,
        authorize: Authorize | None = None,
        admit: Admit | None = None,
        worker_for: WorkerFor | None = None,
        application_for: ApplicationFor | None = None,
    ) -> None:
        self._provider = provider
        self._sink = sink
        self._authorize = authorize or _deny_all
        self._admit = admit or _allow
        self._worker_for = worker_for
        self._application_for = application_for

    def status(self) -> ProcessSnapshot:
        return self._provider.snapshot()

    def apply(
        self,
        request: ProcessRequest,
        grants: Mapping[str, Sequence[str]],
        environment: str,
        *,
        permitted: bool = False,
    ) -> ProcessOutcome:
        if not permitted:
            decision, reason = self._authorize(
                _ACTIONS[request.action],
                request.public_arguments(),
                grants,
                environment,
            )
            if decision != "ALLOW":
                return ProcessOutcome(
                    applied=False,
                    permitted=False,
                    reason=reason,
                    state=self.status(),
                )
        prepared = self._prepare(request)
        if prepared.action == "start":
            decision, reason = self._admit()
            if decision != "ALLOW":
                return ProcessOutcome(
                    applied=False,
                    permitted=False,
                    reason=reason,
                    state=self.status(),
                )
        outcome = self._provider.apply(prepared)
        if self._sink is not None:
            for event in outcome.events:
                self._sink(event.type, dict(event.payload))
        return outcome

    def _prepare(self, request: ProcessRequest) -> ProcessRequest:
        worker_id = request.worker_id
        if worker_id is None and self._worker_for is not None:
            worker_id = self._worker_for(request.task_id)
        application_id = request.application_id
        if application_id is None and request.argv and self._application_for is not None:
            application_id = self._application_for(request.argv[0])
        if worker_id == request.worker_id and application_id == request.application_id:
            return request
        return request.model_copy(update={"worker_id": worker_id, "application_id": application_id})


def admit_resources(cpu_percent: float | None, available_mb: float | None) -> tuple[str, str]:
    """Deny a start when measured CPU or free memory is already exhausted.

    Unknown telemetry does not invent a denial.
    """

    if cpu_percent is not None and cpu_percent >= 95:
        return "DENY", "cpu is too high"
    if available_mb is not None and available_mb < 64:
        return "DENY", "available memory is too low"
    return "ALLOW", "resources allow a process"


def worker_id_for(
    task_id: str | None, workers: Sequence[tuple[str, str | None, str]]
) -> str | None:
    """Return the running worker that owns ``task_id``.

    Each row is ``(worker_id, current_task, status)``.
    """

    if task_id is None:
        return None
    for worker_id, current_task, status in workers:
        if current_task == task_id and status == "RUNNING":
            return worker_id
    return None


def application_id_for(program: str, catalog: Sequence[tuple[str, str | None]]) -> str | None:
    """Match a program basename to an installed application id."""

    name = Path(program).name
    for app_id, executable in catalog:
        if executable and Path(executable).name == name:
            return app_id
    return None


def _deny_all(
    _tool_id: str,
    _arguments: dict[str, object],
    _grants: Mapping[str, Sequence[str]],
    _environment: str,
) -> tuple[str, str]:
    return "DENY", "process permission was not evaluated"


def _allow() -> tuple[str, str]:
    return "ALLOW", "resources allow a process"
