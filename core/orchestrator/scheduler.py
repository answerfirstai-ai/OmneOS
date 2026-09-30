"""Dependency-aware task scheduling and bounded recovery."""

from __future__ import annotations

import asyncio

from core.agents.lifecycle import AgentLifecycle, AgentState
from core.agents.registry import AgentRegistry
from core.agents.runtime import AgentRuntime
from core.compute.allocation import AllocationDecision
from core.compute.monitor import SystemMonitor
from core.compute.scheduler import ComputeScheduler
from core.events.bus import EventBus
from core.models.registry import ModelRegistry
from core.orchestrator.executor.executor import ExecutionFailure, TaskExecutor
from core.orchestrator.store import TaskStore
from core.orchestrator.task import Task, TaskErrorRecord, TaskStatus
from core.recovery.policy import RecoveryAction, classify_failure, decide_recovery
from core.security.commands import is_destructive


class TaskScheduler:
    """Run a parent task's children when dependencies, agents, and resources allow."""

    def __init__(
        self,
        *,
        store: TaskStore,
        executor: TaskExecutor,
        events: EventBus,
        monitor: SystemMonitor,
        compute: ComputeScheduler,
        agents: AgentRegistry,
        runtime: AgentRuntime,
        lifecycle: AgentLifecycle,
        max_parallel: int,
        models: ModelRegistry | None = None,
        execution_mode: str = "testing",
    ) -> None:
        self._store = store
        self._executor = executor
        self._events = events
        self._monitor = monitor
        self._compute = compute
        self._agents = agents
        self._runtime = runtime
        self._lifecycle = lifecycle
        self._max_parallel = max_parallel
        self._models = models
        self._mode = execution_mode
        self._holds: dict[str, str] = {}
        self._schedule_pause = 0.5
        self._schedule_attempts = 30

    async def execute_parent(self, parent_id: str) -> Task:
        parent = self._store.get(parent_id)
        if parent.status is TaskStatus.QUEUED:
            parent = self._store.transition(parent, TaskStatus.PLANNING)
            parent = self._store.transition(parent, TaskStatus.RUNNING)
            self._events.publish("task.started", task_id=parent.id)
        elif parent.status is TaskStatus.WAITING:
            parent = self._store.transition(parent, TaskStatus.RUNNING)
        elif parent.status is not TaskStatus.RUNNING:
            return parent

        waits = 0
        while True:
            parent = self._store.get(parent.id)
            children = self._store.children(parent.id)
            if not children:
                return self._complete(parent, {"children": []})

            if _unapproved_waiting(children):
                if parent.status is TaskStatus.RUNNING:
                    parent = self._store.transition(parent, TaskStatus.WAITING)
                return self._store.get(parent.id)

            failed = [child for child in children if child.status is TaskStatus.FAILED]
            if failed:
                message = (
                    failed[0].errors[-1].message if failed[0].errors else "a child task failed"
                )
                return self._fail(parent, message, code="child_failed")

            if any(child.status is TaskStatus.CANCELLED for child in children):
                return self._cancel(parent)

            if all(child.status is TaskStatus.COMPLETED for child in children):
                return self._complete(parent, _aggregate(parent, children))

            ready = _ready(children)
            batch, reason, requests = self._choose(ready)
            if not batch:
                if reason == "wait" and waits < self._schedule_attempts:
                    waits += 1
                    self._release_requests(requests)
                    await asyncio.sleep(self._schedule_pause)
                    continue
                self._release_requests(requests)
                return self._fail(
                    parent,
                    "no ready task could be scheduled",
                    code="scheduling_blocked",
                )
            waits = 0
            if len(batch) == 1:
                await self._run_child(batch[0])
            else:
                await asyncio.gather(*(self._run_child(child) for child in batch))

    async def _run_child(self, task: Task) -> Task:
        hold = self._holds.get(task.id)
        if hold is not None:
            self._compute.run(hold)
        try:
            while True:
                task = self._store.get(task.id)
                try:
                    return await self._executor.run(task)
                except ExecutionFailure as exc:
                    task = self._store.get(task.id)
                    self._abandon(task)
                    errors = [
                        *task.errors,
                        TaskErrorRecord(code=exc.code, message=str(exc)),
                    ]
                    if task.status is TaskStatus.RUNNING:
                        task = self._store.transition(task, TaskStatus.RECOVERING, errors=errors)
                    action = decide_recovery(
                        classify_failure(exc.code),
                        retry_count=task.retry_count,
                        retry_limit=task.retry_limit,
                        destructive=_task_is_destructive(task),
                    )
                    updates = _alternate_assignment(self, task, action)
                    if updates is None:
                        action = RecoveryAction.ABORT
                    if action in {
                        RecoveryAction.ABORT,
                        RecoveryAction.ASK_USER,
                        RecoveryAction.REPLAN,
                        RecoveryAction.DIFFERENT_TOOL,
                    }:
                        failed = self._store.transition(
                            task,
                            TaskStatus.FAILED,
                            errors=[
                                *errors,
                                TaskErrorRecord(code="escalated", message=action.value),
                            ],
                        )
                        self._events.publish(
                            "task.failed",
                            task_id=failed.id,
                            agent_id=failed.assigned_agent,
                            payload={"code": exc.code, "recovery": action.value},
                        )
                        return failed
                    if task.retry_count >= task.retry_limit:
                        failed = self._store.transition(
                            task,
                            TaskStatus.FAILED,
                            errors=[
                                *errors,
                                TaskErrorRecord(
                                    code="escalated",
                                    message="retry limit reached",
                                ),
                            ],
                        )
                        self._events.publish(
                            "task.failed",
                            task_id=failed.id,
                            agent_id=failed.assigned_agent,
                            payload={"code": "escalated"},
                        )
                        return failed
                    task = self._store.transition(
                        task,
                        TaskStatus.QUEUED,
                        retry_count=task.retry_count + 1,
                        observations=[],
                        errors=errors,
                        **(updates or {}),
                    )
                    self._events.publish(
                        "task.recovered",
                        task_id=task.id,
                        agent_id=task.assigned_agent,
                        payload={"retry_count": task.retry_count, "recovery": action.value},
                    )
        finally:
            current = self._store.get(task.id)
            self._abandon(current)
            reservation_id = self._holds.pop(task.id, None)
            if reservation_id is not None:
                self._compute.release_id(reservation_id)

    def _select_batch(self, ready: list[Task]) -> list[Task]:
        batch, _reason, _requests = self._choose(ready)
        return batch

    def _choose(self, ready: list[Task]) -> tuple[list[Task], str, list[str]]:
        """Pick a batch. ``wait`` means a later attempt can still admit work."""

        batch: list[Task] = []
        requests: list[str] = []
        waiting = False
        used_agents: dict[str, int] = {}
        snapshot = self._monitor.snapshot()
        for child in ready:
            if len(batch) >= self._max_parallel:
                break
            exclusive = bool(child.metadata.get("exclusive"))
            if exclusive and batch:
                continue
            if batch and any(bool(item.metadata.get("exclusive")) for item in batch):
                continue
            agent_id = child.assigned_agent
            if agent_id:
                decision = self._worker_decision(
                    agent_id,
                    used_agents.get(agent_id, 0),
                    cpu_percent=snapshot.cpu.usage_percent,
                )
                if decision == "WAIT":
                    waiting = True
                    continue
                if decision != "ALLOW":
                    continue
            reservation = self._compute.open(
                child.required_resources,
                owner=child.id,
                kind="task",
                local=True,
                cloud_available=False,
                snapshot=snapshot,
            )
            if reservation.decision is not AllocationDecision.ALLOW:
                requests.append(reservation.id)
                if reservation.decision is AllocationDecision.WAIT:
                    waiting = True
                continue
            self._holds[child.id] = reservation.id
            batch.append(child)
            if agent_id:
                used_agents[agent_id] = used_agents.get(agent_id, 0) + 1
            if exclusive:
                break
        if batch:
            return batch, "ready", requests
        if waiting:
            return [], "wait", requests
        return [], "blocked", requests

    def _release_requests(self, reservation_ids: list[str]) -> None:
        for reservation_id in reservation_ids:
            self._compute.release_id(reservation_id)

    def _worker_limit(self, agent_id: str) -> int:
        try:
            return self._agents.get(agent_id).max_workers
        except KeyError:
            return 1

    def _worker_decision(
        self, agent_id: str, already_batched: int, *, cpu_percent: float | None
    ) -> str:
        limit = self._worker_limit(agent_id)
        if limit <= 1 and not self._agent_free(agent_id):
            return "WAIT" if self._agent_transient(agent_id) else "DENY"
        try:
            requested = self._agents.get(agent_id).resources.ram_mb
        except KeyError:
            requested = 0
        return self._runtime.pool.can_start(
            agent_id=agent_id,
            max_workers=limit,
            requested_ram_mb=requested,
            cpu_percent=cpu_percent,
            extra_active=already_batched,
        )

    def _agent_free(self, agent_id: str) -> bool:
        try:
            state = self._lifecycle.state(agent_id)
        except KeyError:
            return True
        return state in {AgentState.AVAILABLE, AgentState.UNLOADED}

    def _agent_transient(self, agent_id: str) -> bool:
        try:
            state = self._lifecycle.state(agent_id)
        except KeyError:
            return False
        return state in {
            AgentState.RESERVED,
            AgentState.INITIALIZING,
            AgentState.RUNNING,
            AgentState.VERIFYING,
            AgentState.RECOVERING,
        }

    def _abandon(self, task: Task) -> None:
        agent_id = task.assigned_agent
        if agent_id is None:
            return
        try:
            manifest = self._agents.get(agent_id)
            state = self._lifecycle.state(agent_id)
        except KeyError:
            return
        if state is AgentState.RUNNING:
            self._runtime.fail(manifest, retry=False)

    def _complete(self, parent: Task, result: dict[str, object]) -> Task:
        parent = self._store.transition(parent, TaskStatus.VERIFYING, result=result)
        parent = self._store.transition(parent, TaskStatus.COMPLETED, result=result)
        self._events.publish("task.completed", task_id=parent.id)
        return parent

    def _fail(self, parent: Task, message: str, *, code: str) -> Task:
        errors = [*parent.errors, TaskErrorRecord(code=code, message=message)]
        if parent.status in {TaskStatus.RUNNING, TaskStatus.WAITING}:
            parent = self._store.transition(parent, TaskStatus.FAILED, errors=errors)
        self._events.publish("task.failed", task_id=parent.id, payload={"code": code})
        return self._store.get(parent.id)

    def _cancel(self, parent: Task) -> Task:
        if parent.status in {TaskStatus.RUNNING, TaskStatus.WAITING, TaskStatus.QUEUED}:
            if parent.status is TaskStatus.QUEUED:
                parent = self._store.transition(parent, TaskStatus.PLANNING)
            parent = self._store.transition(parent, TaskStatus.CANCELLED)
        self._events.publish("task.cancelled", task_id=parent.id)
        return self._store.get(parent.id)


def _alternate_assignment(
    scheduler: TaskScheduler, task: Task, action: RecoveryAction
) -> dict[str, str] | None:
    """Return a field update, an empty update, or None when no alternate exists."""

    if action is RecoveryAction.DIFFERENT_MODEL:
        alternate = _other_model(scheduler, task)
        if alternate is None:
            return None
        return {"assigned_model": alternate}
    if action is RecoveryAction.DIFFERENT_AGENT:
        alternate = _other_agent(scheduler, task)
        if alternate is None:
            return None
        return {"assigned_agent": alternate}
    return {}


def _other_model(scheduler: TaskScheduler, task: Task) -> str | None:
    models = scheduler._models
    if models is None or task.assigned_model is None:
        return None
    try:
        current = models.get(task.assigned_model)
    except KeyError:
        return None
    required = set(current.capabilities)
    candidates = [
        model
        for model in models.enabled()
        if model.id != current.id and required <= set(model.capabilities)
    ]
    if scheduler._mode == "production":
        candidates = [model for model in candidates if model.provider != "mock"]
    if scheduler._mode in {"offline", "local"}:
        candidates = [model for model in candidates if model.local]
    if not candidates:
        return None
    candidates.sort(key=lambda model: (model.priority, model.id))
    return candidates[0].id


def _other_agent(scheduler: TaskScheduler, task: Task) -> str | None:
    current = task.assigned_agent
    if current is None:
        return None
    try:
        manifest = scheduler._agents.get(current)
    except KeyError:
        return None
    for capability in manifest.capabilities:
        for candidate in scheduler._agents.by_capability(capability):
            if candidate.id != current and scheduler._agents.is_enabled(candidate.id):
                return candidate.id
    return None


def _task_is_destructive(task: Task) -> bool:
    for call in task.calls:
        if call.tool_id in {"filesystem.write", "git.commit", "process.stop", "process.restart"}:
            return True
        if call.tool_id == "terminal.execute":
            return is_destructive(call.arguments.get("argv"))
    return False


def _unapproved_waiting(children: list[Task]) -> bool:
    for child in children:
        if child.status is not TaskStatus.WAITING:
            continue
        pending = child.pending_confirmation or {}
        if pending.get("approved") is not True:
            return True
    return False


def _ready(children: list[Task]) -> list[Task]:
    by_id = {child.id: child for child in children}
    ready: list[Task] = []
    for child in children:
        approved = (child.pending_confirmation or {}).get("approved") is True
        queued = child.status is TaskStatus.QUEUED
        confirmed = child.status is TaskStatus.WAITING and approved
        if not queued and not confirmed:
            continue
        dependencies_done = all(
            dependency in by_id and by_id[dependency].status is TaskStatus.COMPLETED
            for dependency in child.dependencies
        )
        if dependencies_done:
            ready.append(child)
    return ready


def _aggregate(parent: Task, children: list[Task]) -> dict[str, object]:
    by_id = {child.id: child for child in children}
    ordered: list[dict[str, object]] = []
    for step in parent.steps:
        child = by_id.get(step.id)
        if child is None:
            continue
        ordered.append(
            {
                "id": child.id,
                "key": child.metadata.get("key"),
                "status": child.status.value,
                "result": child.result,
            }
        )
    return {"children": ordered}
