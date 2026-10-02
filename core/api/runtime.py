"""Build the in-process OMNE runtime."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from core.agents.communication import AgentMailbox
from core.agents.create import load_saved_agents
from core.agents.lifecycle import AgentLifecycle
from core.agents.registry import AgentRegistry
from core.agents.runtime import AgentRuntime
from core.capabilities.registry import build_capability_registry
from core.compute.manager import ResourceManager
from core.compute.model_cache import ModelCache
from core.compute.monitor import SystemMonitor
from core.compute.scheduler import ComputeScheduler
from core.config.settings import Settings, prepare_runtime_directories
from core.events.bus import EventBus
from core.memory.database import MemoryDatabase
from core.memory.store import MemoryStore
from core.mission.store import MissionStore
from core.models.cache import ResponseCache
from core.models.cortex import Cortex
from core.models.credentials import nvidia_api_key, preferred_nvidia_model, xai_api_key
from core.models.engines.mock import MockEngine
from core.models.engines.openai_compatible import OpenAICompatibleEngine
from core.models.lifecycle import ModelLifecycle
from core.models.providers.base import ModelProvider
from core.models.providers.local.provider import LocalProvider
from core.models.providers.mock.provider import MockProvider
from core.models.providers.nvidia.provider import NvidiaProvider
from core.models.providers.xai.provider import XAIProvider
from core.models.registry import ModelRegistry
from core.models.router import ModelRouter
from core.models.runtime import ModelRuntime
from core.orchestrator.executor.executor import TaskExecutor
from core.orchestrator.scheduler import TaskScheduler
from core.orchestrator.service import OMNE
from core.orchestrator.store import TaskStore
from core.permissions.audit import AuditLog
from core.permissions.evaluator import PermissionEvaluator
from core.permissions.policies import PermissionRequest
from core.project.context import inspect_project
from core.tools import build_registry
from core.tools.gateway import ToolGateway
from core.voice.service import VoiceService
from core.workers.lifecycle import WorkerState
from core.workers.pool import WorkerPool
from core.world.state import WorldStateService
from omne.applications.select import application_service
from omne.applications.service import ApplicationService
from omne.audio.select import audio_service
from omne.audio.service import AudioService
from omne.browser.select import browser_service
from omne.browser.service import BrowserService
from omne.display.select import select_provider as select_display
from omne.hardware.select import hardware_service
from omne.hardware.service import HardwareService
from omne.input.select import input_service
from omne.input.service import InputService
from omne.network.select import network_service
from omne.network.service import NetworkService
from omne.processes.select import process_service
from omne.processes.service import (
    ProcessService,
    admit_resources,
    application_id_for,
    worker_id_for,
)
from omne.recovery.select import recovery_service
from omne.secrets.audit import SecretAuditLog
from omne.secrets.select import select_provider
from omne.secrets.service import SecretService
from omne.storage.select import storage_service
from omne.storage.service import StorageService


def build_OMNE(settings: Settings) -> OMNE:
    """Assemble registries, providers, and the scheduler.

    Missing agent or model directories produce an empty registry. The xAI
    credential comes from the secret store, or from ``XAI_API_KEY`` in
    development and testing. It is not written into settings.
    """

    prepare_runtime_directories(settings)
    events = EventBus(persist_path=settings.data_dir / "events.jsonl")
    evaluator = PermissionEvaluator()
    secrets = _secret_service(settings, events, evaluator)
    monitor = SystemMonitor()
    resources = ResourceManager(monitor, events=events)
    compute = ComputeScheduler(monitor, manager=resources)
    cache = ModelCache()
    applications = _application_service(settings, events, evaluator)
    browser = _browser_service(settings, events, evaluator)
    lifecycle = AgentLifecycle(events)
    runtime = AgentRuntime(
        lifecycle,
        events=events,
        pool=WorkerPool(ram_limit_mb=8192, resources=resources),
    )
    processes = _process_service(settings, events, evaluator, monitor, runtime, applications)
    network, audio, hardware, storage, controls = _observer_services(settings, events, evaluator)
    tools = build_registry(
        browser_command=settings.browser_command,
        applications=applications,
        browser=browser,
        processes=processes,
        environment=settings.environment,
        network=network,
        audio=audio,
        hardware=hardware,
        storage=storage,
        display=select_display(settings.environment),
        controls=controls,
    )
    gateway = ToolGateway(
        tools,
        evaluator,
        AuditLog(settings.data_dir / "audit.jsonl"),
        events,
    )
    agents = AgentRegistry()
    agents.discover(settings.agents_dir, known_tools=tools.ids())
    load_saved_agents(agents, settings.data_dir / "agents", known_tools=tools.ids())
    models = ModelRegistry()
    models.discover(settings.models_dir)
    _apply_recovery(settings, agents, models, events)
    for manifest in agents.all():
        lifecycle.register(manifest.id)
    for model in models.enabled():
        cache.register(model.id, size_bytes=None, requirements=model.requirements)
    credential = xai_api_key(settings, secrets)
    nvidia_key = nvidia_api_key(settings, secrets)
    nvidia_model = preferred_nvidia_model(settings)
    providers, model_names, provider_labels, nvidia_provider = _providers(
        settings, models, credential, nvidia_key, nvidia_model
    )
    _announce_providers(
        events,
        nvidia_configured=nvidia_key is not None,
        nvidia_model=nvidia_model,
        xai_configured=credential is not None,
        local_configured=bool(settings.local_model_base_url),
    )
    store = TaskStore(settings.data_dir / "tasks.sqlite")
    model_lifecycle = ModelLifecycle()
    model_runtime = _model_runtime(
        settings,
        models,
        model_lifecycle,
        monitor,
        events,
        runtime,
        resources,
        xai_configured=credential is not None,
        nvidia_configured=nvidia_key is not None,
    )
    executor = TaskExecutor(
        store=store,
        gateway=gateway,
        agents=agents,
        runtime=runtime,
        events=events,
        providers=providers,
        model_names=model_names,
        provider_labels=provider_labels,
        environment=settings.environment,
        workspace_root=settings.workspace_root,
        timeout_seconds=settings.tool_timeout_seconds,
        responses=ResponseCache(ttl_seconds=settings.cache_ttl_seconds),
        verification_required=settings.verification_required,
    )
    scheduler = TaskScheduler(
        store=store,
        executor=executor,
        events=events,
        monitor=monitor,
        compute=compute,
        agents=agents,
        runtime=runtime,
        lifecycle=lifecycle,
        max_parallel=settings.max_parallel_tasks,
        models=models,
        execution_mode=settings.execution_mode,
    )
    omne = OMNE(
        store=store,
        scheduler=scheduler,
        events=events,
        agents=agents,
        lifecycle=lifecycle,
        models=models,
        router=ModelRouter(models),
        monitor=monitor,
        voice=VoiceService(evaluator, environment=settings.environment),
        memory=MemoryStore(MemoryDatabase(settings.data_dir / "memory.sqlite")),
        cache=cache,
        mailbox=AgentMailbox(events),
        retry_limit=settings.task_retry_limit,
        missions=MissionStore(settings.data_dir / "missions.sqlite"),
        world=WorldStateService(ttl_seconds=settings.world_state_ttl_seconds),
        runtime=runtime,
        capabilities=build_capability_registry(agents.all(), models.enabled()),
        model_lifecycle=model_lifecycle,
        project=inspect_project(settings.workspace_root),
        execution_mode=settings.execution_mode,
        environment=settings.environment,
        context_item_limit=settings.context_item_limit,
        context_char_limit=settings.context_char_limit,
        memory_retrieve_limit=settings.memory_retrieve_limit,
        workspace_root=settings.workspace_root,
        activation_shortcut=settings.activation_shortcut,
        cancel_shortcut=settings.cancel_shortcut,
        push_to_talk_shortcut=settings.push_to_talk_shortcut,
        applications=applications,
        browser=browser,
        processes=processes,
        model_runtime=model_runtime,
        resources=resources,
        data_dir=settings.data_dir,
        model_route=settings.model_route,
        preferred_nvidia_model=nvidia_model,
        providers=providers,
        model_names=model_names,
        provider_labels=provider_labels,
        nvidia_provider=nvidia_provider,
        cortex=Cortex(
            router=ModelRouter(models),
            providers=providers,
            model_names=model_names,
            provider_labels=provider_labels,
            events=events,
            known_tools=set(tools.ids()),
        ),
        nvidia_configured=nvidia_key is not None,
    )
    executor._context_text = omne.context_for
    executor._decider = omne.decide_for
    omne._network = network
    omne._audio = audio
    omne._hardware = hardware
    omne._storage = storage
    omne._input = controls
    omne._secrets = secrets
    return omne


def _observer_services(
    settings: Settings,
    events: EventBus,
    evaluator: PermissionEvaluator,
) -> tuple[NetworkService, AudioService, HardwareService, StorageService, InputService]:
    def sink_for(source: str) -> Callable[[str, dict[str, Any]], None]:
        def sink(event_type: str, payload: dict[str, Any]) -> None:
            events.publish(event_type, source=source, payload=payload)

        return sink

    def authorize(
        tool_id: str,
        arguments: dict[str, object],
        grants: Mapping[str, Sequence[str]],
        environment: str,
    ) -> tuple[str, str]:
        result = evaluator.evaluate(
            PermissionRequest(
                tool_id=tool_id,
                arguments=dict(arguments),
                grants={key: list(value) for key, value in grants.items()},
                environment=environment,
                workspace_root=str(settings.workspace_root),
            )
        )
        return result.decision.value, result.reason

    return (
        network_service(settings.environment, sink=sink_for("network"), authorize=authorize),
        audio_service(settings.environment, sink=sink_for("audio"), authorize=authorize),
        hardware_service(settings.environment, sink=sink_for("hardware")),
        storage_service(settings.environment, sink=sink_for("storage")),
        input_service(
            settings.environment,
            activation=settings.activation_shortcut,
            cancel=settings.cancel_shortcut,
            push_to_talk=settings.push_to_talk_shortcut,
            sink=sink_for("input"),
            authorize=authorize,
        ),
    )


def _application_service(
    settings: Settings,
    events: EventBus,
    evaluator: PermissionEvaluator,
) -> ApplicationService:
    def sink(event_type: str, payload: dict[str, Any]) -> None:
        events.publish(event_type, source="applications", payload=payload)

    def authorize(
        tool_id: str,
        arguments: dict[str, object],
        grants: Mapping[str, Sequence[str]],
        environment: str,
    ) -> tuple[str, str]:
        result = evaluator.evaluate(
            PermissionRequest(
                tool_id=tool_id,
                arguments=dict(arguments),
                grants={key: list(value) for key, value in grants.items()},
                environment=environment,
                workspace_root=str(settings.workspace_root),
            )
        )
        return result.decision.value, result.reason

    return application_service(settings.environment, sink=sink, authorize=authorize)


def _browser_service(
    settings: Settings,
    events: EventBus,
    evaluator: PermissionEvaluator,
) -> BrowserService:
    def sink(event_type: str, payload: dict[str, Any]) -> None:
        events.publish(event_type, source="browser", payload=payload)

    def authorize(
        tool_id: str,
        arguments: dict[str, object],
        grants: Mapping[str, Sequence[str]],
        environment: str,
    ) -> tuple[str, str]:
        result = evaluator.evaluate(
            PermissionRequest(
                tool_id=tool_id,
                arguments=dict(arguments),
                grants={key: list(value) for key, value in grants.items()},
                environment=environment,
                workspace_root=str(settings.workspace_root),
            )
        )
        return result.decision.value, result.reason

    return browser_service(settings.environment, sink=sink, authorize=authorize)


def _process_service(
    settings: Settings,
    events: EventBus,
    evaluator: PermissionEvaluator,
    monitor: SystemMonitor,
    runtime: AgentRuntime,
    applications: ApplicationService,
) -> ProcessService:
    def sink(event_type: str, payload: dict[str, Any]) -> None:
        events.publish(event_type, source="processes", payload=payload)

    def authorize(
        tool_id: str,
        arguments: dict[str, object],
        grants: Mapping[str, Sequence[str]],
        environment: str,
    ) -> tuple[str, str]:
        result = evaluator.evaluate(
            PermissionRequest(
                tool_id=tool_id,
                arguments=dict(arguments),
                grants={key: list(value) for key, value in grants.items()},
                environment=environment,
                workspace_root=str(settings.workspace_root),
            )
        )
        return result.decision.value, result.reason

    def admit() -> tuple[str, str]:
        snapshot = monitor.snapshot()
        return admit_resources(snapshot.cpu.usage_percent, snapshot.memory.available_mb)

    def worker_for(task_id: str | None) -> str | None:
        rows = [
            (worker.worker_id, worker.current_task, worker.status)
            for worker in runtime.pool.list_workers()
        ]
        return worker_id_for(task_id, rows)

    def application_for(program: str) -> str | None:
        catalog = [(app.id, app.executable) for app in applications.catalog().applications]
        return application_id_for(program, catalog)

    return process_service(
        settings.environment,
        sink=sink,
        authorize=authorize,
        admit=admit,
        worker_for=worker_for,
        application_for=application_for,
    )


def _model_runtime(
    settings: Settings,
    models: ModelRegistry,
    lifecycle: ModelLifecycle,
    monitor: SystemMonitor,
    events: EventBus,
    runtime: AgentRuntime,
    resources: ResourceManager,
    *,
    xai_configured: bool,
    nvidia_configured: bool,
) -> ModelRuntime:
    """Select adapters from configuration. Construction does not load a model."""

    mock_engine = MockEngine()
    for model in models.enabled():
        if model.provider == "mock":
            mock_engine.allow(model.model_name)
    local_engine = OpenAICompatibleEngine(
        base_url=settings.local_model_base_url,
        timeout_seconds=settings.xai_timeout_seconds,
    )
    model_runtime = ModelRuntime(
        registry=models,
        lifecycle=lifecycle,
        monitor=monitor,
        events=events,
        engines={"mock": mock_engine, "openai-compatible": local_engine},
        workers=lambda worker_id: _worker_alive(runtime, worker_id),
        resources=resources,
    )
    model_runtime.prepare(
        available=lambda model: _model_is_available(
            settings,
            model.provider,
            xai_configured=xai_configured,
            nvidia_configured=nvidia_configured,
        )
    )
    return model_runtime


def _worker_alive(runtime: AgentRuntime, worker_id: str) -> bool:
    try:
        worker = runtime.pool.get(worker_id)
    except KeyError:
        return False
    return worker.lifecycle not in {WorkerState.TERMINATED, WorkerState.FAILED}


def _model_is_available(
    settings: Settings,
    provider: str,
    *,
    xai_configured: bool,
    nvidia_configured: bool,
) -> bool:
    """Report availability from configuration. This does not load weights or call NVIDIA."""

    if provider == "mock":
        return True
    if provider == "local":
        return bool(settings.local_model_base_url)
    if provider == "xai":
        return xai_configured
    if provider == "nvidia":
        return nvidia_configured
    return False


def _providers(
    settings: Settings,
    models: ModelRegistry,
    xai_key: str | None,
    nvidia_key: str | None,
    nvidia_model: str,
) -> tuple[dict[str, ModelProvider], dict[str, str], dict[str, str], NvidiaProvider]:
    mock: ModelProvider = MockProvider()
    xai: ModelProvider = XAIProvider(
        api_key=xai_key,
        base_url=settings.xai_base_url,
        timeout_seconds=settings.xai_timeout_seconds,
        max_retries=settings.xai_max_retries,
    )
    nvidia = NvidiaProvider(
        api_key=nvidia_key,
        base_url=settings.nvidia_base_url,
        timeout_seconds=settings.nvidia_timeout_seconds,
        max_retries=settings.nvidia_max_retries,
    )
    local: ModelProvider = LocalProvider(
        base_url=settings.local_model_base_url,
        timeout_seconds=settings.xai_timeout_seconds,
    )
    by_provider: dict[str, ModelProvider] = {
        "mock": mock,
        "xai": xai,
        "local": local,
        "nvidia": nvidia,
    }
    providers: dict[str, ModelProvider] = {}
    names: dict[str, str] = {}
    labels: dict[str, str] = {}
    for model in models.enabled():
        providers[model.id] = by_provider[model.provider]
        names[model.id] = model.model_name
        if model.id == "nvidia-reasoning" and nvidia_model != model.model_name:
            names[model.id] = nvidia_model
        labels[model.id] = model.provider
    return providers, names, labels, nvidia


def _announce_providers(
    events: EventBus,
    *,
    nvidia_configured: bool,
    nvidia_model: str,
    xai_configured: bool,
    local_configured: bool,
) -> None:
    """Record which providers can be called. This does not open a connection."""

    rows = (
        ("nvidia", nvidia_configured, nvidia_model),
        ("xai", xai_configured, ""),
        ("local", local_configured, ""),
        ("mock", True, "mock"),
    )
    for provider, configured, model in rows:
        events.publish(
            "model.provider.available" if configured else "model.provider.unavailable",
            source="models",
            payload={"provider": provider, "model": model, "latency": None},
        )


def _apply_recovery(
    settings: Settings,
    agents: AgentRegistry,
    models: ModelRegistry,
    events: EventBus,
) -> None:
    """Disable third-party agents and optional models when safe mode is active."""

    service = recovery_service(
        settings.environment,
        settings.data_dir / "recovery",
        updates_dir=settings.data_dir / "updates",
        port=settings.port,
    )
    status = service.assess()
    for agent_id in service.disabled_agent_ids(agent.id for agent in agents.all()):
        agents.disable(agent_id)
    pairs = ((model.id, model.provider) for model in models.all())
    for model_id in service.disabled_model_ids(pairs):
        models.disable(model_id)
    if status.state == "NORMAL":
        return
    events.publish(
        "recovery.assessed",
        source="recovery",
        payload={"state": status.state, "explanation": status.explanation},
    )


def _secret_service(
    settings: Settings, events: EventBus, evaluator: PermissionEvaluator
) -> SecretService:
    """Build the secret store. Access is audited and does not record the value."""

    def authorize(
        tool_id: str,
        agent_id: str,
        grants: Mapping[str, Sequence[str]],
        environment: str,
        arguments: dict[str, Any],
    ) -> tuple[str, str]:
        result = evaluator.evaluate(
            PermissionRequest(
                tool_id=tool_id,
                arguments=arguments,
                grants={key: list(value) for key, value in grants.items()},
                environment=environment,
                workspace_root=str(settings.workspace_root),
                agent_id=agent_id,
                user="core",
            )
        )
        return result.decision.value, result.reason

    def publish(event_type: str, payload: dict[str, Any]) -> None:
        events.publish(event_type, source="secrets", payload=payload)

    return SecretService(
        select_provider(settings.environment, dev_fallback=settings.secrets_dev_fallback),
        authorize=authorize,
        audit=SecretAuditLog(settings.data_dir / "secrets-audit.jsonl"),
        sink=publish,
    )
