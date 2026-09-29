"""The JARVIS execution service."""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from core.agents.communication import AgentMailbox
from core.agents.lifecycle import AgentLifecycle, AgentState
from core.agents.registry import AgentRegistry
from core.compute.model_cache import ModelCache
from core.compute.monitor import ResourceSnapshot, SystemMonitor
from core.events.bus import Event, EventBus
from core.memory.store import MemoryStore
from core.models.registry import ModelRegistry
from core.models.router import ModelRouter, RoutingError
from core.orchestrator.planner.planner import PlanNode, plan_objective
from core.orchestrator.scheduler import TaskScheduler
from core.orchestrator.store import TaskStore
from core.orchestrator.task import Task, TaskErrorRecord, TaskStatus, TaskStep
from core.voice.service import VoiceService

_MODEL_CAPABILITY = {
    "conversation": "reasoning",
    "software_development": "coding",
    "code_analysis": "coding",
    "testing": "coding",
    "debugging": "coding",
    "source_collection": "planning",
    "summarization": "planning",
    "research": "planning",
    "browser_navigation": "tool_use",
    "page_extraction": "tool_use",
    "system_inspection": "tool_use",
    "process_inspection": "tool_use",
}

_CANCELLABLE = {
    TaskStatus.QUEUED,
    TaskStatus.PLANNING,
    TaskStatus.WAITING,
    TaskStatus.RUNNING,
    TaskStatus.PAUSED,
    TaskStatus.RECOVERING,
    TaskStatus.FAILED,
}


class Jarvis:
    """Plan an objective and run it through the scheduler."""

    def __init__(
        self,
        *,
        store: TaskStore,
        scheduler: TaskScheduler,
        events: EventBus,
        agents: AgentRegistry,
        lifecycle: AgentLifecycle,
        models: ModelRegistry,
        router: ModelRouter,
        monitor: SystemMonitor,
        voice: VoiceService,
        memory: MemoryStore,
        cache: ModelCache,
        mailbox: AgentMailbox,
        retry_limit: int,
    ) -> None:
        self._store = store
        self._scheduler = scheduler
        self._events = events
        self._agents = agents
        self._lifecycle = lifecycle
        self._models = models
        self._router = router
        self._monitor = monitor
        self._voice = voice
        self.memory = memory
        self.cache = cache
        self.mailbox = mailbox
        self._retry_limit = retry_limit
        self._lock = threading.Lock()

    def execute_sync(self, objective: str) -> Task:
        with self._lock:
            return asyncio.run(self.execute(objective))

    def confirm_sync(self, task_id: str, *, approved: bool) -> Task:
        with self._lock:
            return asyncio.run(self.confirm(task_id, approved=approved))

    def cancel(self, task_id: str) -> Task:
        with self._lock:
            return self._cancel(task_id)

    async def execute(self, objective: str) -> Task:
        text = " ".join(objective.split())
        if not text:
            raise ValueError("objective must not be empty")
        parent, children = self._materialize(text)
        self._store.save(parent)
        for child in children:
            self._store.save(child)
        return await self._scheduler.execute_parent(parent.id)

    async def confirm(self, task_id: str, *, approved: bool) -> Task:
        parent, target = self._confirmation_target(task_id)
        if not approved:
            denied = self._store.transition(
                target,
                TaskStatus.FAILED,
                errors=[
                    *target.errors,
                    TaskErrorRecord(code="confirmation_denied", message="confirmation was denied"),
                ],
                pending_confirmation=None,
            )
            self._events.publish(
                "task.failed",
                task_id=denied.id,
                payload={"code": "confirmation_denied"},
            )
            if parent.status is TaskStatus.WAITING:
                parent = self._store.transition(
                    parent,
                    TaskStatus.FAILED,
                    errors=[
                        *parent.errors,
                        TaskErrorRecord(
                            code="confirmation_denied",
                            message="confirmation was denied",
                        ),
                    ],
                )
            return self._store.get(parent.id)
        pending = dict(target.pending_confirmation or {})
        pending["approved"] = True
        self._store.save(
            target.model_copy(
                update={"pending_confirmation": pending, "updated_at": datetime.now(UTC)}
            )
        )
        return await self._scheduler.execute_parent(parent.id)

    def list_tasks(self) -> list[Task]:
        return self._store.list_tasks()

    def get_task(self, task_id: str) -> Task:
        return self._store.get(task_id)

    def list_events(self, *, after: str | None = None) -> list[Event]:
        return self._events.list_events(after=after)

    def agent_views(self) -> list[dict[str, object]]:
        views: list[dict[str, object]] = []
        for manifest in self._agents.all():
            try:
                state: AgentState | None = self._lifecycle.state(manifest.id)
            except KeyError:
                state = None
            views.append(
                {
                    "id": manifest.id,
                    "name": manifest.name,
                    "enabled": self._agents.is_enabled(manifest.id),
                    "state": state.value if state is not None else "untracked",
                    "capabilities": list(manifest.capabilities),
                }
            )
        return views

    def model_views(self) -> list[dict[str, object]]:
        return [
            {
                "id": model.id,
                "provider": model.provider,
                "model_name": model.model_name,
                "local": model.local,
                "priority": model.priority,
                "capabilities": list(model.capabilities),
                "cost_input": model.cost_input,
                "cost_output": model.cost_output,
                "latency": model.latency,
            }
            for model in self._models.enabled()
        ]

    def compute_status(self) -> ResourceSnapshot:
        return self._monitor.snapshot()

    def voice_status(self) -> dict[str, object]:
        return self._voice.status()

    def _materialize(self, objective: str) -> tuple[Task, list[Task]]:
        nodes = plan_objective(objective)
        now = datetime.now(UTC)
        parent_id = str(uuid4())
        snapshot = self._monitor.snapshot()
        key_to_id = {node.key: str(uuid4()) for node in nodes}
        children: list[Task] = []
        steps: list[TaskStep] = []
        for node in nodes:
            child = self._child(node, parent_id, key_to_id, now, snapshot)
            children.append(child)
            steps.append(
                TaskStep(
                    id=child.id,
                    objective=child.objective,
                    status=TaskStatus.QUEUED,
                    dependencies=list(child.dependencies),
                    assigned_agent=child.assigned_agent,
                    required_tools=list(child.required_tools),
                )
            )
        parent = Task(
            id=parent_id,
            objective=objective,
            created_at=now,
            updated_at=now,
            retry_limit=self._retry_limit,
            steps=steps,
            metadata={"role": "parent"},
        )
        return parent, children

    def _child(
        self,
        node: PlanNode,
        parent_id: str,
        key_to_id: dict[str, str],
        now: datetime,
        snapshot: ResourceSnapshot,
    ) -> Task:
        matches = self._agents.by_capability(node.capability)
        agent = matches[0] if matches else None
        model_id = self._select_model(node.capability, snapshot)
        return Task(
            id=key_to_id[node.key],
            objective=node.objective,
            created_at=now,
            updated_at=now,
            parent_task=parent_id,
            dependencies=[key_to_id[key] for key in node.depends_on],
            assigned_agent=agent.id if agent is not None else None,
            assigned_model=model_id,
            required_tools=list(node.required_tools),
            required_resources=node.resources,
            calls=list(node.calls),
            retry_limit=self._retry_limit,
            metadata={"role": "child", "key": node.key, "exclusive": node.exclusive},
        )

    def _select_model(self, capability: str, snapshot: ResourceSnapshot) -> str | None:
        if not self._models.enabled():
            return None
        required = _MODEL_CAPABILITY.get(capability, "reasoning")
        try:
            route = self._router.select([required], snapshot)
        except RoutingError:
            return None
        return route.model.id

    def _confirmation_target(self, task_id: str) -> tuple[Task, Task]:
        task = self._store.get(task_id)
        parent = self._store.get(task.parent_task) if task.parent_task else task
        if task.status is TaskStatus.WAITING and task.pending_confirmation:
            return parent, task
        waiting = [
            child
            for child in self._store.children(parent.id)
            if child.status is TaskStatus.WAITING and child.pending_confirmation
        ]
        if not waiting:
            raise ValueError("task is not waiting for confirmation")
        return parent, waiting[0]

    def _cancel(self, task_id: str) -> Task:
        task = self._store.get(task_id)
        parent = self._store.get(task.parent_task) if task.parent_task else task
        if parent.status in {TaskStatus.COMPLETED, TaskStatus.CANCELLED}:
            raise ValueError("task cannot be cancelled")
        for child in self._store.children(parent.id):
            if child.status in _CANCELLABLE:
                self._cancel_one(child)
        if parent.status in _CANCELLABLE:
            return self._cancel_one(parent)
        return self._store.get(parent.id)

    def _cancel_one(self, task: Task) -> Task:
        if task.status not in _CANCELLABLE:
            if task.status in {TaskStatus.COMPLETED, TaskStatus.CANCELLED}:
                return task
            raise ValueError(f"task {task.id} cannot be cancelled from {task.status.value}")
        current = self._store.transition(task, TaskStatus.CANCELLED)
        self._events.publish("task.cancelled", task_id=current.id)
        return current


def task_document(task: Task) -> dict[str, Any]:
    """Serialize a task for the HTTP API."""

    return task.model_dump(mode="json")
