"""Build the in-process OMNE runtime."""

from __future__ import annotations

import os

from core.agents.communication import AgentMailbox
from core.agents.lifecycle import AgentLifecycle
from core.agents.registry import AgentRegistry
from core.agents.runtime import AgentRuntime
from core.capabilities.registry import build_capability_registry
from core.compute.model_cache import ModelCache
from core.compute.monitor import SystemMonitor
from core.compute.scheduler import ComputeScheduler
from core.config.settings import Settings, prepare_runtime_directories
from core.events.bus import EventBus
from core.memory.database import MemoryDatabase
from core.memory.store import MemoryStore
from core.mission.store import MissionStore
from core.models.cache import ResponseCache
from core.models.lifecycle import ModelLifecycle
from core.models.providers.base import ModelProvider
from core.models.providers.local.provider import LocalProvider
from core.models.providers.mock.provider import MockProvider
from core.models.providers.xai.provider import XAIProvider
from core.models.registry import ModelRegistry
from core.models.router import ModelRouter
from core.orchestrator.executor.executor import TaskExecutor
from core.orchestrator.scheduler import TaskScheduler
from core.orchestrator.service import OMNE
from core.orchestrator.store import TaskStore
from core.permissions.audit import AuditLog
from core.permissions.evaluator import PermissionEvaluator
from core.project.context import inspect_project
from core.tools import build_registry
from core.tools.gateway import ToolGateway
from core.voice.service import VoiceService
from core.world.state import WorldStateService


def build_OMNE(settings: Settings) -> OMNE:
    """Assemble registries, providers, and the scheduler.

    Missing agent or model directories produce an empty registry. The xAI
    credential is read from ``XAI_API_KEY`` at construction and is not written
    into settings.
    """

    prepare_runtime_directories(settings)
    events = EventBus(persist_path=settings.data_dir / "events.jsonl")
    monitor = SystemMonitor()
    compute = ComputeScheduler(monitor)
    cache = ModelCache()
    tools = build_registry(browser_command=settings.browser_command)
    evaluator = PermissionEvaluator()
    gateway = ToolGateway(
        tools,
        evaluator,
        AuditLog(settings.data_dir / "audit.jsonl"),
        events,
    )
    agents = AgentRegistry()
    agents.discover(settings.agents_dir, known_tools=tools.ids())
    lifecycle = AgentLifecycle(events)
    for manifest in agents.all():
        lifecycle.register(manifest.id)
    runtime = AgentRuntime(lifecycle, events=events)
    models = ModelRegistry()
    models.discover(settings.models_dir)
    for model in models.enabled():
        cache.register(model.id, size_bytes=None, requirements=model.requirements)
    providers, model_names, provider_labels = _providers(settings, models)
    store = TaskStore(settings.data_dir / "tasks.sqlite")
    model_lifecycle = ModelLifecycle()
    for model in models.enabled():
        available = _model_is_available(settings, model.provider)
        model_lifecycle.register(model, available=available)
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
    )
    executor._context_text = omne.context_for
    return omne


def _model_is_available(settings: Settings, provider: str) -> bool:
    """Report availability from configuration. This does not load weights."""

    if provider == "mock":
        return True
    if provider == "local":
        return bool(settings.local_model_base_url)
    if provider == "xai":
        return bool(os.environ.get("XAI_API_KEY"))
    return False


def _providers(
    settings: Settings, models: ModelRegistry
) -> tuple[dict[str, ModelProvider], dict[str, str], dict[str, str]]:
    mock: ModelProvider = MockProvider()
    xai: ModelProvider = XAIProvider(
        api_key=os.environ.get("XAI_API_KEY"),
        base_url=settings.xai_base_url,
        timeout_seconds=settings.xai_timeout_seconds,
        max_retries=settings.xai_max_retries,
    )
    local: ModelProvider = LocalProvider(
        base_url=settings.local_model_base_url,
        timeout_seconds=settings.xai_timeout_seconds,
    )
    by_provider = {"mock": mock, "xai": xai, "local": local}
    providers: dict[str, ModelProvider] = {}
    names: dict[str, str] = {}
    labels: dict[str, str] = {}
    for model in models.enabled():
        providers[model.id] = by_provider[model.provider]
        names[model.id] = model.model_name
        labels[model.id] = model.provider
    return providers, names, labels
