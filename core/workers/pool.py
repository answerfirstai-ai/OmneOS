"""In-memory worker instances.

A worker is a record, not an operating-system process. The pool reuses an
idle or paused instance when one belongs to the same agent, and it refuses a
new instance when the agent slot count, CPU, or declared memory budget says
no.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.compute.allocation import AllocationDecision
from core.compute.manager import ResourceManager
from core.compute.requirements import ResourceRequirements
from core.security.boundary import resource_denial
from core.workers.lifecycle import (
    ACTIVE_STATES,
    OCCUPIED_STATES,
    REUSABLE_STATES,
    TRANSITIONS,
    InvalidWorkerTransition,
    WorkerState,
)

WorkerHook = Callable[[str, "Worker"], None]


class Worker(BaseModel):
    """One running instance of an agent definition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    worker_id: str
    agent_id: str
    lifecycle: WorkerState
    status: str
    current_task: str | None = None
    current_mission: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    model: str | None = None
    tools: list[str] = Field(default_factory=list)
    permissions: dict[str, list[str]] = Field(default_factory=dict)
    resources: ResourceRequirements = Field(default_factory=ResourceRequirements)
    context: str = ""
    trace_id: str | None = None
    started_at: datetime
    last_activity: datetime

    @model_validator(mode="after")
    def _status_matches_lifecycle(self) -> Worker:
        if self.status != self.lifecycle.value:
            raise ValueError("worker status must match its lifecycle")
        return self


class WorkerLimit(Exception):
    """Raised when an agent has no remaining worker slots or resources."""

    def __init__(self, message: str, *, reason: str = "limit") -> None:
        super().__init__(message)
        self.reason = reason


def admit_worker(
    *,
    active: int,
    max_workers: int,
    cpu_percent: float | None,
    cpu_limit: float = 95.0,
    allocated_ram_mb: int = 0,
    requested_ram_mb: int = 0,
    ram_limit_mb: int | None = None,
) -> str:
    """Decide whether a worker may start.

    Unknown CPU telemetry is not treated as capacity. A full worker slot is a
    denial. A request larger than the memory budget is a denial. A budget that
    is only full because other workers hold it waits. High measured CPU waits
    instead of starting another worker.
    """

    if requested_ram_mb < 0 or (ram_limit_mb is not None and requested_ram_mb > ram_limit_mb):
        return "DENY"
    if active >= max_workers:
        return "DENY"
    if ram_limit_mb is not None and allocated_ram_mb + requested_ram_mb > ram_limit_mb:
        return "WAIT"
    if cpu_percent is not None and cpu_percent >= cpu_limit:
        return "WAIT"
    return "ALLOW"


class WorkerPool:
    """Track workers. Creation stays in this process and stops at the limits."""

    def __init__(
        self,
        *,
        hook: WorkerHook | None = None,
        ram_limit_mb: int | None = None,
        resources: ResourceManager | None = None,
    ) -> None:
        self._workers: dict[str, Worker] = {}
        self._by_agent: dict[str, list[str]] = {}
        self._hook = hook
        self._ram_limit = ram_limit_mb
        self._resources = resources
        self._reservations: dict[str, str] = {}
        self._log: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def bind(self, hook: WorkerHook) -> None:
        with self._lock:
            self._hook = hook

    def events(self) -> list[tuple[str, str]]:
        with self._lock:
            return list(self._log)

    def active(self, agent_id: str) -> int:
        with self._lock:
            return self._active(agent_id)

    def can_start(
        self,
        *,
        agent_id: str,
        max_workers: int,
        requested_ram_mb: int,
        cpu_percent: float | None,
        extra_active: int = 0,
    ) -> str:
        with self._lock:
            return self._admission(
                agent_id,
                max_workers=max_workers,
                requested_ram_mb=requested_ram_mb,
                cpu_percent=cpu_percent,
                extra_active=extra_active,
            )

    def start(
        self,
        *,
        agent_id: str,
        max_workers: int,
        task_id: str | None,
        mission_id: str | None,
        model_id: str | None,
        trace_id: str | None,
        capabilities: list[str] | None = None,
        tools: list[str] | None = None,
        permissions: dict[str, list[str]] | None = None,
        resources: ResourceRequirements | None = None,
        context: str = "",
        cpu_percent: float | None = None,
    ) -> Worker:
        denial = resource_denial(
            "WORKER",
            ram_mb=(resources or ResourceRequirements()).ram_mb,
            cpu_threads=(resources or ResourceRequirements()).cpu_threads,
        )
        if denial is not None:
            raise WorkerLimit(f"{agent_id} is waiting for resources", reason="resources")
        assignment = _Assignment(
            agent_id=agent_id,
            task_id=task_id,
            mission_id=mission_id,
            model_id=model_id,
            trace_id=trace_id,
            capabilities=list(capabilities or []),
            tools=list(tools or []),
            permissions={key: list(value) for key, value in (permissions or {}).items()},
            resources=resources or ResourceRequirements(),
            context=context,
        )
        with self._lock:
            failure = self._admission_failure(agent_id, assignment, max_workers, cpu_percent)
            fresh_needed = failure is None and self._reusable(agent_id) is None
        if failure is not None:
            raise failure
        reservation_id: str | None = None
        if fresh_needed:
            reservation_id = self._reserve_new(assignment)
        with self._lock:
            failure = self._admission_failure(agent_id, assignment, max_workers, cpu_percent)
            if failure is not None:
                kept = None
                worker = None
                pending: list[tuple[str, Worker]] = []
            else:
                reusable = self._reusable(agent_id)
                if reusable is None:
                    worker, pending = self._create(assignment)
                    if reservation_id is not None:
                        self._reservations[worker.worker_id] = reservation_id
                    kept = reservation_id
                else:
                    worker, pending = self._reuse(reusable, assignment)
                    kept = None
            hook = self._hook
        if failure is not None:
            self._drop(reservation_id)
            raise failure
        if kept is None:
            self._drop(reservation_id)
        elif self._resources is not None:
            self._resources.run(kept)
        self._flush(hook, pending)
        assert worker is not None
        return worker

    def _admission_failure(
        self,
        agent_id: str,
        assignment: _Assignment,
        max_workers: int,
        cpu_percent: float | None,
    ) -> WorkerLimit | None:
        decision = self._admission(
            agent_id,
            max_workers=max_workers,
            requested_ram_mb=assignment.resources.ram_mb,
            cpu_percent=cpu_percent,
        )
        if decision == "ALLOW":
            return None
        waiting = decision == "WAIT"
        memory = waiting and not self._ram_fits(assignment)
        reason = "resources" if memory else "cpu" if waiting else "limit"
        message = (
            f"{agent_id} is waiting for resources"
            if waiting
            else f"{agent_id} already has {max_workers} workers"
        )
        return WorkerLimit(message, reason=reason)

    def _reserve_new(self, assignment: _Assignment) -> str | None:
        if self._resources is None:
            return None
        reservation = self._resources.request(
            assignment.resources,
            owner=assignment.agent_id,
            kind="worker",
            local=True,
            cloud_available=False,
        )
        if reservation.decision is not AllocationDecision.ALLOW:
            raise WorkerLimit(
                f"{assignment.agent_id} is waiting for resources",
                reason="resources",
            )
        return reservation.id

    def _drop(self, reservation_id: str | None) -> None:
        if reservation_id is None or self._resources is None:
            return
        current = self._resources.get(reservation_id)
        if current.state.value == "RELEASE":
            return
        self._resources.release(reservation_id)

    def complete(self, agent_id: str) -> Worker | None:
        return self._close_running(agent_id, WorkerState.IDLE, "worker.idle", "worker.completed")

    def pause_running(self, agent_id: str) -> Worker | None:
        return self._close_running(agent_id, WorkerState.PAUSED, "worker.paused")

    def fail(self, agent_id: str) -> Worker | None:
        return self._close_running(agent_id, WorkerState.FAILED, "worker.failed")

    def cancel(self, worker_id: str) -> Worker:
        with self._lock:
            worker = self._get(worker_id)
            if worker.lifecycle not in {
                WorkerState.RUNNING,
                WorkerState.PAUSED,
                WorkerState.SPAWNED,
            }:
                raise InvalidWorkerTransition(worker_id, worker.lifecycle, WorkerState.IDLE)
            updated = self._move(
                worker,
                WorkerState.IDLE,
                current_task=None,
                current_mission=None,
            )
            pending = [("worker.cancelled", updated)]
            hook = self._hook
        self._flush(hook, pending)
        return updated

    def resume(self, worker_id: str) -> Worker:
        with self._lock:
            worker = self._get(worker_id)
            updated = self._move(worker, WorkerState.RUNNING)
            pending = [("worker.resumed", updated), ("worker.started", updated)]
            hook = self._hook
        self._flush(hook, pending)
        return updated

    def terminate(self, worker_id: str) -> Worker:
        with self._lock:
            worker = self._get(worker_id)
            updated = self._move(worker, WorkerState.TERMINATED, current_task=None)
            reservation_id = self._reservations.pop(worker_id, None)
            pending = [("worker.terminated", updated)]
            hook = self._hook
        self._drop(reservation_id)
        self._flush(hook, pending)
        return updated

    def terminate_idle(self, agent_id: str) -> list[Worker]:
        return self._terminate_where(agent_id, WorkerState.IDLE)

    def terminate_failed(self, agent_id: str) -> list[Worker]:
        return self._terminate_where(agent_id, WorkerState.FAILED)

    def list_workers(self) -> list[Worker]:
        with self._lock:
            return list(self._workers.values())

    def get(self, worker_id: str) -> Worker:
        with self._lock:
            return self._get(worker_id)

    def _close_running(
        self, agent_id: str, proposed: WorkerState, *event_types: str
    ) -> Worker | None:
        with self._lock:
            worker_id = self._newest(agent_id, WorkerState.RUNNING)
            if worker_id is None:
                return None
            updated = self._move(self._workers[worker_id], proposed)
            pending = [(event_type, updated) for event_type in event_types]
            hook = self._hook
        self._flush(hook, pending)
        return updated

    def _terminate_where(self, agent_id: str, state: WorkerState) -> list[Worker]:
        with self._lock:
            found = [
                self._move(self._workers[worker_id], WorkerState.TERMINATED, current_task=None)
                for worker_id in self._by_agent.get(agent_id, [])
                if self._workers[worker_id].lifecycle is state
            ]
            released = [self._reservations.pop(worker.worker_id, None) for worker in found]
            pending = [("worker.terminated", worker) for worker in found]
            hook = self._hook
        for reservation_id in released:
            self._drop(reservation_id)
        self._flush(hook, pending)
        return found

    def _admission(
        self,
        agent_id: str,
        *,
        max_workers: int,
        requested_ram_mb: int,
        cpu_percent: float | None,
        extra_active: int = 0,
    ) -> str:
        reusable = self._reusable(agent_id) is not None
        slots = self._active(agent_id) if reusable else self._slots(agent_id)
        return admit_worker(
            active=slots + extra_active,
            max_workers=max_workers,
            cpu_percent=cpu_percent,
            allocated_ram_mb=0 if reusable else self._held_ram(),
            requested_ram_mb=0 if reusable else requested_ram_mb,
            ram_limit_mb=self._ram_limit,
        )

    def _ram_fits(self, assignment: _Assignment) -> bool:
        if self._reusable(assignment.agent_id) is not None:
            return True
        if self._ram_limit is None:
            return True
        return self._held_ram() + assignment.resources.ram_mb <= self._ram_limit

    def _create(self, assignment: _Assignment) -> tuple[Worker, list[tuple[str, Worker]]]:
        now = datetime.now(UTC)
        worker = Worker(
            worker_id=str(uuid4()),
            agent_id=assignment.agent_id,
            lifecycle=WorkerState.DISCOVERED,
            status=WorkerState.DISCOVERED.value,
            capabilities=assignment.capabilities,
            model=assignment.model_id,
            tools=assignment.tools,
            permissions=assignment.permissions,
            resources=assignment.resources,
            context=assignment.context,
            current_task=assignment.task_id,
            current_mission=assignment.mission_id,
            trace_id=assignment.trace_id,
            started_at=now,
            last_activity=now,
        )
        self._workers[worker.worker_id] = worker
        self._by_agent.setdefault(assignment.agent_id, []).append(worker.worker_id)
        pending = [("worker.discovered", worker)]
        for state, event_type in (
            (WorkerState.AVAILABLE, "worker.available"),
            (WorkerState.SPAWNED, "worker.spawned"),
            (WorkerState.RUNNING, "worker.started"),
        ):
            worker = self._move(worker, state)
            pending.append((event_type, worker))
        return worker, pending

    def _reuse(
        self, worker: Worker, assignment: _Assignment
    ) -> tuple[Worker, list[tuple[str, Worker]]]:
        fields = assignment.fields()
        pending: list[tuple[str, Worker]] = []
        if worker.lifecycle is WorkerState.PAUSED:
            worker = self._move(worker, WorkerState.RUNNING, **fields)
            pending.append(("worker.resumed", worker))
            pending.append(("worker.started", worker))
            return worker, pending
        pending.append(("worker.reused", worker))
        worker = self._move(worker, WorkerState.SPAWNED, **fields)
        pending.append(("worker.spawned", worker))
        worker = self._move(worker, WorkerState.RUNNING)
        pending.append(("worker.started", worker))
        return worker, pending

    def _move(self, worker: Worker, proposed: WorkerState, **updates: object) -> Worker:
        if proposed not in TRANSITIONS[worker.lifecycle]:
            raise InvalidWorkerTransition(worker.worker_id, worker.lifecycle, proposed)
        updated = worker.model_copy(
            update={
                "lifecycle": proposed,
                "status": proposed.value,
                "last_activity": datetime.now(UTC),
                **updates,
            }
        )
        self._workers[worker.worker_id] = updated
        return updated

    def _flush(self, hook: WorkerHook | None, pending: list[tuple[str, Worker]]) -> None:
        with self._lock:
            self._log.extend((event_type, worker.worker_id) for event_type, worker in pending)
        if hook is None:
            return
        for event_type, worker in pending:
            hook(event_type, worker)

    def _active(self, agent_id: str) -> int:
        return sum(
            1
            for worker_id in self._by_agent.get(agent_id, [])
            if self._workers[worker_id].lifecycle in ACTIVE_STATES
        )

    def _slots(self, agent_id: str) -> int:
        return sum(
            1
            for worker_id in self._by_agent.get(agent_id, [])
            if self._workers[worker_id].lifecycle in OCCUPIED_STATES
        )

    def _held_ram(self) -> int:
        return sum(
            worker.resources.ram_mb
            for worker in self._workers.values()
            if worker.lifecycle in OCCUPIED_STATES
        )

    def _reusable(self, agent_id: str) -> Worker | None:
        for worker_id in self._by_agent.get(agent_id, []):
            worker = self._workers[worker_id]
            if worker.lifecycle in REUSABLE_STATES:
                return worker
        return None

    def _newest(self, agent_id: str, state: WorkerState) -> str | None:
        found = [
            worker_id
            for worker_id in self._by_agent.get(agent_id, [])
            if self._workers[worker_id].lifecycle is state
        ]
        if not found:
            return None
        return found[-1]

    def _get(self, worker_id: str) -> Worker:
        try:
            return self._workers[worker_id]
        except KeyError as exc:
            raise KeyError(f"unknown worker: {worker_id}") from exc


class _Assignment:
    def __init__(
        self,
        *,
        agent_id: str,
        task_id: str | None,
        mission_id: str | None,
        model_id: str | None,
        trace_id: str | None,
        capabilities: list[str],
        tools: list[str],
        permissions: dict[str, list[str]],
        resources: ResourceRequirements,
        context: str,
    ) -> None:
        self.agent_id = agent_id
        self.task_id = task_id
        self.mission_id = mission_id
        self.model_id = model_id
        self.trace_id = trace_id
        self.capabilities = capabilities
        self.tools = tools
        self.permissions = permissions
        self.resources = resources
        self.context = context

    def fields(self) -> dict[str, object]:
        return {
            "current_task": self.task_id,
            "current_mission": self.mission_id,
            "model": self.model_id,
            "trace_id": self.trace_id,
            "capabilities": self.capabilities,
            "tools": self.tools,
            "permissions": self.permissions,
            "resources": self.resources,
            "context": self.context,
        }
