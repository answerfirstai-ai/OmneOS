"""Deterministic resource reservations and contention."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.agents.lifecycle import AgentLifecycle
from core.agents.registry import AgentRegistry
from core.agents.runtime import AgentRuntime
from core.compute.allocation import AllocationDecision
from core.compute.manager import (
    InvalidReservation,
    Reservation,
    ReservationKind,
    ReservationState,
    ResourceManager,
)
from core.compute.monitor import (
    CpuTelemetry,
    DiskTelemetry,
    GpuTelemetry,
    MemoryTelemetry,
    NetworkTelemetry,
    ResourceSnapshot,
    ThermalTelemetry,
)
from core.compute.requirements import ResourceRequirements
from core.compute.scheduler import ComputeScheduler
from core.events.bus import EventBus
from core.models.engines.mock import MockEngine
from core.models.lifecycle import ModelLifecycle
from core.models.registry import ModelMetadata, ModelRegistry
from core.models.runtime import ModelRuntime
from core.models.types import ProviderError
from core.orchestrator.scheduler import TaskScheduler
from core.orchestrator.store import TaskStore
from core.orchestrator.task import Task
from core.workers.pool import Worker, WorkerLimit, WorkerPool


def test_cpu_worker_and_gpu_worker_run_together() -> None:
    manager = _manager(_machine())
    pool = WorkerPool(resources=manager)

    cpu_worker = _start(
        pool,
        agent_id="worker-a",
        resources=ResourceRequirements(cpu_threads=4, ram_mb=4096),
    )
    gpu_worker = _start(
        pool,
        agent_id="worker-b",
        resources=ResourceRequirements(gpu=True, vram_mb=8192, cpu_threads=0),
    )

    assert cpu_worker.lifecycle.value == "RUNNING"
    assert gpu_worker.lifecycle.value == "RUNNING"
    assert manager.held().cpu_threads == 4
    assert manager.held().ram_mb == 4096
    assert manager.held().vram_mb == 8192
    assert manager.held().gpus == 1
    assert {item.state for item in _holding(manager)} == {ReservationState.RUN}


def test_second_vram_claim_waits_until_release() -> None:
    manager = _manager(_machine())
    pool = WorkerPool(resources=manager)
    _start(
        pool,
        agent_id="worker-b",
        resources=ResourceRequirements(gpu=True, vram_mb=8192, cpu_threads=0),
    )
    with pytest.raises(WorkerLimit) as caught:
        _start(
            pool,
            agent_id="worker-c",
            resources=ResourceRequirements(gpu=True, vram_mb=8192, cpu_threads=0),
        )

    assert caught.value.reason == "resources"
    assert manager.held().vram_mb == 8192
    assert len(pool.list_workers()) == 1
    waiting = _owned(manager, "worker-c")
    assert waiting.decision is AllocationDecision.WAIT
    assert waiting.reason == "video memory is reserved"
    assert waiting.state is ReservationState.REQUEST

    pool.terminate(pool.list_workers()[0].worker_id)
    assert manager.held().vram_mb == 0
    started = _start(
        pool,
        agent_id="worker-c",
        resources=ResourceRequirements(gpu=True, vram_mb=8192, cpu_threads=0),
    )
    assert started.lifecycle.value == "RUNNING"
    assert manager.held().vram_mb == 8192


def test_cpu_request_beyond_the_machine_is_denied_without_a_hold() -> None:
    manager = _manager(_machine())
    denied = _ask(manager, ResourceRequirements(cpu_threads=16), owner="wide")

    assert denied.decision is AllocationDecision.DENY
    assert denied.reason == "cpu requirement exceeds the machine"
    assert denied.state is ReservationState.REQUEST
    assert manager.held().cpu_threads == 0
    with pytest.raises(InvalidReservation):
        manager.run(denied.id)


def test_unknown_cpu_count_defers_a_multithreaded_request() -> None:
    manager = _manager(_machine(count=None))
    deferred = _ask(manager, ResourceRequirements(cpu_threads=4), owner="unsized")

    assert deferred.decision is AllocationDecision.DEFER
    assert deferred.reason == "cpu capacity is unknown"
    assert manager.held().cpu_threads == 0


def test_unknown_gpu_telemetry_defers_without_a_vendor() -> None:
    manager = _manager(_machine(gpu=None, gpu_count=None, vram_total=None, vram_used=None))
    requirements = ResourceRequirements(gpu=True, vram_mb=8192, vram_known=True)
    deferred = _ask(manager, requirements, owner="gpu-worker")

    assert deferred.decision is AllocationDecision.DEFER
    assert deferred.reason == "gpu telemetry is unavailable"
    assert "nvidia" not in deferred.reason
    assert "amd" not in deferred.reason
    assert deferred.state is ReservationState.REQUEST
    assert manager.held().vram_mb == 0
    assert manager.held().gpus == 0


def test_absent_gpu_denies_or_selects_another_route() -> None:
    snapshot = _machine(gpu=False, gpu_count=0, vram_total=None, vram_used=None, gpu_usage=None)
    requirements = ResourceRequirements(gpu=True, vram_mb=1024)
    manager = _manager(snapshot)
    denied = _ask(manager, requirements, cloud=False)
    cloud = _ask(manager, requirements, local=True, cloud=True)
    other = _ask(manager, requirements, local=False, cloud=True)

    assert denied.decision is AllocationDecision.DENY
    assert denied.reason == "video memory requirement cannot be satisfied"
    assert cloud.decision is AllocationDecision.USE_CLOUD
    assert cloud.reason == "local video memory cannot satisfy the requirement"
    assert other.decision is AllocationDecision.USE_DIFFERENT_MODEL
    assert denied.state is ReservationState.REQUEST
    assert manager.held().gpus == 0


def test_memory_contention_waits_and_an_impossible_request_is_denied() -> None:
    manager = _manager(_machine(available_ram=6000))
    first = _ask(manager, ResourceRequirements(ram_mb=4000), owner="first")
    second = _ask(manager, ResourceRequirements(ram_mb=4000), owner="second")

    assert first.decision is AllocationDecision.ALLOW
    assert first.state is ReservationState.RESERVE
    assert second.decision is AllocationDecision.WAIT
    assert second.reason == "memory is reserved"
    assert manager.held().ram_mb == 4000

    unknown = _ask(
        _manager(_machine()),
        ResourceRequirements(ram_mb=0, ram_known=False),
        owner="local-model",
    )
    assert unknown.decision is AllocationDecision.DEFER
    assert unknown.reason == "local memory requirement is unknown"

    missing = _ask(
        _manager(_machine(available_ram=None)),
        ResourceRequirements(ram_mb=64),
        owner="unmeasured",
    )
    assert missing.decision is AllocationDecision.DEFER
    assert missing.reason == "memory telemetry is unknown"

    denied = _ask(
        _manager(_machine(available_ram=1000)),
        ResourceRequirements(ram_mb=4000),
        owner="too-big",
    )
    assert denied.decision is AllocationDecision.DENY
    assert denied.reason == "memory requirement exceeds available memory"
    assert denied.state is ReservationState.REQUEST


def test_disk_unknown_defers_and_oversize_denies() -> None:
    unknown = _ask(
        _manager(_machine(disk=None)),
        ResourceRequirements(disk_mb=10),
        owner="disk",
    )
    denied = _ask(
        _manager(_machine(disk=100)),
        ResourceRequirements(disk_mb=200),
        owner="disk",
    )
    manager = _manager(_machine(disk=1000))
    first = _ask(manager, ResourceRequirements(disk_mb=600), owner="first")
    second = _ask(manager, ResourceRequirements(disk_mb=600), owner="second")

    assert unknown.decision is AllocationDecision.DEFER
    assert unknown.reason == "disk telemetry is unknown"
    assert denied.decision is AllocationDecision.DENY
    assert denied.reason == "disk requirement exceeds available disk"
    assert first.decision is AllocationDecision.ALLOW
    assert second.decision is AllocationDecision.WAIT
    assert second.reason == "disk is reserved"
    assert manager.held().disk_mb == 600


def test_thermal_waits_only_for_a_real_high_reading() -> None:
    hot = _ask(_manager(_machine(thermal=99)), ResourceRequirements(cpu_threads=2), owner="hot")
    single = _ask(
        _manager(_machine(thermal=99)),
        ResourceRequirements(cpu_threads=1),
        owner="single",
    )
    missing = _ask(
        _manager(_machine(thermal=None)),
        ResourceRequirements(cpu_threads=4),
        owner="unmeasured",
    )

    assert hot.decision is AllocationDecision.WAIT
    assert hot.reason == "thermal reading is high"
    assert single.decision is AllocationDecision.ALLOW
    assert missing.decision is AllocationDecision.ALLOW


def test_gpu_utilization_waits_only_when_measured() -> None:
    busy = _ask(
        _manager(_machine(gpu_usage=95)),
        ResourceRequirements(gpu=True, vram_mb=128),
        owner="busy",
    )
    unknown = _ask(
        _manager(_machine(gpu_usage=None)),
        ResourceRequirements(gpu=True, vram_mb=128),
        owner="quiet",
    )

    assert busy.decision is AllocationDecision.WAIT
    assert busy.reason == "gpu utilization is above 90 percent"
    assert unknown.decision is AllocationDecision.ALLOW


def test_reservation_moves_through_request_reserve_run_and_release() -> None:
    events = EventBus()
    manager = _manager(_machine(), events)
    allowed = _ask(manager, ResourceRequirements(cpu_threads=4, ram_mb=4096), owner="worker-a")

    assert allowed.state is ReservationState.RESERVE
    running = manager.run(allowed.id)
    assert running.state is ReservationState.RUN
    assert manager.held().ram_mb == 4096
    released = manager.release(allowed.id)
    assert released.state is ReservationState.RELEASE
    assert manager.held().ram_mb == 0
    assert manager.held().cpu_threads == 0
    with pytest.raises(InvalidReservation):
        manager.run(allowed.id)

    names = [event.type for event in events.list_events()]
    assert names == [
        "compute.requested",
        "compute.reserved",
        "compute.running",
        "compute.released",
    ]
    payload = events.list_events()[0].payload
    assert payload["owner"] == "worker-a"
    assert payload["decision"] == "ALLOW"
    assert "vram_total_mb" not in payload


def test_active_holds_never_exceed_measured_capacity() -> None:
    manager = _manager(_machine(available_ram=6000, count=8))
    admitted: list[str] = []
    for index in range(4):
        reservation = _ask(
            manager,
            ResourceRequirements(ram_mb=2000, cpu_threads=0),
            owner=f"ram-{index}",
        )
        if reservation.decision is AllocationDecision.ALLOW:
            manager.run(reservation.id)
            admitted.append(reservation.id)
    assert len(admitted) == 3
    assert manager.held().ram_mb == 6000

    for index in range(3):
        reservation = _ask(manager, ResourceRequirements(cpu_threads=4), owner=f"cpu-{index}")
        if reservation.decision is AllocationDecision.ALLOW:
            manager.run(reservation.id)
    assert manager.held().cpu_threads == 8

    manager.release(admitted[0])
    follow = _ask(manager, ResourceRequirements(ram_mb=2000), owner="after-release")
    assert follow.decision is AllocationDecision.ALLOW
    assert manager.held().ram_mb == 6000


def test_exclusive_gpu_without_vram_waits_for_the_device() -> None:
    manager = _manager(_machine())
    first = _ask(manager, ResourceRequirements(gpu=True, vram_mb=0), owner="one")
    second = _ask(manager, ResourceRequirements(gpu=True, vram_mb=0), owner="two")

    assert first.decision is AllocationDecision.ALLOW
    assert second.decision is AllocationDecision.WAIT
    assert second.reason == "gpu is reserved"
    assert manager.held().gpus == 1


def test_model_loads_share_the_ledger_with_workers() -> None:
    manager = _manager(_machine())
    pool = WorkerPool(resources=manager)
    worker = _start(
        pool,
        agent_id="worker-b",
        resources=ResourceRequirements(gpu=True, vram_mb=8192, cpu_threads=0),
    )
    runtime = _runtime(manager, "shared-model", vram_mb=8192)
    refused = runtime.load("shared-model")

    assert refused["performed"] is False
    assert refused["code"] == "resources"
    assert refused["reason"] == "video memory is reserved"
    assert manager.held().vram_mb == 8192

    pool.terminate(worker.worker_id)
    loaded = runtime.load("shared-model")
    assert loaded["performed"] is True
    assert manager.held().vram_mb == 8192
    assert _owned(manager, "shared-model").state is ReservationState.RUN

    unloaded = runtime.unload("shared-model")
    assert unloaded["performed"] is True
    assert manager.held().vram_mb == 0
    assert manager.held().gpus == 0


def test_failed_model_load_releases_the_hold(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _manager(_machine())
    engine = MockEngine()
    engine.allow("wide")
    runtime = _runtime(manager, "wide-model", vram_mb=4096, engine=engine, model_name="wide")

    def boom(_model_name: str) -> None:
        raise ProviderError("model runtime failed", code="runtime", provider="mock")

    monkeypatch.setattr(engine, "load", boom)
    failed = runtime.load("wide-model")

    assert failed["performed"] is False
    assert failed["code"] == "runtime"
    assert manager.held().vram_mb == 0
    assert _owned(manager, "wide-model").state is ReservationState.RELEASE


def test_reused_worker_does_not_take_a_second_hold() -> None:
    manager = _manager(_machine())
    pool = WorkerPool(resources=manager)
    requirements = ResourceRequirements(ram_mb=1000)
    first = _start(pool, agent_id="coding", resources=requirements)
    assert manager.held().ram_mb == 1000
    assert pool.complete("coding") is not None

    again = _start(pool, agent_id="coding", resources=requirements, task_id="task-2")
    assert again.worker_id == first.worker_id
    assert manager.held().ram_mb == 1000
    pool.terminate(again.worker_id)
    assert manager.held().ram_mb == 0


def test_task_scheduler_keeps_only_requests_that_fit(tmp_path: Path) -> None:
    snapshot = _machine(available_ram=6000)
    monitor = _Monitor(snapshot)
    manager = ResourceManager(monitor)
    events = EventBus()
    lifecycle = AgentLifecycle(events)
    scheduler = TaskScheduler(
        store=TaskStore(tmp_path / "tasks.sqlite"),
        executor=_Unused(),
        events=events,
        monitor=monitor,
        compute=ComputeScheduler(monitor, manager=manager),
        agents=AgentRegistry(),
        runtime=AgentRuntime(lifecycle, events=events),
        lifecycle=lifecycle,
        max_parallel=4,
    )
    ready = [
        _task("fits", ram_mb=4000),
        _task("contended", ram_mb=4000),
        _task("too-wide", threads=16),
        _task("small", ram_mb=1000),
    ]

    batch = scheduler._select_batch(ready)

    assert [task.id for task in batch] == ["fits", "small"]
    assert manager.held().ram_mb == 5000
    assert _owned(manager, "contended").decision is AllocationDecision.WAIT
    assert _owned(manager, "too-wide").decision is AllocationDecision.DENY
    assert _owned(manager, "too-wide").state is ReservationState.REQUEST
    for reservation in _holding(manager):
        manager.release(reservation.id)
    assert manager.held().ram_mb == 0


def test_status_preserves_unknown_measurements() -> None:
    snapshot = _machine(
        cpu=None,
        count=None,
        available_ram=None,
        gpu=None,
        gpu_count=None,
        gpu_usage=None,
        vram_total=None,
        vram_used=None,
        disk=None,
        thermal=None,
        network=False,
    )
    view = _manager(snapshot).status(snapshot)

    assert view["cpu"] == {"usage_percent": None, "count": None}
    assert view["memory"]["available_mb"] is None
    assert view["gpu"]["available"] is None
    assert view["gpu"]["count"] is None
    assert view["gpu"]["vram_total_mb"] is None
    assert view["disk"]["available_mb"] is None
    assert view["thermal"] == {"celsius": None}
    assert view["network"] == {"available": False, "interfaces": []}
    assert view["held"] == {
        "cpu_threads": 0,
        "ram_mb": 0,
        "vram_mb": 0,
        "disk_mb": 0,
        "gpus": 0,
    }
    assert view["reservations"] == []


class _Monitor:
    def __init__(self, snapshot: ResourceSnapshot) -> None:
        self._snapshot = snapshot

    def snapshot(self) -> ResourceSnapshot:
        return self._snapshot


class _Unused:
    """Stand-in for the executor. Selection does not run a task."""


def _manager(snapshot: ResourceSnapshot, events: EventBus | None = None) -> ResourceManager:
    return ResourceManager(_Monitor(snapshot), events=events)


def _ask(
    manager: ResourceManager,
    requirements: ResourceRequirements,
    *,
    owner: str = "owner",
    kind: ReservationKind = "worker",
    local: bool = True,
    cloud: bool = False,
) -> Reservation:
    return manager.request(
        requirements,
        owner=owner,
        kind=kind,
        local=local,
        cloud_available=cloud,
    )


def _records(manager: ResourceManager) -> list[dict[str, object]]:
    reservations = manager.status()["reservations"]
    assert isinstance(reservations, list)
    return [item for item in reservations if isinstance(item, dict)]


def _holding(manager: ResourceManager) -> list[Reservation]:
    return [
        manager.get(str(item["id"]))
        for item in _records(manager)
        if item["state"] in {"RESERVE", "RUN"}
    ]


def _owned(manager: ResourceManager, owner: str) -> Reservation:
    matches = [manager.get(str(item["id"])) for item in _records(manager) if item["owner"] == owner]
    assert matches
    return matches[-1]


def _machine(
    *,
    cpu: float | None = 10,
    count: int | None = 8,
    available_ram: float | None = 16384,
    gpu: bool | None = True,
    gpu_count: int | None = 1,
    gpu_usage: float | None = 10,
    vram_total: float | None = 8192,
    vram_used: float | None = 0,
    disk: float | None = 99000,
    thermal: float | None = 40,
    network: bool = True,
) -> ResourceSnapshot:
    return ResourceSnapshot(
        cpu=CpuTelemetry(usage_percent=cpu, count=count),
        memory=MemoryTelemetry(
            total_mb=None if available_ram is None else 32768,
            available_mb=available_ram,
            used_mb=None,
        ),
        gpu=GpuTelemetry(
            available=gpu,
            count=gpu_count,
            usage_percent=gpu_usage,
            vram_total_mb=vram_total,
            vram_used_mb=vram_used,
        ),
        disk=DiskTelemetry(
            total_mb=None if disk is None else disk + 1000,
            used_mb=None if disk is None else 1000,
            available_mb=disk,
        ),
        network=NetworkTelemetry(available=network),
        thermal=ThermalTelemetry(celsius=thermal),
    )


def _start(
    pool: WorkerPool,
    *,
    agent_id: str,
    resources: ResourceRequirements,
    task_id: str = "task-1",
) -> Worker:
    return pool.start(
        agent_id=agent_id,
        max_workers=4,
        task_id=task_id,
        mission_id="mission",
        model_id="mock",
        trace_id="trace",
        resources=resources,
    )


def _runtime(
    manager: ResourceManager,
    model_id: str,
    *,
    vram_mb: int,
    engine: MockEngine | None = None,
    model_name: str = "mock",
) -> ModelRuntime:
    selected = engine or MockEngine()
    selected.allow(model_name)
    registry = ModelRegistry()
    registry.register(
        ModelMetadata(
            id=model_id,
            provider="mock",
            model_name=model_name,
            capabilities=["coding"],
            local=True,
            requirements=ResourceRequirements(ram_mb=64, vram_mb=vram_mb, gpu=True),
        )
    )
    runtime = ModelRuntime(
        registry=registry,
        lifecycle=ModelLifecycle(),
        monitor=_Monitor(_machine()),
        events=EventBus(),
        engines={"mock": selected},
        resources=manager,
    )
    runtime.prepare(available=lambda _model: True)
    return runtime


def _task(task_id: str, *, ram_mb: int = 0, threads: int = 1) -> Task:
    now = datetime.now(UTC)
    return Task(
        id=task_id,
        objective=task_id,
        created_at=now,
        updated_at=now,
        required_resources=ResourceRequirements(ram_mb=ram_mb, cpu_threads=threads),
    )
