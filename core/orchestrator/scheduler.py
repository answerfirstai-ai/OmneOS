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
from core.orchestrator.executor.executor import ExecutionFailure, TaskExecutor
from core.orchestrator.store import TaskStore
from core.orchestrator.task import Task, TaskErrorRecord, TaskStatus


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
            batch = self._select_batch(ready)
            if not batch:
                return self._fail(
                    parent,
                    "no ready task could be scheduled",
                    code="scheduling_blocked",
                )
            if len(batch) == 1:
                await self._run_child(batch[0])
            else:
                await asyncio.gather(*(self._run_child(child) for child in batch))

    async def _run_child(self, task: Task) -> Task:
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
                    )
                    self._events.publish(
                        "task.recovered",
                        task_id=task.id,
                        agent_id=task.assigned_agent,
                        payload={"retry_count": task.retry_count},
                    )
        finally:
            current = self._store.get(task.id)
            self._abandon(current)
            self._compute.release(current.required_resources)

    def _select_batch(self, ready: list[Task]) -> list[Task]:
        batch: list[Task] = []
        used_agents: set[str] = set()
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
            if agent_id and (agent_id in used_agents or not self._agent_free(agent_id)):
                continue
            decision = self._compute.request(
                child.required_resources,
                local=True,
                cloud_available=False,
                snapshot=snapshot,
            )
            if decision is not AllocationDecision.ALLOW:
                continue
            batch.append(child)
            if agent_id:
                used_agents.add(agent_id)
            if exclusive:
                break
        return batch

    def _agent_free(self, agent_id: str) -> bool:
        try:
            state = self._lifecycle.state(agent_id)
        except KeyError:
            return True
        return state in {AgentState.AVAILABLE, AgentState.UNLOADED}

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
