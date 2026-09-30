"""Workers are lightweight instances of an agent definition."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from core.agents.lifecycle import AgentLifecycle, AgentState
from core.agents.manifest import AgentManifest
from core.agents.runtime import AgentRuntime
from core.compute.requirements import ResourceRequirements
from core.events.bus import EventBus
from core.workers.lifecycle import InvalidWorkerTransition, WorkerState
from core.workers.pool import Worker, WorkerLimit, WorkerPool, admit_worker


def test_a_worker_records_its_parent_and_walks_the_lifecycle() -> None:
    events = EventBus()
    runtime = _runtime(events)
    worker = runtime.begin(
        _manifest(),
        task_id="task-1",
        mission_id="mission-1",
        model_id="mock-default",
        trace_id="trace-1",
    )

    assert runtime._lifecycle.state("coding") is AgentState.RUNNING
    assert worker.worker_id
    assert worker.agent_id == "coding"
    assert worker.lifecycle is WorkerState.RUNNING
    assert worker.status == "RUNNING"
    assert worker.current_task == "task-1"
    assert worker.current_mission == "mission-1"
    assert worker.capabilities == ["software_development"]
    assert worker.model == "mock-default"
    assert worker.tools == ["filesystem.read"]
    assert worker.permissions == {"filesystem": ["workspace"]}
    assert worker.resources.ram_mb == 64
    assert worker.context == "task task-1"
    assert worker.trace_id == "trace-1"
    assert _worker_events(events) == [
        "worker.discovered",
        "worker.available",
        "worker.spawned",
        "worker.started",
    ]


def test_idle_workers_are_reused_and_on_demand_workers_terminate() -> None:
    pool = WorkerPool()
    first = _start(pool, task_id="task-1")
    assert pool.complete("coding") is not None
    again = _start(pool, task_id="task-2", trace_id="trace-2")

    assert again.worker_id == first.worker_id
    assert again.lifecycle is WorkerState.RUNNING
    assert again.current_task == "task-2"
    assert again.trace_id == "trace-2"
    assert [event for event, _worker in pool.events()].count("worker.reused") == 1
    assert pool.active("coding") == 1

    events = EventBus()
    runtime = _runtime(events)
    created = runtime.begin(_manifest(), task_id="task-1", trace_id="trace-1")
    runtime.succeed(_manifest())
    assert runtime.pool.get(created.worker_id).lifecycle is WorkerState.TERMINATED
    assert runtime._lifecycle.state("coding") is AgentState.AVAILABLE
    assert "worker.terminated" in _worker_events(events)

    persistent = _runtime(EventBus())
    kept = persistent.begin(_manifest(persistent=True), task_id="task-1", trace_id="trace-1")
    persistent.succeed(_manifest(persistent=True))
    assert persistent.pool.get(kept.worker_id).lifecycle is WorkerState.IDLE
    reused = persistent.begin(_manifest(persistent=True), task_id="task-2", trace_id="trace-2")
    assert reused.worker_id == kept.worker_id


def test_cancellation_failure_and_pause() -> None:
    pool = WorkerPool()
    worker = _start(pool, task_id="task-1")
    paused = pool.pause_running("coding")
    assert paused is not None
    assert paused.lifecycle is WorkerState.PAUSED
    resumed = pool.resume(worker.worker_id)
    assert resumed.lifecycle is WorkerState.RUNNING
    cancelled = pool.cancel(worker.worker_id)
    assert cancelled.lifecycle is WorkerState.IDLE
    assert cancelled.current_task is None

    running = _start(pool, task_id="task-3", max_workers=1)
    failed = pool.fail("coding")
    assert failed is not None
    assert failed.lifecycle is WorkerState.FAILED
    with pytest.raises(WorkerLimit):
        _start(pool, task_id="task-4", max_workers=1)
    terminated = pool.terminate(running.worker_id)
    assert terminated.lifecycle is WorkerState.TERMINATED
    with pytest.raises(InvalidWorkerTransition):
        pool.terminate(running.worker_id)
    replacement = _start(pool, task_id="task-5")
    assert replacement.worker_id != running.worker_id

    events = EventBus()
    runtime = _runtime(events)
    owned = runtime.begin(_manifest(), task_id="task-1", trace_id="trace-1")
    runtime.fail(_manifest(), retry=False)
    assert runtime.pool.get(owned.worker_id).lifecycle is WorkerState.TERMINATED
    assert "worker.failed" in _worker_events(events)
    assert runtime._lifecycle.state("coding") is AgentState.AVAILABLE


def test_resource_limits_wait_or_deny() -> None:
    assert admit_worker(active=2, max_workers=2, cpu_percent=None) == "DENY"
    assert admit_worker(active=0, max_workers=2, cpu_percent=99) == "WAIT"
    denied = admit_worker(
        active=0,
        max_workers=1,
        cpu_percent=None,
        requested_ram_mb=128,
        ram_limit_mb=64,
    )
    waiting = admit_worker(
        active=0,
        max_workers=2,
        cpu_percent=None,
        allocated_ram_mb=64,
        requested_ram_mb=64,
        ram_limit_mb=100,
    )
    assert denied == "DENY"
    assert waiting == "WAIT"

    pool = WorkerPool(ram_limit_mb=100)
    _start(pool, task_id="task-1", ram_mb=64)
    with pytest.raises(WorkerLimit) as limited:
        _start(pool, task_id="task-2", ram_mb=64, max_workers=4)
    assert limited.value.reason == "resources"

    busy = WorkerPool()
    with pytest.raises(WorkerLimit) as waiting:
        _start(busy, task_id="task-1", cpu_percent=99)
    assert waiting.value.reason == "cpu"


def test_concurrent_starts_stop_at_the_slot_limit() -> None:
    pool = WorkerPool()
    started: list[str] = []
    denied: list[str] = []
    barrier = threading.Barrier(8)

    def work(index: int) -> None:
        barrier.wait()
        try:
            worker = _start(pool, task_id=f"task-{index}", max_workers=3)
        except WorkerLimit:
            denied.append(str(index))
            return
        started.append(worker.worker_id)

    threads = [threading.Thread(target=work, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(started) == 3
    assert len(set(started)) == 3
    assert len(denied) == 5
    assert pool.active("coding") == 3


def test_many_workers_stay_inside_this_process(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("worker creation must not spawn a process")

    monkeypatch.setattr("os.fork", explode, raising=False)
    monkeypatch.setattr("subprocess.Popen", explode)
    pool = WorkerPool()
    created = [
        pool.start(
            agent_id=f"agent-{index}",
            max_workers=1,
            task_id=f"task-{index}",
            mission_id=None,
            model_id="mock",
            trace_id=f"trace-{index}",
            capabilities=["software_development"],
            context=f"task task-{index}",
        )
        for index in range(100)
    ]

    assert len({worker.worker_id for worker in created}) == 100
    assert all(worker.lifecycle is WorkerState.RUNNING for worker in created)
    assert len(pool.list_workers()) == 100
    for path in Path("core/workers").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "subprocess" not in text
        assert "os.fork" not in text
        assert "os.kill" not in text


def _runtime(events: EventBus) -> AgentRuntime:
    lifecycle = AgentLifecycle(events)
    lifecycle.register("coding")
    return AgentRuntime(lifecycle, events=events, pool=WorkerPool())


def _manifest(*, persistent: bool = False, max_workers: int = 2, ram_mb: int = 64) -> AgentManifest:
    return AgentManifest.model_validate(
        {
            "id": "coding",
            "name": "Coding",
            "version": "0.1.0",
            "description": "Writes files.",
            "capabilities": ["software_development"],
            "tools": ["filesystem.read"],
            "permissions": {"filesystem": ["workspace"]},
            "lifecycle": {
                "persistent": persistent,
                "startup": "on_demand",
                "shutdown": "never" if persistent else "after_task",
            },
            "max_workers": max_workers,
            "resources": {
                "ram_mb": ram_mb,
                "vram_mb": 0,
                "cpu_threads": 1,
                "disk_mb": 0,
                "ram_known": True,
                "vram_known": True,
            },
        }
    )


def _start(
    pool: WorkerPool,
    *,
    task_id: str,
    trace_id: str = "trace",
    max_workers: int = 2,
    ram_mb: int = 0,
    cpu_percent: float | None = None,
) -> Worker:
    worker = pool.start(
        agent_id="coding",
        max_workers=max_workers,
        task_id=task_id,
        mission_id="mission",
        model_id="mock",
        trace_id=trace_id,
        capabilities=["software_development"],
        tools=["filesystem.read"],
        permissions={"filesystem": ["workspace"]},
        resources=ResourceRequirements(ram_mb=ram_mb),
        context=f"task {task_id}",
        cpu_percent=cpu_percent,
    )
    return worker


def _worker_events(events: EventBus) -> list[str]:
    return [event.type for event in events.list_events() if event.type.startswith("worker.")]
