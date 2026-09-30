"""Model runtime: adapters, residency, compute, workers, and the router."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

import pytest
from tests.support import runtime_settings

from core.agents.lifecycle import AgentLifecycle
from core.agents.manifest import AgentManifest
from core.agents.runtime import AgentRuntime
from core.api.runtime import build_OMNE
from core.compute.monitor import (
    CpuTelemetry,
    DiskTelemetry,
    GpuTelemetry,
    MemoryTelemetry,
    NetworkTelemetry,
    ResourceSnapshot,
)
from core.compute.requirements import ResourceRequirements
from core.events.bus import EventBus
from core.models.engines.mock import MockEngine
from core.models.engines.openai_compatible import OpenAICompatibleEngine
from core.models.lifecycle import InvalidModelTransition, ModelLifecycle, ModelLifecycleState
from core.models.registry import ModelMetadata, ModelRegistry
from core.models.router import ModelRouter
from core.models.runtime import ModelRuntime, estimate_tokens
from core.models.types import ProviderError

Transport = Callable[[str, dict[str, str], bytes, float], tuple[int, bytes]]


def test_explicit_load_emits_and_a_file_write_does_not(tmp_path: Path) -> None:
    omne = build_OMNE(runtime_settings(tmp_path))

    omne.execute_sync("write file notes.txt with content hello")
    assert all(event.type != "model.loaded" for event in omne.list_events())

    loaded = omne.model_runtime.load("mock-default")
    health = omne.model_runtime.health("mock-default")
    names = [event.type for event in omne.list_events()]
    views = {str(item["id"]): item for item in omne.model_views()}

    assert loaded["performed"] is True
    assert loaded["state"] == "LOADED"
    assert "model.loading" in names
    assert "model.loaded" in names
    assert health["engine"] == "mock"
    assert health["gpu"] == "none"
    assert health["loaded"] is True
    assert views["mock-default"]["loaded"] is True
    assert views["mock-default"]["engine"] == "mock"


def test_built_runtime_leaves_an_unconfigured_local_model_unavailable(tmp_path: Path) -> None:
    omne = build_OMNE(runtime_settings(tmp_path))
    local = omne.model_runtime.health("local-default")

    assert local["lifecycle"] == "UNAVAILABLE"
    assert local["gpu"] == "unknown"
    assert local["resident"] is False
    assert "local-default" not in omne.model_runtime.available_ids()
    refused = omne.model_runtime.load("local-default")
    assert refused["performed"] is False
    assert refused["code"] == "unavailable"
    assert all(event.type != "model.loaded" for event in omne.list_events())


def test_mock_load_infer_stream_unload_and_context_limit() -> None:
    engine = MockEngine()
    engine.allow("mock")
    runtime, events, _registry = _runtime(_mock("context-mock", context_window=8), engine=engine)
    loaded = runtime.load("context-mock")
    assert loaded["performed"] is True
    assert [event.type for event in events.list_events()] == ["model.loading", "model.loaded"]

    short = asyncio.run(runtime.generate("context-mock", "hi"))
    assert short.performed is True
    assert short.text == "mock-response:hi"
    assert short.state == "IDLE"
    assert runtime.health("context-mock")["lifecycle"] == "IDLE"

    limited = asyncio.run(
        runtime.generate("context-mock", "hello world this is too long for the window")
    )
    assert limited.performed is False
    assert limited.code == "context_limit"
    assert runtime.health("context-mock")["lifecycle"] == "IDLE"
    assert all(
        event.type != "model.running" or event.payload.get("request_id") == short.request_id
        for event in events.list_events()
    )

    async def limited() -> None:
        async for _chunk in runtime.stream("context-mock", "x" * 80, system="system " * 20):
            pass

    with pytest.raises(ProviderError) as caught:
        asyncio.run(limited())
    assert caught.value.code == "context_limit"

    parts: list[str] = []

    async def read() -> None:
        async for chunk in runtime.stream(
            "context-mock", "hello there friend", request_id="stream-1"
        ):
            parts.append(chunk.text)
            if len(parts) == 1:
                runtime.cancel("stream-1")

    asyncio.run(read())
    assert parts
    assert "".join(parts) != "mock-response:hello there friend"
    assert runtime.health("context-mock")["lifecycle"] == "IDLE"
    assert any(event.type == "model.cancelled" for event in events.list_events())

    unloaded = runtime.unload("context-mock")
    assert unloaded["performed"] is True
    assert unloaded["state"] == "AVAILABLE"
    assert any(event.type == "model.unloaded" for event in events.list_events())
    again = asyncio.run(runtime.generate("context-mock", "hi"))
    assert again.code == "not_loaded"


def test_cancellation_stops_a_held_request() -> None:
    engine = MockEngine()
    engine.allow("mock")
    runtime, events, _registry = _runtime(_mock("held-mock"), engine=engine)
    assert runtime.load("held-mock")["performed"] is True
    engine.pause()

    async def run() -> tuple[dict[str, object], object]:
        task = asyncio.create_task(runtime.generate("held-mock", "hello", request_id="held-1"))
        await asyncio.sleep(0.05)
        assert runtime.health("held-mock")["lifecycle"] == "RUNNING"
        cancelled = runtime.cancel("held-1")
        return cancelled, await task

    cancelled, result = asyncio.run(run())
    assert cancelled["performed"] is True
    assert result.cancelled is True
    assert result.performed is False
    assert runtime.health("held-mock")["lifecycle"] == "IDLE"
    assert any(event.type == "model.cancelled" for event in events.list_events())


def test_engine_failure_removes_the_model_from_routing() -> None:
    engine = MockEngine()
    engine.allow("mock")
    runtime, _events, registry = _runtime(_mock("failing-mock"), engine=engine)
    assert runtime.load("failing-mock")["performed"] is True
    engine.fail_once()
    failed = asyncio.run(runtime.generate("failing-mock", "hello"))

    assert failed.code == "failed"
    assert runtime.health("failing-mock")["lifecycle"] == "FAILED"
    assert "failing-mock" not in runtime.available_ids()
    choice = ModelRouter(registry).choose(
        ["coding"],
        _snapshot(),
        mode="testing",
        available=runtime.available_ids(),
    )
    assert choice.model is None


def test_memory_and_video_memory_refusals_do_not_load() -> None:
    engine = MockEngine()
    engine.allow("mock")
    heavy = _mock(
        "heavy-local",
        local=True,
        requirements=ResourceRequirements(ram_mb=4096, ram_known=True, vram_mb=0, vram_known=True),
    )
    unknown = _mock(
        "unknown-ram",
        local=True,
        requirements=ResourceRequirements(ram_mb=0, ram_known=False, vram_mb=0, vram_known=True),
    )
    gpu = _mock(
        "gpu-local",
        local=True,
        requirements=ResourceRequirements(ram_mb=64, ram_known=True, vram_mb=8192, vram_known=True),
    )
    runtime, events, _registry = _runtime(
        [heavy, unknown, gpu],
        engine=engine,
        snapshot=_snapshot(available_mb=512, gpu_available=False),
    )

    memory = runtime.load("heavy-local")
    deferred = runtime.load("unknown-ram")
    video = runtime.load("gpu-local")

    assert memory["performed"] is False
    assert memory["code"] == "resources"
    assert memory["state"] == "AVAILABLE"
    assert deferred["reason"] == "local memory requirement is unknown"
    assert video["reason"] == "video memory requirement cannot be satisfied"
    assert "nvidia" not in str(video["reason"]).lower()
    assert "amd" not in str(video["reason"]).lower()
    assert runtime.health("gpu-local")["gpu"] == "none"
    assert all(event.type != "model.loaded" for event in events.list_events())


def test_local_adapter_uses_only_a_resident_model() -> None:
    seen: list[str] = []

    def transport(
        url: str, headers: dict[str, str], data: bytes, timeout: float
    ) -> tuple[int, bytes]:
        seen.append(url)
        assert b"pull" not in data
        if url.endswith("/models"):
            return 200, b'{"data":[{"id":"resident"}]}'
        if url.endswith("/chat/completions"):
            body = (
                b'{"model":"resident","choices":[{"finish_reason":"stop","message":'
                b'{"content":"hello"}}],"usage":{"prompt_tokens":1,"completion_tokens":1}}'
            )
            return 200, body
        raise AssertionError(url)

    runtime, events = _local_runtime(transport, model_name="resident")
    assert seen == ["http://127.0.0.1:9/v1/models"]
    assert runtime.health("local-resident")["gpu"] == "unknown"
    loaded = runtime.load("local-resident")
    assert loaded["performed"] is True
    assert seen == ["http://127.0.0.1:9/v1/models"]
    generated = asyncio.run(runtime.generate("local-resident", "hi"))
    assert generated.text == "hello"
    assert generated.performed is True
    assert all("pull" not in url and "huggingface" not in url for url in seen)
    assert any(event.type == "model.loaded" for event in events.list_events())


def test_local_adapter_reports_an_accelerator_only_when_the_server_does() -> None:
    def transport(
        url: str, headers: dict[str, str], data: bytes, timeout: float
    ) -> tuple[int, bytes]:
        return 200, b'{"accelerator":"vendor-a","data":[{"id":"resident"}]}'

    runtime, _events = _local_runtime(transport, model_name="resident")
    assert runtime.health("local-resident")["gpu"] == "vendor-a"


def test_missing_local_model_is_not_installed_and_does_not_connect_without_a_url() -> None:
    seen: list[str] = []

    def transport(
        url: str, headers: dict[str, str], data: bytes, timeout: float
    ) -> tuple[int, bytes]:
        seen.append(url)
        return 200, b'{"data":[{"id":"other"}]}'

    runtime, events = _local_runtime(transport, model_name="resident")
    missing = runtime.load("local-resident")
    assert missing["performed"] is False
    assert missing["reason"] == "model is not installed on the local runtime"
    assert seen == ["http://127.0.0.1:9/v1/models"]
    assert all(event.type != "model.loaded" for event in events.list_events())

    def explode(
        url: str, headers: dict[str, str], data: bytes, timeout: float
    ) -> tuple[int, bytes]:
        raise AssertionError(url)

    quiet, _quiet_events = _local_runtime(explode, model_name="resident", base_url="")
    refused = quiet.load("local-resident")
    assert refused["code"] == "unavailable"
    assert refused["reason"] == "local model runtime is not configured"


def test_load_records_a_live_worker_and_refuses_an_unknown_one() -> None:
    events = EventBus()
    agents = AgentLifecycle(events)
    agents.register("coding")
    workers = AgentRuntime(agents, events=events)
    worker = workers.begin(_manifest(), task_id="task-1", model_id="worker-mock")
    engine = MockEngine()
    engine.allow("mock")
    runtime, _model_events, registry = _runtime(
        _mock("worker-mock"),
        engine=engine,
        workers=lambda worker_id: worker_id == worker.worker_id,
    )

    refused = runtime.load("worker-mock", worker_id="missing")
    assert refused["code"] == "worker"
    assert refused["performed"] is False
    loaded = runtime.load("worker-mock", worker_id=worker.worker_id)
    assert loaded["performed"] is True
    assert runtime.health("worker-mock")["worker_id"] == worker.worker_id
    choice = ModelRouter(registry).choose(
        ["coding"],
        _snapshot(),
        mode="testing",
        available=runtime.available_ids(),
    )
    assert choice.model is not None
    assert choice.model.id == "worker-mock"


def test_lifecycle_tracker_does_not_load_weights() -> None:
    lifecycle = ModelLifecycle()
    model = _mock("tracker-mock")
    lifecycle.register(model, available=True)

    assert lifecycle.load(model.id)["performed"] is False
    assert lifecycle.state(model.id) is ModelLifecycleState.AVAILABLE
    with pytest.raises(InvalidModelTransition):
        lifecycle.transition(model.id, ModelLifecycleState.RUNNING)


def test_token_estimate_is_zero_for_empty_text() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("hi") == 1


def test_runtime_sources_do_not_spawn_or_download() -> None:
    banned = ("subprocess", "os.kill", "os.fork", "huggingface", "nvidia-smi", "/api/pull")
    for path in Path("core/models").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for word in banned:
            assert word not in text


def _runtime(
    models: ModelMetadata | list[ModelMetadata],
    *,
    engine: MockEngine,
    snapshot: ResourceSnapshot | None = None,
    workers: Callable[[str], bool] | None = None,
) -> tuple[ModelRuntime, EventBus, ModelRegistry]:
    registry = ModelRegistry()
    items = models if isinstance(models, list) else [models]
    for model in items:
        registry.register(model)
    events = EventBus()
    runtime = ModelRuntime(
        registry=registry,
        lifecycle=ModelLifecycle(),
        monitor=_Monitor(snapshot or _snapshot()),
        events=events,
        engines={"mock": engine},
        workers=workers,
    )
    runtime.prepare(available=lambda model: True)
    return runtime, events, registry


def _local_runtime(
    transport: Transport,
    *,
    model_name: str,
    base_url: str = "http://127.0.0.1:9",
) -> tuple[ModelRuntime, EventBus]:
    registry = ModelRegistry()
    registry.register(
        ModelMetadata(
            id="local-resident",
            provider="local",
            model_name=model_name,
            capabilities=["coding"],
            local=True,
            requirements=ResourceRequirements(
                ram_mb=64, ram_known=True, vram_mb=0, vram_known=True
            ),
        )
    )
    events = EventBus()
    engine = OpenAICompatibleEngine(base_url=base_url, timeout_seconds=1, transport=transport)
    runtime = ModelRuntime(
        registry=registry,
        lifecycle=ModelLifecycle(),
        monitor=_Monitor(_snapshot()),
        events=events,
        engines={"openai-compatible": engine},
    )
    runtime.prepare(available=lambda model: bool(base_url))
    return runtime, events


def _mock(
    model_id: str,
    *,
    local: bool = False,
    context_window: int | None = None,
    requirements: ResourceRequirements | None = None,
) -> ModelMetadata:
    return ModelMetadata(
        id=model_id,
        provider="mock",
        model_name="mock",
        capabilities=["coding"],
        local=local,
        context_window=context_window,
        requirements=requirements
        or ResourceRequirements(ram_mb=0, ram_known=True, vram_mb=0, vram_known=True),
    )


def _manifest() -> AgentManifest:
    return AgentManifest.model_validate(
        {
            "id": "coding",
            "name": "Coding",
            "version": "0.1.0",
            "description": "Writes files.",
            "capabilities": ["software_development"],
            "tools": ["filesystem.read"],
            "permissions": {"filesystem": ["workspace"]},
            "lifecycle": {"persistent": False, "startup": "on_demand", "shutdown": "after_task"},
            "max_workers": 2,
            "resources": {
                "ram_mb": 64,
                "vram_mb": 0,
                "cpu_threads": 1,
                "disk_mb": 0,
                "ram_known": True,
                "vram_known": True,
            },
        }
    )


def _snapshot(
    *,
    available_mb: float | None = 4096,
    gpu_available: bool | None = False,
) -> ResourceSnapshot:
    return ResourceSnapshot(
        cpu=CpuTelemetry(usage_percent=10),
        memory=MemoryTelemetry(total_mb=8192, available_mb=available_mb, used_mb=1024),
        gpu=GpuTelemetry(available=gpu_available),
        disk=DiskTelemetry(total_mb=1000, used_mb=100, available_mb=900),
        network=NetworkTelemetry(available=True),
    )


class _Monitor:
    def __init__(self, snapshot: ResourceSnapshot) -> None:
        self._snapshot = snapshot

    def snapshot(self) -> ResourceSnapshot:
        return self._snapshot
