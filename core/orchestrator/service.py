"""The OMNE execution service."""

from __future__ import annotations

import asyncio
import contextlib
import platform
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.agents.communication import AgentMailbox
from core.agents.lifecycle import AgentLifecycle, AgentState
from core.agents.registry import AgentRegistry
from core.agents.runtime import AgentRuntime
from core.capabilities.registry import CapabilityRegistry
from core.compute.model_cache import ModelCache
from core.compute.monitor import ResourceSnapshot, SystemMonitor
from core.context.builder import build_context
from core.decision.engine import DecisionEngine, ExecutionDecision
from core.events.bus import Event, EventBus
from core.events.replay import replay_events
from core.graph.model import build_graph
from core.intent.engine import Intent, IntentEngine
from core.memory.retrieval import SCOPES, AccessGrant, MemoryAccessError
from core.memory.store import MemoryStore
from core.metrics import ReliabilityLedger
from core.mission.model import Mission, MissionError, MissionStatus, mission_event
from core.mission.store import MissionStore
from core.models.lifecycle import ModelLifecycle, ModelLifecycleState
from core.models.registry import ModelRegistry
from core.models.router import ModelRouter, RoutingError
from core.orchestrator.planner.planner import PlanNode, plan_objective
from core.orchestrator.scheduler import TaskScheduler
from core.orchestrator.store import TaskStore
from core.orchestrator.task import Task, TaskErrorRecord, TaskStatus, TaskStep
from core.project.context import ProjectContext
from core.trace import new_trace_id, set_mission_id
from core.verify.verifier import VerificationResult, verify_observations
from core.voice.service import VoiceService
from core.world.state import WorldState, WorldStateService
from omne.display.select import diagnose_display

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


class OMNE:
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
        missions: MissionStore,
        world: WorldStateService,
        runtime: AgentRuntime,
        capabilities: CapabilityRegistry,
        model_lifecycle: ModelLifecycle,
        project: ProjectContext,
        execution_mode: str,
        environment: str,
        context_item_limit: int,
        context_char_limit: int,
        memory_retrieve_limit: int,
        workspace_root: Path,
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
        self._missions = missions
        self._world = world
        self._runtime = runtime
        self._capabilities = capabilities
        self._model_lifecycle = model_lifecycle
        self._project = project
        self._mode = execution_mode
        self._environment = environment
        self._context_items = context_item_limit
        self._context_chars = context_char_limit
        self._memory_limit = memory_retrieve_limit
        self._workspace = workspace_root
        self._intent = IntentEngine()
        self._decision = DecisionEngine()
        self._metrics = ReliabilityLedger()
        self._questions: list[dict[str, object]] = []
        self._verifications: dict[str, VerificationResult] = {}
        self._lock = threading.Lock()
        self._events.subscribe(self._on_event)
        self._world.bind(self.build_world)

    def execute_sync(self, objective: str, *, dry_run: bool = False) -> Task:
        with self._lock:
            return asyncio.run(self.execute(objective, dry_run=dry_run))

    def confirm_sync(self, task_id: str, *, approved: bool) -> Task:
        with self._lock:
            return asyncio.run(self.confirm(task_id, approved=approved))

    def cancel(self, task_id: str) -> Task:
        with self._lock:
            return self._cancel(task_id)

    async def execute(self, objective: str, *, dry_run: bool = False) -> Task:
        text = " ".join(objective.split())
        if not text:
            raise ValueError("objective must not be empty")
        trace_id = new_trace_id()
        intent = self._intent.interpret(text, allow_model=False)
        decision = self._decision.decide(
            intent,
            mode=self._mode,
            local_available=self._local_available(),
            cloud_available=self._cloud_available(),
            cpu_wait=False,
            trace_id=trace_id,
        )
        now = datetime.now(UTC)
        mission = Mission(
            id=str(uuid4()),
            objective=text,
            created_at=now,
            updated_at=now,
            trace_id=trace_id,
            objectives=[text],
            metadata={
                "intent": intent.model_dump(mode="json"),
                "decision": decision.model_dump(mode="json"),
            },
        )
        self._missions.save(mission)
        set_mission_id(mission.id)
        self._events.publish("mission.created", mission_id=mission.id, trace_id=trace_id)
        mission = self._advance_mission(mission, MissionStatus.ANALYZING)
        self._publish_decision(mission, decision)
        if intent.ambiguous or decision.decision == "ASK_USER":
            return self._ask(mission, intent, now)
        if decision.decision == "DENY":
            return self._deny(mission, decision, now)
        if dry_run:
            return self._dry_run(mission, text, decision, now)
        world = self._world.current()
        mission = self._advance_mission(mission, MissionStatus.PLANNING)
        parent, children = self._materialize(
            text,
            extras={
                "trace_id": trace_id,
                "mission_id": mission.id,
                "world_revision": world.revision,
                "decision": decision.decision,
            },
        )
        self._store.save(parent)
        for child in children:
            self._store.save(child)
        mission = self._advance_mission(mission, MissionStatus.READY, task_id=parent.id)
        mission = self._advance_mission(mission, MissionStatus.RUNNING)
        result = await self._scheduler.execute_parent(parent.id)
        return self._close_mission(mission, result)

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

    def desktop_view(self) -> dict[str, object]:
        """Return the panels the shell paints, without a fresh telemetry sample."""

        tasks = self.list_tasks()
        confirmations = [
            document for task in tasks if (document := confirmation_document(task)) is not None
        ]
        return {
            "tasks": [task_document(task) for task in self._store.roots()],
            "agents": self.agent_views(),
            "models": self.model_views(),
            "events": [event.model_dump(mode="json") for event in self.list_events(limit=8)],
            "voice": self.voice_status(),
            "missions": [mission_document(mission) for mission in self._missions.list_missions()],
            "workers": [
                worker.model_dump(mode="json") for worker in self._runtime.pool.list_workers()
            ],
            "activity": [activity_document(task) for task in tasks if task.parent_task],
            "confirmations": confirmations,
            "questions": [dict(question) for question in self._questions],
            "project": project_document(self._project),
        }

    def get_task(self, task_id: str) -> Task:
        return self._store.get(task_id)

    def list_events(self, *, after: str | None = None, limit: int | None = None) -> list[Event]:
        return self._events.list_events(after=after, limit=limit)

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
                "lifecycle": self._model_lifecycle.state(model.id).value,
                "loaded": self._model_lifecycle.state(model.id) is ModelLifecycleState.LOADED,
            }
            for model in self._models.enabled()
        ]

    def compute_status(self) -> ResourceSnapshot:
        return self._monitor.snapshot()

    def display_view(self) -> dict[str, object]:
        return diagnose_display(self._environment).model_dump(mode="json")

    def voice_status(self) -> dict[str, object]:
        return self._voice.status()

    def list_missions(self) -> list[Mission]:
        return self._missions.list_missions()

    def get_mission(self, mission_id: str) -> Mission:
        return self._missions.get(mission_id)

    def cancel_mission(self, mission_id: str) -> Mission:
        with self._lock:
            mission = self._missions.get(mission_id)
            if mission.status in {MissionStatus.COMPLETED, MissionStatus.CANCELLED}:
                raise ValueError("mission cannot be cancelled")
            if mission.task_id:
                with contextlib.suppress(ValueError):
                    self._cancel(mission.task_id)
            mission = self._missions.get(mission_id)
            if mission.status is MissionStatus.CANCELLED:
                return mission
            if mission.status in {MissionStatus.COMPLETED}:
                raise ValueError("mission cannot be cancelled")
            return self._advance_mission(mission, MissionStatus.CANCELLED)

    def pause_mission(self, mission_id: str) -> Mission:
        with self._lock:
            mission = self._missions.get(mission_id)
            if mission.status not in {
                MissionStatus.READY,
                MissionStatus.RUNNING,
                MissionStatus.WAITING,
            }:
                raise ValueError(f"mission cannot be paused from {mission.status.value}")
            if mission.task_id:
                task = self._store.get(mission.task_id)
                if task.status in {
                    TaskStatus.QUEUED,
                    TaskStatus.PLANNING,
                    TaskStatus.RUNNING,
                    TaskStatus.WAITING,
                }:
                    self._store.transition(task, TaskStatus.PAUSED)
            return self._advance_mission(mission, MissionStatus.PAUSED)

    def resume_mission(self, mission_id: str) -> Mission:
        with self._lock:
            mission = self._missions.get(mission_id)
            if mission.status is not MissionStatus.PAUSED:
                raise ValueError("mission is not paused")
            mission = self._advance_mission(mission, MissionStatus.RUNNING)
            if mission.task_id is None:
                return mission
            task = self._store.get(mission.task_id)
            if task.status is not TaskStatus.PAUSED:
                return mission
            pending = task.pending_confirmation or {}
            waiting_on_user = bool(task.metadata.get("question_id")) or (
                bool(pending) and pending.get("approved") is not True
            )
            if waiting_on_user:
                self._store.transition(task, TaskStatus.WAITING)
                return self._advance_mission(mission, MissionStatus.WAITING)
            self._store.transition(task, TaskStatus.RUNNING)
            return mission

    def world_view(self) -> dict[str, Any]:
        return self._world.current().model_dump(mode="json")

    def build_world(self, revision: int) -> WorldState:
        snapshot = self._monitor.snapshot()
        tasks = self._store.list_tasks()
        missions = self._missions.list_missions()
        errors = [
            error.message
            for mission in missions
            if mission.status is MissionStatus.FAILED
            for error in mission.errors
        ]
        return WorldState(
            revision=revision,
            machine={"system": platform.system(), "machine": platform.machine()},
            resources=snapshot.model_dump(mode="json"),
            agents=self.agent_views(),
            workers=[
                worker.model_dump(mode="json") for worker in self._runtime.pool.list_workers()
            ],
            models=self.model_views(),
            missions=[mission_document(mission) for mission in missions],
            tasks=[
                {
                    "id": task.id,
                    "status": task.status.value,
                    "objective": task.objective,
                    "parent_task": task.parent_task,
                }
                for task in tasks
            ],
            tools=sorted(
                capability.id.removeprefix("tool:")
                for capability in self._capabilities.all()
                if capability.id.startswith("tool:")
            ),
            project=self._project.model_dump(mode="json"),
            recent_events=[event.model_dump(mode="json") for event in self.list_events(limit=8)],
            active_errors=errors[:8],
            configuration={
                "environment": self._environment,
                "execution_mode": self._mode,
            },
            metrics=self._metrics.snapshot(),
        )

    def capability_views(self) -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in self._capabilities.all()]

    def worker_views(self) -> list[dict[str, Any]]:
        return [worker.model_dump(mode="json") for worker in self._runtime.pool.list_workers()]

    def get_worker(self, worker_id: str) -> dict[str, Any]:
        return self._runtime.pool.get(worker_id).model_dump(mode="json")

    def trace_view(self, trace_id: str) -> dict[str, Any]:
        events = [
            event.model_dump(mode="json")
            for event in self.list_events()
            if event.trace_id == trace_id
        ]
        missions = [
            mission_document(mission)
            for mission in self._missions.list_missions()
            if mission.trace_id == trace_id
        ]
        if not events and not missions:
            raise KeyError(f"unknown trace: {trace_id}")
        return {"trace_id": trace_id, "events": events, "missions": missions}

    def list_memory(self, *, scope: str, scope_key: str, limit: int) -> list[dict[str, Any]]:
        if scope not in SCOPES:
            raise MemoryAccessError(f"unknown memory scope: {scope}")
        grant = AccessGrant({scope})
        records = self.memory.retrieve(grant, scope=scope, scope_key=scope_key, limit=limit)
        return [record.model_dump(mode="json") for record in records]

    def verification_view(self, verification_id: str) -> dict[str, Any]:
        stored = self._verifications.get(verification_id)
        if stored is not None:
            return stored.model_dump(mode="json")
        task = self._store.get(verification_id)
        verdict = verify_observations(task.id, list(task.observations), workspace=self._workspace)
        self._verifications[verdict.id] = verdict
        return verdict.model_dump(mode="json")

    def questions(self) -> list[dict[str, object]]:
        return list(self._questions)

    def graph_view(self) -> dict[str, Any]:
        return build_graph(
            missions=[mission_document(mission) for mission in self._missions.list_missions()],
            tasks=[task.model_dump(mode="json") for task in self._store.list_tasks()],
            workers=self.worker_views(),
            agents=self.agent_views(),
            models=self.model_views(),
            tools=sorted(
                capability.id.removeprefix("tool:")
                for capability in self._capabilities.all()
                if capability.id.startswith("tool:")
            ),
        )

    def replay(self) -> dict[str, Any]:
        return replay_events(self.list_events())

    def context_for(self, task: Task) -> str:
        """Rank a few memory notes for one model call. The database is not dumped."""

        memories: list[dict[str, Any]] = []
        scope_key = task.parent_task or task.id
        mission_key = task.metadata.get("mission_id")
        if isinstance(mission_key, str) and mission_key:
            scope_key = mission_key
        grant = AccessGrant({"task", "project"})
        records = self.memory.retrieve(
            grant,
            scope="task",
            scope_key=str(scope_key),
            query=task.objective,
            limit=self._memory_limit,
        )
        for record in records:
            memories.append(
                {
                    "content": record.content,
                    "source": record.source or "memory",
                    "scope": record.scope,
                    "created_at": record.created_at,
                    "priority": 0,
                }
            )
        revision = task.metadata.get("world_revision", 0)
        built = build_context(
            request=task.objective,
            memories=memories,
            project_name=self._project.name,
            world_revision=revision if isinstance(revision, int) else 0,
            item_limit=self._context_items,
            char_limit=self._context_chars,
        )
        return built.render(char_limit=self._context_chars)

    def _materialize(
        self, objective: str, *, extras: dict[str, Any] | None = None
    ) -> tuple[Task, list[Task]]:
        nodes = plan_objective(objective)
        now = datetime.now(UTC)
        parent_id = str(uuid4())
        snapshot = self._monitor.snapshot()
        key_to_id = {node.key: str(uuid4()) for node in nodes}
        children: list[Task] = []
        steps: list[TaskStep] = []
        for node in nodes:
            child = self._child(node, parent_id, key_to_id, now, snapshot, extras or {})
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
            metadata={"role": "parent", **(extras or {})},
        )
        return parent, children

    def _child(
        self,
        node: PlanNode,
        parent_id: str,
        key_to_id: dict[str, str],
        now: datetime,
        snapshot: ResourceSnapshot,
        extras: dict[str, Any],
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
            metadata={
                "role": "child",
                "key": node.key,
                "exclusive": node.exclusive,
                **extras,
            },
        )

    def _select_model(self, capability: str, snapshot: ResourceSnapshot) -> str | None:
        if not self._models.enabled():
            return None
        required = _MODEL_CAPABILITY.get(capability, "reasoning")
        if self._mode in {"testing", "development"}:
            try:
                route = self._router.select([required], snapshot)
            except RoutingError:
                return None
            return route.model.id
        choice = self._router.choose(
            [required],
            snapshot,
            mode=self._mode,
            available=self._available_model_ids(),
        )
        if choice.model is None:
            return None
        return choice.model.id

    def _on_event(self, event: Event) -> None:
        self._metrics.observe(event)
        if event.type.startswith(("mission.", "task.", "worker.", "permission.", "verification.")):
            self._world.invalidate()

    def _advance_mission(
        self, mission: Mission, status: MissionStatus, **updates: object
    ) -> Mission:
        previous = mission.status
        updated = self._missions.transition(mission, status, **updates)
        if previous is MissionStatus.PAUSED and status is MissionStatus.RUNNING:
            event_name: str | None = "mission.resumed"
        else:
            event_name = mission_event(status)
        if event_name:
            self._events.publish(
                event_name,
                mission_id=updated.id,
                trace_id=updated.trace_id,
                task_id=updated.task_id,
            )
        self._world.invalidate()
        return updated

    def _publish_decision(self, mission: Mission, decision: ExecutionDecision) -> None:
        snapshot = self._monitor.snapshot()
        payload = decision.model_dump(mode="json")
        payload["resources"] = {
            "cpu_percent": _metric(snapshot.cpu.usage_percent),
            "memory_available_mb": _metric(snapshot.memory.available_mb),
            "gpu_available": _metric(snapshot.gpu.available),
        }
        self._events.publish(
            "decision.selected",
            mission_id=mission.id,
            trace_id=mission.trace_id,
            payload=payload,
        )

    def _ask(self, mission: Mission, intent: Intent, now: datetime) -> Task:
        question_id = str(uuid4())
        question = intent.question or "OMNE needs a more specific request."
        self._questions.append(
            {
                "question_id": question_id,
                "trace_id": mission.trace_id,
                "mission_id": mission.id,
                "question": question,
                "options": list(intent.options),
                "required": True,
                "default": None,
            }
        )
        mission = self._advance_mission(mission, MissionStatus.WAITING)
        return self._terminal_task(
            mission,
            now,
            [TaskStatus.PLANNING, TaskStatus.WAITING],
            metadata={"question_id": question_id, "question": question},
        )

    def _deny(self, mission: Mission, decision: ExecutionDecision, now: datetime) -> Task:
        mission = self._advance_mission(
            mission,
            MissionStatus.FAILED,
            errors=[MissionError(code="denied", message=decision.reason)],
        )
        return self._terminal_task(
            mission,
            now,
            [TaskStatus.PLANNING, TaskStatus.FAILED],
            errors=[TaskErrorRecord(code="denied", message=decision.reason)],
        )

    def _dry_run(
        self, mission: Mission, objective: str, decision: ExecutionDecision, now: datetime
    ) -> Task:
        mission = self._advance_mission(mission, MissionStatus.PLANNING)
        parent, children = self._materialize(
            objective,
            extras={
                "trace_id": mission.trace_id,
                "mission_id": mission.id,
                "dry_run": True,
                "decision": decision.decision,
            },
        )
        steps = [
            {
                "objective": child.objective,
                "agent": child.assigned_agent,
                "model": child.assigned_model,
                "tools": list(child.required_tools),
            }
            for child in children
        ]
        result = {
            "dry_run": True,
            "side_effects": False,
            "decision": decision.model_dump(mode="json"),
            "steps": steps,
            "risk": str(mission.metadata.get("intent", {}).get("risk", "unknown")),
            "estimated_cost": "unknown",
            "network": bool(mission.metadata.get("intent", {}).get("requires_network", False)),
        }
        self._store.save(parent)
        parent = self._walk(parent, [TaskStatus.PLANNING, TaskStatus.RUNNING, TaskStatus.VERIFYING])
        for child in children:
            self._store.save(child)
            self._walk(
                child,
                [
                    TaskStatus.PLANNING,
                    TaskStatus.RUNNING,
                    TaskStatus.VERIFYING,
                    TaskStatus.COMPLETED,
                ],
                result={"dry_run": True},
            )
        parent = self._store.transition(parent, TaskStatus.COMPLETED, result=result)
        mission = self._advance_mission(mission, MissionStatus.READY, task_id=parent.id)
        mission = self._advance_mission(mission, MissionStatus.RUNNING)
        mission = self._advance_mission(mission, MissionStatus.VERIFYING)
        self._advance_mission(mission, MissionStatus.COMPLETED, result=result)
        return self._store.get(parent.id)

    def _close_mission(self, mission: Mission, task: Task) -> Task:
        current = self._missions.get(mission.id)
        self._record_verifications(task)
        if task.status is TaskStatus.COMPLETED and current.status is MissionStatus.RUNNING:
            current = self._advance_mission(current, MissionStatus.VERIFYING)
            self._advance_mission(
                current,
                MissionStatus.COMPLETED,
                result={"task_id": task.id, "status": task.status.value},
            )
            self._remember(task)
        elif task.status is TaskStatus.WAITING and current.status is MissionStatus.RUNNING:
            self._advance_mission(current, MissionStatus.WAITING)
        elif task.status is TaskStatus.FAILED and current.status is MissionStatus.RUNNING:
            message = task.errors[-1].message if task.errors else "mission failed"
            self._advance_mission(
                current,
                MissionStatus.FAILED,
                errors=[MissionError(code="failed", message=message)],
            )
        elif task.status is TaskStatus.CANCELLED and current.status in {
            MissionStatus.RUNNING,
            MissionStatus.WAITING,
            MissionStatus.READY,
        }:
            self._advance_mission(current, MissionStatus.CANCELLED)
        self._world.invalidate()
        return self._store.get(task.id)

    def _remember(self, task: Task) -> None:
        trace = task.metadata.get("trace_id")
        mission_key = task.metadata.get("mission_id")
        scope_key = mission_key if isinstance(mission_key, str) and mission_key else task.id
        self.memory.add(
            AccessGrant({"task"}),
            scope="task",
            scope_key=scope_key,
            content=f"Mission finished with status {task.status.value} for {task.objective}"[:500],
            trace_id=trace if isinstance(trace, str) else "",
            source="mission",
        )

    def _record_verifications(self, task: Task) -> None:
        children = self._store.children(task.id)
        subjects = children or [task]
        for subject in subjects:
            verdict = verify_observations(
                subject.id, list(subject.observations), workspace=self._workspace
            )
            self._verifications[verdict.id] = verdict

    def _terminal_task(
        self,
        mission: Mission,
        now: datetime,
        statuses: list[TaskStatus],
        *,
        metadata: dict[str, Any] | None = None,
        errors: list[TaskErrorRecord] | None = None,
    ) -> Task:
        task = Task(
            id=str(uuid4()),
            objective=mission.objective,
            created_at=now,
            updated_at=now,
            retry_limit=self._retry_limit,
            metadata={
                "role": "parent",
                "trace_id": mission.trace_id,
                "mission_id": mission.id,
                **(metadata or {}),
            },
        )
        self._store.save(task)
        task = self._walk(task, statuses, errors=errors or [])
        self._missions.save(
            mission.model_copy(update={"task_id": task.id, "updated_at": task.updated_at})
        )
        return task

    def _walk(self, task: Task, statuses: list[TaskStatus], **updates: object) -> Task:
        current = task
        for index, status in enumerate(statuses):
            if index == len(statuses) - 1:
                current = self._store.transition(current, status, **updates)
            else:
                current = self._store.transition(current, status)
        return current

    def _local_available(self) -> bool:
        return any(
            model.local and self._model_lifecycle.state(model.id) is ModelLifecycleState.AVAILABLE
            for model in self._models.enabled()
        )

    def _cloud_available(self) -> bool:
        return any(
            (not model.local)
            and model.provider != "mock"
            and self._model_lifecycle.state(model.id) is ModelLifecycleState.AVAILABLE
            for model in self._models.enabled()
        )

    def _available_model_ids(self) -> set[str]:
        return {
            model.id
            for model in self._models.enabled()
            if self._model_lifecycle.state(model.id)
            in {ModelLifecycleState.AVAILABLE, ModelLifecycleState.LOADED, ModelLifecycleState.IDLE}
        }

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


def activity_document(task: Task) -> dict[str, Any]:
    """Serialize one child task for the live mission view."""

    mission_id = task.metadata.get("mission_id")
    return {
        "id": task.id,
        "parent_task": task.parent_task,
        "objective": task.objective,
        "status": task.status.value,
        "assigned_agent": task.assigned_agent,
        "assigned_model": task.assigned_model,
        "mission_id": mission_id if isinstance(mission_id, str) else None,
        "verification": _verification_brief(task.result),
        "errors": [{"code": error.code, "message": error.message} for error in task.errors],
    }


def confirmation_document(task: Task) -> dict[str, Any] | None:
    """Describe a confirmation the gateway is still waiting on."""

    pending = task.pending_confirmation or {}
    if task.status is not TaskStatus.WAITING or not pending or pending.get("approved") is True:
        return None
    mission_id = task.metadata.get("mission_id")
    return {
        "task_id": task.id,
        "objective": task.objective,
        "tool_id": str(pending.get("tool_id", "")),
        "command": _confirmation_command(pending, task.objective),
        "agent_id": task.assigned_agent,
        "mission_id": mission_id if isinstance(mission_id, str) else None,
    }


def project_document(project: ProjectContext) -> dict[str, Any]:
    """Return project identity without paths that are only useful to the host."""

    return {
        "name": project.name,
        "type": project.type,
        "git_branch": project.git_branch,
        "languages": list(project.languages),
    }


def _verification_brief(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return None
    verification = result.get("verification")
    if not isinstance(verification, dict):
        return None
    status = verification.get("status")
    if not isinstance(status, str):
        return None
    return {
        "status": status,
        "evidence": _string_list(verification.get("evidence")),
        "checks": _string_list(verification.get("checks")),
        "errors": _string_list(verification.get("errors")),
    }


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _confirmation_command(pending: dict[str, Any], objective: str) -> str:
    for key in ("arguments", "requested"):
        arguments = pending.get(key)
        if not isinstance(arguments, dict):
            continue
        argv = arguments.get("argv")
        if isinstance(argv, list) and argv and all(isinstance(item, str) for item in argv):
            return " ".join(argv)
    return objective


def mission_document(mission: Mission) -> dict[str, Any]:
    """Serialize a mission for the HTTP API."""

    return mission.model_dump(mode="json")


def _metric(value: object) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)
