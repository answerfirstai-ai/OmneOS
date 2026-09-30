"""The OMNE execution service."""

from __future__ import annotations

import asyncio
import contextlib
import platform
import threading
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.agents.communication import AgentMailbox
from core.agents.lifecycle import AgentLifecycle, AgentState
from core.agents.registry import AgentRegistry
from core.agents.runtime import AgentRuntime
from core.capabilities.registry import CapabilityRegistry
from core.compute.manager import ResourceManager
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
from core.mission.model import (
    MISSION_TRANSITIONS,
    Mission,
    MissionError,
    MissionStatus,
    mission_event,
)
from core.mission.store import MissionStore
from core.models.cortex import Cortex, IntelligenceContext
from core.models.lifecycle import LOADED_STATES, SELECTABLE_STATES, ModelLifecycle
from core.models.providers.base import ModelProvider
from core.models.providers.nvidia.provider import NvidiaProvider
from core.models.registry import ModelRegistry
from core.models.router import ModelRouter, RoutingError
from core.models.runtime import ModelRuntime
from core.models.structured import StructuredDecision
from core.orchestrator.planner.planner import PlanNode, plan_objective
from core.orchestrator.scheduler import TaskScheduler
from core.orchestrator.store import TaskStore
from core.orchestrator.task import Task, TaskErrorRecord, TaskStatus, TaskStep
from core.permissions.evaluator import PermissionEvaluator
from core.permissions.policies import PermissionRequest
from core.project.context import ProjectContext
from core.trace import new_trace_id, set_mission_id
from core.verify.verifier import VerificationResult, verify_observations
from core.voice.service import VoiceService
from core.world.state import WorldState, WorldStateService
from omne.applications.service import ApplicationService
from omne.audio.model import AudioRequest
from omne.audio.select import audio_service
from omne.audio.service import AudioService
from omne.browser.select import browser_service
from omne.browser.service import BrowserService
from omne.display.select import diagnose_display
from omne.hardware.select import hardware_service
from omne.hardware.service import HardwareService
from omne.input.model import InputRequest
from omne.input.select import input_service
from omne.input.service import InputService
from omne.network.model import NetworkRequest
from omne.network.select import network_service
from omne.network.service import NetworkService
from omne.processes.select import process_service
from omne.processes.service import ProcessService
from omne.recovery.select import recovery_service
from omne.recovery.service import RecoveryService
from omne.storage.select import storage_service
from omne.storage.service import StorageService
from omne.updates.service import UpdateService
from omne.windowing.model import WindowRequest
from omne.windowing.select import windowing_service
from omne.windowing.service import WindowingService

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


def _required_model_capability(capability: str) -> str:
    if capability in {"reasoning", "coding", "planning", "tool_use", "vision"}:
        return capability
    return _MODEL_CAPABILITY.get(capability, "reasoning")


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
        activation_shortcut: str = "",
        cancel_shortcut: str = "",
        push_to_talk_shortcut: str = "",
        applications: ApplicationService | None = None,
        browser: BrowserService | None = None,
        processes: ProcessService | None = None,
        model_runtime: ModelRuntime | None = None,
        resources: ResourceManager | None = None,
        data_dir: Path | None = None,
        model_route: str = "mock",
        preferred_nvidia_model: str = "",
        providers: dict[str, ModelProvider] | None = None,
        model_names: dict[str, str] | None = None,
        provider_labels: dict[str, str] | None = None,
        nvidia_provider: NvidiaProvider | None = None,
        cortex: Cortex | None = None,
        nvidia_configured: bool = False,
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
        self.model_runtime = model_runtime
        self.resources = resources
        self._project = project
        self._mode = execution_mode
        self._model_route = model_route
        self._preferred_nvidia_model = preferred_nvidia_model
        self._providers = providers or {}
        self._model_names = model_names or {}
        self._provider_labels = provider_labels or {}
        self._nvidia = nvidia_provider
        self._cortex = cortex
        self._nvidia_configured = nvidia_configured
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
        self._windowing: WindowingService | None = None
        self._hardware: HardwareService | None = None
        self._network: NetworkService | None = None
        self._audio: AudioService | None = None
        self._input: InputService | None = None
        self._storage: StorageService | None = None
        self._updates: UpdateService | None = None
        self._recovery: RecoveryService | None = None
        self._data_dir = data_dir
        self._applications = applications
        self._browser = browser
        self._processes = processes
        self._activation_shortcut = activation_shortcut
        self._cancel_shortcut = cancel_shortcut
        self._push_to_talk_shortcut = push_to_talk_shortcut
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
            task = self._cancel(task_id)
            self._cancel_mission_for(task)
            return self._store.get(task.id)

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
            "questions": self._open_questions(),
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
        views: list[dict[str, object]] = []
        ready = self._available_model_ids()
        for model in self._models.enabled():
            state = self._model_lifecycle.state(model.id)
            views.append(
                {
                    "id": model.id,
                    "provider": model.provider,
                    "model_name": self._model_names.get(model.id, model.model_name),
                    "local": model.local,
                    "priority": model.priority,
                    "capabilities": list(model.capabilities),
                    "cost_input": model.cost_input,
                    "cost_output": model.cost_output,
                    "latency": model.latency,
                    "lifecycle": state.value,
                    "loaded": state in LOADED_STATES,
                    "context_window": model.context_window,
                    "reasoning": model.reasoning,
                    "tool_calling": model.tool_calling,
                    "vision": model.vision,
                    "coding": model.coding,
                    "availability": "available" if model.id in ready else "unavailable",
                    "resource_class": model.resource_class(),
                    "ram_mb": model.requirements.ram_mb if model.requirements.ram_known else None,
                    "vram_mb": model.requirements.vram_mb
                    if model.requirements.vram_known
                    else None,
                    "gpu": "unknown",
                    "engine": None,
                    "resident": False,
                    "healthy": state in SELECTABLE_STATES,
                    "worker_id": None,
                }
            )
        if self.model_runtime is None:
            return views
        for view in views:
            model_id = view["id"]
            if not isinstance(model_id, str):
                continue
            health = self.model_runtime.health(model_id)
            view["loaded"] = health["loaded"]
            view["gpu"] = health["gpu"]
            view["engine"] = health["engine"]
            view["resident"] = health["resident"]
            view["healthy"] = health["healthy"]
            view["worker_id"] = health["worker_id"]
            view["lifecycle"] = health["lifecycle"]
        ready = self._available_model_ids()
        for view in views:
            model_id = view["id"]
            if isinstance(model_id, str):
                view["availability"] = "available" if model_id in ready else "unavailable"
                external = self._model_names.get(model_id)
                if external:
                    view["model_name"] = external
                cloud = view.get("resource_class") == "CLOUD_MODEL_RESOURCE"
                if cloud and view.get("engine") is None:
                    view["gpu"] = "cloud"
        return views

    def nvidia_status(self) -> dict[str, object]:
        """Report NVIDIA configuration without calling the network."""

        return {
            "nvidia": "CONFIGURED" if self._nvidia_configured else "NOT CONFIGURED",
            "provider": "AVAILABLE" if self._nvidia_configured else "UNAVAILABLE",
            "model": self._preferred_nvidia_model,
            "inference": "NOT RUN",
            "authentication": "SKIPPED",
        }

    async def test_nvidia(self) -> dict[str, object]:
        """One real completion when a key is configured. Tools are not called."""

        if self._nvidia is None:
            return {
                "nvidia": "NOT CONFIGURED",
                "provider": "UNAVAILABLE",
                "model": self._preferred_nvidia_model,
                "inference": "FAIL",
                "authentication": "SKIPPED",
                "detail": "NVIDIA provider is not installed",
            }
        result = await self._nvidia.probe(self._preferred_nvidia_model or "nvidia")
        provider = str(result.get("answered_provider") or result.get("provider") or "")
        self._events.publish(
            "model.completed" if result.get("inference") == "PASS" else "model.failed",
            source="models",
            payload={
                "provider": "nvidia" if result.get("inference") == "PASS" else provider,
                "model": result.get("model"),
                "latency": result.get("latency_ms"),
                "code": "ok" if result.get("inference") == "PASS" else "probe",
            },
        )
        answered = result.get("answered_provider")
        if result.get("inference") == "PASS" and answered not in {"", "nvidia"}:
            result = dict(result)
            result["inference"] = "FAIL"
            result["detail"] = "response provider was not nvidia"
        return result

    def request_model(self, capability: str) -> dict[str, object]:
        """Name the model a worker should use. Nothing is executed."""

        model_id, fallbacks = self._select_model(capability, self._monitor.snapshot())
        if model_id is None:
            return {
                "capability": capability,
                "model": None,
                "provider": None,
                "model_name": None,
                "resource_class": None,
                "fallbacks": [],
            }
        model = self._models.get(model_id)
        return {
            "capability": capability,
            "model": model_id,
            "provider": model.provider,
            "model_name": self._model_names.get(model_id, model.model_name),
            "resource_class": model.resource_class(),
            "fallbacks": fallbacks,
        }

    async def reason(self, objective: str, *, capability: str = "reasoning") -> StructuredDecision:
        """Ask the routed model for a decision. Tool requests are not executed."""

        if self._cortex is None:
            raise RuntimeError("intelligence layer is not configured")
        text = " ".join(objective.split())
        if not text:
            raise ValueError("objective must not be empty")
        required = _required_model_capability(capability)
        route = self._route_for_mode()
        if route == "mock":
            route = "auto" if self._nvidia_configured else "mock"
        return await self._cortex.complete(
            self._intelligence_context(text),
            self._monitor.snapshot(),
            capability=required,
            route=route,
            available=self._available_model_ids(),
            preferred_model=self._preferred_nvidia_model or None,
            allow_mock=self._mode != "production",
        )

    async def decide_for(self, task: Task) -> StructuredDecision:
        """Ask the routed model for this task. The caller runs tools."""

        if self._cortex is None:
            raise RuntimeError("intelligence layer is not configured")
        text = " ".join(task.objective.split())
        if not text:
            raise ValueError("objective must not be empty")
        worker = task.metadata.get("worker_id")
        trace = task.metadata.get("trace_id")
        return await self._cortex.complete(
            self._intelligence_context(text),
            self._monitor.snapshot(),
            capability="reasoning",
            route=self._route_for_mode(),
            available=self._available_model_ids(),
            task_id=task.id,
            worker_id=worker if isinstance(worker, str) else None,
            trace_id=trace if isinstance(trace, str) else None,
            preferred_model=self._preferred_nvidia_model or None,
            allow_mock=self._mode != "production",
        )

    def _intelligence_context(self, objective: str) -> IntelligenceContext:
        agents = [
            f"{manifest.id} ({', '.join(manifest.capabilities[:4])})"
            for manifest in self._agents.all()[:8]
        ]
        workers = [
            f"{worker.get('worker_id', '')} {worker.get('lifecycle', '')}"
            for worker in self.worker_views()[:8]
        ]
        tools = sorted(
            capability.id.removeprefix("tool:")
            for capability in self._capabilities.all()
            if capability.id.startswith("tool:")
        )[:16]
        permissions = sorted(
            {
                f"{name}:{','.join(grants)}"
                for manifest in self._agents.all()
                for name, grants in manifest.permissions.items()
            }
        )[:12]
        snapshot = self._monitor.snapshot()
        machine = (
            f"cpu={_metric(snapshot.cpu.usage_percent)} "
            f"memory_available_mb={_metric(snapshot.memory.available_mb)}"
        )
        return IntelligenceContext(
            objective=objective,
            task=objective,
            agents=agents,
            workers=[item for item in workers if item.strip()],
            tools=tools,
            permissions=permissions,
            machine=machine,
            memory=self._bounded_memory(objective),
            project=self._project.name,
        )

    def _bounded_memory(self, objective: str) -> str:
        grant = AccessGrant({"project", "task"})
        try:
            records = self.memory.retrieve(
                grant,
                scope="project",
                scope_key=self._project.name or "workspace",
                query=objective,
                limit=min(self._memory_limit, 5),
            )
        except MemoryAccessError:
            return ""
        notes = [record.content for record in records[:5]]
        return "\n".join(notes)

    def compute_status(self) -> ResourceSnapshot:
        return self._monitor.snapshot()

    def resource_view(self) -> dict[str, object]:
        snapshot = self._monitor.snapshot()
        if self.resources is None:
            view: dict[str, object] = snapshot.model_dump()
            view["held"] = {
                "cpu_threads": 0,
                "ram_mb": 0,
                "vram_mb": 0,
                "disk_mb": 0,
                "gpus": 0,
            }
            view["reservations"] = []
            return view
        return self.resources.status(snapshot)

    def display_view(self) -> dict[str, object]:
        return diagnose_display(self._environment).model_dump(mode="json")

    def windowing_view(self) -> dict[str, object]:
        with self._lock:
            return self._windowing_service().state().model_dump(mode="json")

    def apply_window(
        self, request: WindowRequest, grants: dict[str, list[str]]
    ) -> dict[str, object]:
        with self._lock:
            return (
                self._windowing_service()
                .apply(request, grants, self._environment)
                .model_dump(mode="json")
            )

    def _windowing_service(self) -> WindowingService:
        service = self._windowing
        if service is not None:
            return service

        def sink(event_type: str, payload: dict[str, Any], agent_id: str | None) -> None:
            self._events.publish(
                event_type,
                agent_id=agent_id,
                source="windowing",
                payload=payload,
            )

        service = windowing_service(self._environment, sink=sink)
        self._windowing = service
        return service

    def hardware_view(self) -> dict[str, object]:
        with self._lock:
            return self._hardware_service().inventory().model_dump(mode="json")

    def _hardware_service(self) -> HardwareService:
        service = self._hardware
        if service is not None:
            return service

        def sink(event_type: str, payload: dict[str, Any]) -> None:
            self._events.publish(event_type, source="hardware", payload=payload)

        service = hardware_service(self._environment, sink=sink)
        self._hardware = service
        return service

    def network_view(self) -> dict[str, object]:
        with self._lock:
            return self._network_service().inspect().model_dump(mode="json")

    def apply_network(
        self, request: NetworkRequest, grants: dict[str, list[str]]
    ) -> dict[str, object]:
        with self._lock:
            return (
                self._network_service()
                .apply(request, grants, self._environment)
                .model_dump(mode="json")
            )

    def _network_service(self) -> NetworkService:
        service = self._network
        if service is not None:
            return service

        def sink(event_type: str, payload: dict[str, Any]) -> None:
            self._events.publish(event_type, source="network", payload=payload)

        def authorize(
            tool_id: str,
            arguments: dict[str, object],
            grants: Mapping[str, Sequence[str]],
            environment: str,
        ) -> tuple[str, str]:
            result = PermissionEvaluator().evaluate(
                PermissionRequest(
                    tool_id=tool_id,
                    arguments=dict(arguments),
                    grants={key: list(value) for key, value in grants.items()},
                    environment=environment,
                    workspace_root=str(self._workspace),
                )
            )
            return result.decision.value, result.reason

        service = network_service(self._environment, sink=sink, authorize=authorize)
        self._network = service
        return service

    def audio_view(self) -> dict[str, object]:
        with self._lock:
            return self._audio_service().inspect().model_dump(mode="json")

    def apply_audio(self, request: AudioRequest, grants: dict[str, list[str]]) -> dict[str, object]:
        with self._lock:
            return (
                self._audio_service()
                .apply(request, grants, self._environment)
                .model_dump(mode="json")
            )

    def _audio_service(self) -> AudioService:
        service = self._audio
        if service is not None:
            return service

        def sink(event_type: str, payload: dict[str, Any]) -> None:
            self._events.publish(event_type, source="audio", payload=payload)

        def authorize(
            tool_id: str,
            arguments: dict[str, object],
            grants: Mapping[str, Sequence[str]],
            environment: str,
        ) -> tuple[str, str]:
            result = PermissionEvaluator().evaluate(
                PermissionRequest(
                    tool_id=tool_id,
                    arguments=dict(arguments),
                    grants={key: list(value) for key, value in grants.items()},
                    environment=environment,
                    workspace_root=str(self._workspace),
                )
            )
            return result.decision.value, result.reason

        service = audio_service(self._environment, sink=sink, authorize=authorize)
        self._audio = service
        return service

    def input_view(self) -> dict[str, object]:
        with self._lock:
            return self._input_service().inspect().model_dump(mode="json")

    def apply_input(self, request: InputRequest, grants: dict[str, list[str]]) -> dict[str, object]:
        with self._lock:
            return (
                self._input_service()
                .apply(request, grants, self._environment)
                .model_dump(mode="json")
            )

    def _input_service(self) -> InputService:
        service = self._input
        if service is not None:
            return service

        def sink(event_type: str, payload: dict[str, Any]) -> None:
            self._events.publish(event_type, source="input", payload=payload)

        def authorize(
            tool_id: str,
            arguments: dict[str, object],
            grants: Mapping[str, Sequence[str]],
            environment: str,
        ) -> tuple[str, str]:
            result = PermissionEvaluator().evaluate(
                PermissionRequest(
                    tool_id=tool_id,
                    arguments=dict(arguments),
                    grants={key: list(value) for key, value in grants.items()},
                    environment=environment,
                    workspace_root=str(self._workspace),
                )
            )
            return result.decision.value, result.reason

        service = input_service(
            self._environment,
            activation=self._activation_shortcut,
            cancel=self._cancel_shortcut,
            push_to_talk=self._push_to_talk_shortcut,
            sink=sink,
            authorize=authorize,
        )
        self._input = service
        return service

    def recovery_view(self) -> dict[str, object]:
        with self._lock:
            return self._recovery_service().assess().model_dump(mode="json")

    def _recovery_service(self) -> RecoveryService:
        service = self._recovery
        if service is not None:
            return service
        directory = None if self._data_dir is None else self._data_dir / "recovery"
        updates = None if self._data_dir is None else self._data_dir / "updates"
        service = recovery_service(self._environment, directory, updates_dir=updates)
        self._recovery = service
        return service

    def updates_view(self) -> dict[str, object]:
        with self._lock:
            return self._update_service().status().model_dump(mode="json")

    def _update_service(self) -> UpdateService:
        service = self._updates
        if service is not None:
            return service
        directory = None if self._data_dir is None else self._data_dir / "updates"
        service = UpdateService(directory, host_protected=True)
        self._updates = service
        return service

    def storage_view(self) -> dict[str, object]:
        with self._lock:
            return self._storage_service().inspect().model_dump(mode="json")

    def _storage_service(self) -> StorageService:
        service = self._storage
        if service is not None:
            return service

        def sink(event_type: str, payload: dict[str, Any]) -> None:
            self._events.publish(event_type, source="storage", payload=payload)

        service = storage_service(self._environment, sink=sink)
        self._storage = service
        return service

    def applications_view(self) -> dict[str, object]:
        with self._lock:
            service = self._applications
            if service is None:
                return {
                    "provider": "mock",
                    "observed": False,
                    "applications": [],
                    "gaps": ["runtime"],
                    "commanded": False,
                }
            return service.catalog().model_dump(mode="json")

    def browser_view(self) -> dict[str, object]:
        with self._lock:
            service = self._browser
            if service is None:
                service = browser_service(self._environment)
                self._browser = service
            return service.status().model_dump(mode="json")

    def processes_view(self) -> dict[str, object]:
        with self._lock:
            service = self._processes
            if service is None:
                service = process_service(self._environment)
                self._processes = service
            return service.status().model_dump(mode="json")

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
        model_id, fallbacks = self._select_model(node.capability, snapshot)
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
                "model_fallbacks": fallbacks,
                **extras,
            },
        )

    def _select_model(
        self, capability: str, snapshot: ResourceSnapshot
    ) -> tuple[str | None, list[str]]:
        if not self._models.enabled():
            return None, []
        required = _required_model_capability(capability)
        available = self._available_model_ids()
        route = self._route_for_mode()
        if route == "mock":
            try:
                selected = self._router.select([required], snapshot)
            except RoutingError:
                return None, []
            if selected.model.id not in available:
                return None, []
            return selected.model.id, []
        chain = self._router.order(
            [required],
            snapshot,
            route=route,
            available=available,
            allow_mock=self._mode != "production",
            preferred_model=self._preferred_nvidia_model or None,
        )
        if not chain:
            return None, []
        return chain[0].id, [model.id for model in chain[1:]]

    def _route_for_mode(self) -> str:
        if self._mode in {"offline", "local"}:
            return "local"
        if self._mode == "testing":
            return "mock"
        return self._model_route

    def _on_event(self, event: Event) -> None:
        self._metrics.observe(event)
        if event.type == "task.question":
            question = event.payload.get("question")
            options = event.payload.get("options")
            if isinstance(question, str) and question:
                self._questions.append(
                    {
                        "question_id": event.id,
                        "trace_id": event.trace_id,
                        "mission_id": event.mission_id,
                        "task_id": event.task_id,
                        "question": question,
                        "options": [item for item in options if isinstance(item, str)]
                        if isinstance(options, list)
                        else [],
                        "required": True,
                        "default": None,
                    }
                )
        if event.type.startswith(
            (
                "mission.",
                "task.",
                "worker.",
                "permission.",
                "verification.",
                "model.",
                "compute.",
                "security.",
                "secret.",
                "update.",
                "recovery.",
            )
        ):
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
        ready = self._available_model_ids()
        return any(model.local and model.id in ready for model in self._models.enabled())

    def _cloud_available(self) -> bool:
        ready = self._available_model_ids()
        return any(
            (not model.local) and model.provider != "mock" and model.id in ready
            for model in self._models.enabled()
        )

    def _available_model_ids(self) -> set[str]:
        if self.model_runtime is not None:
            return self.model_runtime.available_ids()
        return {
            model.id
            for model in self._models.enabled()
            if self._model_lifecycle.state(model.id) in SELECTABLE_STATES
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

    def _open_questions(self) -> list[dict[str, object]]:
        open_questions: list[dict[str, object]] = []
        for question in self._questions:
            mission_id = question.get("mission_id")
            if not isinstance(mission_id, str) or not mission_id:
                continue
            try:
                mission = self._missions.get(mission_id)
            except KeyError:
                continue
            if mission.status is MissionStatus.WAITING:
                open_questions.append(dict(question))
        return open_questions

    def _cancel_mission_for(self, task: Task) -> None:
        mission_id = task.metadata.get("mission_id")
        if not isinstance(mission_id, str) or not mission_id:
            return
        try:
            mission = self._missions.get(mission_id)
        except KeyError:
            return
        if MissionStatus.CANCELLED not in MISSION_TRANSITIONS[mission.status]:
            return
        self._advance_mission(mission, MissionStatus.CANCELLED)

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
        "decision": _decision_brief(task),
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


def _decision_brief(task: Task) -> dict[str, Any] | None:
    """Describe the model decision already recorded for one child task."""

    for observation in reversed(task.observations):
        if observation.get("kind") == "decision":
            return {
                "provider": _text(observation.get("provider")),
                "model": _text(observation.get("model")),
                "intent": _text(observation.get("intent")),
                "plan": _string_list(observation.get("plan")),
                "tools": _string_list(observation.get("tools")),
                "rejected_tools": _string_list(observation.get("rejected_tools")),
                "final_response": _text(observation.get("final_response")),
                "observation": _tool_observation(observation.get("outputs")),
            }
    stored = task.metadata.get("structured_decision")
    if not isinstance(stored, dict):
        return None
    return {
        "provider": _text(stored.get("provider")),
        "model": _text(stored.get("model")),
        "intent": _text(stored.get("intent")),
        "plan": _string_list(stored.get("plan")),
        "tools": _requested_tools(stored.get("tool_requests")),
        "rejected_tools": _string_list(stored.get("rejected_tools")),
        "final_response": _text(stored.get("final_response")),
        "observation": "",
    }


def _requested_tools(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for item in value:
        if isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"]:
            names.append(item["name"])
    return names


def _tool_observation(value: object) -> str:
    if not isinstance(value, list):
        return ""
    notes: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        tool_id = item.get("tool_id")
        output = item.get("output")
        if not isinstance(tool_id, str) or not tool_id:
            continue
        if tool_id == "filesystem.read" and isinstance(output, dict):
            content = _text(output.get("content"))
            notes.append(f"read {_text(output.get('path'))}: {content[:80]}")
        elif tool_id == "terminal.execute" and isinstance(output, dict):
            notes.append(f"terminal: {_text(output.get('stdout'))[:80]}")
        else:
            notes.append(tool_id)
    return "; ".join(notes)


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


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
