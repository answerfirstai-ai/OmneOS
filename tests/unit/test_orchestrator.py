"""Planning, parallel scheduling, recovery, and confirmation."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from tests.support import runtime_settings

from core.agents.lifecycle import AgentLifecycle
from core.agents.registry import AgentRegistry
from core.agents.runtime import AgentRuntime
from core.api.runtime import build_OMNE
from core.compute.monitor import SystemMonitor
from core.compute.requirements import ResourceRequirements
from core.compute.scheduler import ComputeScheduler
from core.events.bus import EventBus
from core.orchestrator.scheduler import TaskScheduler
from core.orchestrator.store import TaskStore
from core.orchestrator.task import PlannedCall, Task, TaskStatus, TaskStep


def test_write_file_objective_completes(tmp_path: Path) -> None:
    OMNE = build_OMNE(runtime_settings(tmp_path))

    task = OMNE.execute_sync("write file notes.txt with content hello from OMNE")

    assert task.status is TaskStatus.COMPLETED
    assert (tmp_path / "workspace" / "notes.txt").read_text(encoding="utf-8") == "hello from OMNE"
    assert all(event.type != "model.loaded" for event in OMNE.list_events())


def test_website_steps_run_in_dependency_order(tmp_path: Path) -> None:
    OMNE = build_OMNE(runtime_settings(tmp_path))

    task = OMNE.execute_sync("build a small website")
    children = [child for child in OMNE.list_tasks() if child.parent_task == task.id]
    order = {str(child.metadata.get("key")): child.updated_at for child in children}

    assert task.status is TaskStatus.COMPLETED
    assert (
        "<html"
        in (tmp_path / "workspace" / "site" / "index.html").read_text(encoding="utf-8").lower()
    )
    assert (
        order["research"]
        <= order["design"]
        <= order["coding"]
        <= order["testing"]
        <= order["review"]
    )


def test_terminal_waits_for_confirmation_and_can_be_denied(tmp_path: Path) -> None:
    OMNE = build_OMNE(runtime_settings(tmp_path))

    waiting = OMNE.execute_sync("run terminal command touch proof.txt")
    denied = OMNE.confirm_sync(waiting.id, approved=False)

    assert waiting.status is TaskStatus.WAITING
    assert denied.status is TaskStatus.FAILED
    assert not (tmp_path / "workspace" / "proof.txt").exists()


def test_terminal_runs_after_confirmation(tmp_path: Path) -> None:
    OMNE = build_OMNE(runtime_settings(tmp_path))

    waiting = OMNE.execute_sync("run terminal command echo confirmed")
    finished = OMNE.confirm_sync(waiting.id, approved=True)
    child = next(task for task in OMNE.list_tasks() if task.parent_task == finished.id)

    assert finished.status is TaskStatus.COMPLETED
    assert "confirmed" in str(child.result)


def test_retry_then_escalates(tmp_path: Path) -> None:
    settings = runtime_settings(tmp_path)
    OMNE = build_OMNE(settings)
    now = datetime.now(UTC)
    parent_id = str(uuid4())
    child_id = str(uuid4())
    resources = ResourceRequirements(ram_mb=64, cpu_threads=1, ram_known=True, vram_known=True)
    parent = Task(
        id=parent_id,
        objective="read a missing file",
        created_at=now,
        updated_at=now,
        retry_limit=1,
        steps=[
            TaskStep(
                id=child_id,
                objective="read missing",
                status=TaskStatus.QUEUED,
                required_tools=["filesystem.read"],
            )
        ],
        metadata={"role": "parent"},
    )
    child = Task(
        id=child_id,
        objective="read missing",
        created_at=now,
        updated_at=now,
        parent_task=parent_id,
        assigned_agent="coding",
        assigned_model="mock-default",
        required_tools=["filesystem.read"],
        required_resources=resources,
        calls=[
            PlannedCall(kind="tool", tool_id="filesystem.read", arguments={"path": "missing.txt"})
        ],
        retry_limit=1,
        metadata={"role": "child", "key": "read", "exclusive": False},
    )
    OMNE._store.save(parent)
    OMNE._store.save(child)

    finished = asyncio.run(OMNE._scheduler.execute_parent(parent_id))
    failed = OMNE.get_task(child_id)

    assert finished.status is TaskStatus.FAILED
    assert failed.status is TaskStatus.FAILED
    assert failed.retry_count == 1
    assert any(error.code == "escalated" for error in failed.errors)


def test_independent_tasks_can_overlap_and_shared_agents_cannot(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks.sqlite")
    events = EventBus()
    agents = AgentRegistry()
    lifecycle = AgentLifecycle(events)
    lifecycle.register("system")
    lifecycle.register("research")

    class _Executor:
        def __init__(self) -> None:
            self.active = 0
            self.max_active = 0

        async def run(self, task: Task) -> Task:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(0.05)
            self.active -= 1
            current = store.get(task.id)
            current = store.transition(current, TaskStatus.PLANNING)
            current = store.transition(current, TaskStatus.RUNNING)
            current = store.transition(current, TaskStatus.VERIFYING)
            return store.transition(current, TaskStatus.COMPLETED, result={"ok": True})

    def schedule(executor: _Executor, assignments: list[str]) -> Task:
        now = datetime.now(UTC)
        parent_id = str(uuid4())
        children = []
        steps = []
        for agent_id in assignments:
            child_id = str(uuid4())
            child = Task(
                id=child_id,
                objective=agent_id,
                created_at=now,
                updated_at=now,
                parent_task=parent_id,
                assigned_agent=agent_id,
                required_resources=ResourceRequirements(ram_mb=64, ram_known=True, vram_known=True),
                metadata={"exclusive": False, "key": child_id},
            )
            children.append(child)
            steps.append(TaskStep(id=child_id, objective=agent_id, status=TaskStatus.QUEUED))
        parent = Task(
            id=parent_id,
            objective="parallel",
            created_at=now,
            updated_at=now,
            steps=steps,
            metadata={"role": "parent"},
        )
        store.save(parent)
        for child in children:
            store.save(child)
        scheduler = TaskScheduler(
            store=store,
            executor=executor,  # type: ignore[arg-type]
            events=events,
            monitor=SystemMonitor(sample_seconds=0),
            compute=ComputeScheduler(SystemMonitor(sample_seconds=0)),
            agents=agents,
            runtime=AgentRuntime(lifecycle),
            lifecycle=lifecycle,
            max_parallel=2,
        )
        return asyncio.run(scheduler.execute_parent(parent_id))

    shared = _Executor()
    separate = _Executor()

    assert schedule(shared, ["system", "system"]).status is TaskStatus.COMPLETED
    assert shared.max_active == 1
    assert schedule(separate, ["system", "research"]).status is TaskStatus.COMPLETED
    assert separate.max_active == 2


def test_browser_objective_is_explicitly_unavailable(tmp_path: Path) -> None:
    OMNE = build_OMNE(runtime_settings(tmp_path))

    task = OMNE.execute_sync("open https://example.com")

    assert task.status is TaskStatus.COMPLETED
    rendered = str(task.result)
    assert "available" in rendered
    assert "False" in rendered or "false" in rendered
