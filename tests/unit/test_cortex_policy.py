"""Route class selection and the recorded cortex cycle."""

from __future__ import annotations

from pathlib import Path

from tests.conftest import ROOT
from tests.support import runtime_settings

from core.api.runtime import build_OMNE
from core.compute.allocation import AllocationDecision, AllocationRequest, allocate
from core.compute.monitor import (
    CpuTelemetry,
    DiskTelemetry,
    GpuTelemetry,
    MemoryTelemetry,
    NetworkTelemetry,
    ResourceSnapshot,
)
from core.compute.requirements import ResourceRequirements
from core.cortex.cycle import STAGES
from core.intent.engine import Intent, IntentEngine
from core.models.policy import (
    RouteSituation,
    choose_route,
    complexity_of,
    gpu_is_overloaded,
    is_private_request,
)
from core.models.registry import ModelMetadata, ModelRegistry
from core.models.router import ModelRouter
from core.orchestrator.task import TaskStatus


def test_simple_route_excludes_nvidia() -> None:
    policy = choose_route(
        RouteSituation(
            complexity="simple",
            private=False,
            network="unknown",
            gpu_overloaded=False,
            local_available=True,
            cloud_available=True,
            mock_available=True,
        )
    )

    assert policy.name == "simple_local"
    assert policy.providers == ["local", "mock"]
    assert "nvidia" not in policy.providers


def test_complex_auto_prefers_nvidia_reasoning_before_nvidia_fast() -> None:
    intent = Intent(intent="create_website", desired_outcome="html_file")
    assert complexity_of(intent, "build a small website") == "complex"
    policy = choose_route(
        RouteSituation(
            complexity="complex",
            private=False,
            network="unknown",
            gpu_overloaded=False,
            local_available=True,
            cloud_available=True,
            mock_available=True,
        )
    )
    router = _router()
    ordered = router.order(
        ["reasoning"],
        _snapshot(),
        route="auto",
        available=_ids(),
        policy=policy,
    )

    assert policy.name == "complex_cloud"
    assert policy.prefer_strong is True
    assert policy.providers[0] == "nvidia"
    names = [model.id for model in ordered]
    assert names.index("nvidia-reasoning") < names.index("nvidia-fast")


def test_private_and_network_down_exclude_nvidia() -> None:
    private = choose_route(
        RouteSituation(
            complexity="complex",
            private=True,
            network="unknown",
            gpu_overloaded=True,
            local_available=True,
            cloud_available=True,
            mock_available=True,
        )
    )
    offline = choose_route(
        RouteSituation(
            complexity="complex",
            private=False,
            network="down",
            gpu_overloaded=True,
            local_available=True,
            cloud_available=True,
            mock_available=True,
        )
    )

    assert private.name == "private_local"
    assert offline.name == "offline_local"
    assert "nvidia" not in private.providers
    assert "nvidia" not in offline.providers
    assert is_private_request("keep this private")
    assert is_private_request("confidential notes")
    assert is_private_request("local only")
    assert is_private_request("on this machine")
    assert is_private_request("do not send this")
    assert not is_private_request("write file notes.txt with content hello")
    assert not is_private_request("a privateer ship")


def test_unknown_network_and_gpu_are_not_treated_as_measured() -> None:
    policy = choose_route(
        RouteSituation(
            complexity="complex",
            private=False,
            network="unknown",
            gpu_overloaded=False,
            local_available=False,
            cloud_available=True,
            mock_available=True,
        )
    )
    idle = _snapshot()
    unknown = _snapshot(usage=None, used=None, total=None)

    assert policy.name == "complex_cloud"
    assert not gpu_is_overloaded(idle)
    assert not gpu_is_overloaded(unknown)
    assert gpu_is_overloaded(_snapshot(usage=90))
    assert not gpu_is_overloaded(_snapshot(usage=89.9))
    assert gpu_is_overloaded(_snapshot(usage=None, used=900, total=1000))
    assert not gpu_is_overloaded(_snapshot(usage=None, used=899, total=1000))


def test_research_workspace_stays_on_the_local_tool_path() -> None:
    text = "research why the design should change"
    intent = IntentEngine().interpret(text)
    complexity = complexity_of(intent, text)
    policy = choose_route(
        RouteSituation(
            complexity=complexity,
            private=False,
            network="unknown",
            gpu_overloaded=False,
            local_available=True,
            cloud_available=True,
            mock_available=True,
        )
    )

    assert intent.intent == "research.workspace"
    assert complexity == "simple"
    assert policy.name == "simple_local"
    assert "nvidia" not in policy.providers


def test_gpu_overload_prefers_nvidia_over_a_local_model_that_fits() -> None:
    snapshot = _snapshot(usage=95, used=1000, total=16000)
    local = ModelMetadata(
        id="local-small",
        provider="local",
        model_name="small",
        capabilities=["reasoning"],
        local=True,
        priority=1,
        requirements=ResourceRequirements(ram_mb=128, vram_mb=0, ram_known=True, vram_known=True),
    )
    registry = ModelRegistry()
    registry.discover(ROOT / "models" / "manifests")
    registry.register(local)
    router = ModelRouter(registry)
    decision, _reason = allocate(
        snapshot,
        AllocationRequest(requirements=local.requirements, local=True, cloud_available=True),
    )
    available = {model.id for model in registry.enabled()}
    overloaded = choose_route(
        RouteSituation(
            complexity="simple",
            private=False,
            network="unknown",
            gpu_overloaded=True,
            local_available=True,
            cloud_available=True,
            mock_available=True,
        )
    )
    quiet = choose_route(
        RouteSituation(
            complexity="simple",
            private=False,
            network="unknown",
            gpu_overloaded=False,
            local_available=True,
            cloud_available=True,
            mock_available=True,
        )
    )
    cloud = router.order(
        ["reasoning"], snapshot, route="auto", available=available, policy=overloaded
    )
    local_route = router.order(
        ["reasoning"], snapshot, route="auto", available=available, policy=quiet
    )

    assert decision is AllocationDecision.ALLOW
    assert gpu_is_overloaded(snapshot)
    assert overloaded.name == "gpu_cloud"
    assert cloud[0].provider == "nvidia"
    assert all(model.provider != "local" for model in cloud)
    assert local_route[0].id == "local-small"


def test_explicit_mock_route_ignores_policy() -> None:
    policy = choose_route(
        RouteSituation(
            complexity="complex",
            private=False,
            network="unknown",
            gpu_overloaded=False,
            local_available=True,
            cloud_available=True,
            mock_available=True,
        )
    )
    ordered = _router().order(
        ["reasoning"],
        _snapshot(),
        route="mock",
        available=_ids(),
        policy=policy,
    )

    assert policy.providers[0] == "nvidia"
    assert [model.id for model in ordered] == ["mock-default"]
    assert all(model.provider == "mock" for model in ordered)


def test_nothing_available_falls_back_to_mock() -> None:
    policy = choose_route(
        RouteSituation(
            complexity="complex",
            private=False,
            network="unknown",
            gpu_overloaded=False,
            local_available=False,
            cloud_available=False,
            mock_available=True,
        )
    )

    assert policy.name == "fallback"
    assert "nvidia" not in policy.providers
    assert policy.providers[-1] == "mock"


def test_ambiguous_request_does_not_change_privacy() -> None:
    engine = IntentEngine()
    asked = engine.interpret("delete the project")
    private = engine.interpret("write file notes.txt with content keep this private")

    assert asked.ambiguous is True
    assert asked.privacy == "local"
    assert private.intent == "filesystem.write"
    assert private.privacy == "private"


def test_testing_execute_records_simple_local_cycle(tmp_path: Path) -> None:
    omne = build_OMNE(runtime_settings(tmp_path))
    task = omne.execute_sync("write file notes.txt with content hello from OMNE")
    mission = next(item for item in omne.list_missions() if item.task_id == task.id)
    cortex = mission.metadata["cortex"]
    routed = [event for event in omne.list_events() if event.type == "cortex.routed"]
    nvidia_done = [
        event
        for event in omne.list_events()
        if event.type == "model.completed" and event.payload.get("provider") == "nvidia"
    ]

    assert task.status is TaskStatus.COMPLETED
    assert cortex["policy"] == "simple_local"
    assert cortex["complexity"] == "simple"
    assert cortex["network"] == "unknown"
    assert cortex["stages"] == list(STAGES)
    assert cortex["completed"] == list(STAGES)
    assert cortex["plan"] == ["write"]
    assert cortex["selected_provider"] == "mock"
    assert "nvidia" not in cortex["providers"]
    assert len(routed) == 1
    assert routed[0].mission_id == mission.id
    assert routed[0].payload["policy"] == "simple_local"
    assert routed[0].payload["selected_provider"] == "mock"
    assert nvidia_done == []
    assert omne.network_view()["internet"] == "unreachable"


def _router() -> ModelRouter:
    registry = ModelRegistry()
    registry.discover(ROOT / "models" / "manifests")
    return ModelRouter(registry)


def _ids() -> set[str]:
    registry = ModelRegistry()
    registry.discover(ROOT / "models" / "manifests")
    return {model.id for model in registry.enabled()}


def _snapshot(
    *,
    usage: float | None = 10,
    used: float | None = 1000,
    total: float | None = 16000,
) -> ResourceSnapshot:
    return ResourceSnapshot(
        cpu=CpuTelemetry(usage_percent=10, count=4),
        memory=MemoryTelemetry(total_mb=16000, available_mb=8000, used_mb=8000),
        gpu=GpuTelemetry(
            available=True,
            count=1,
            usage_percent=usage,
            vram_used_mb=used,
            vram_total_mb=total,
        ),
        disk=DiskTelemetry(total_mb=1000, used_mb=100, available_mb=900),
        network=NetworkTelemetry(available=True),
    )
