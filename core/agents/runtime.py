"""Start a worker for one task and return the agent definition afterward.

The worker is an in-memory instance. This module does not create a process
for it.
"""

from __future__ import annotations

from core.agents.lifecycle import AgentLifecycle, AgentState
from core.agents.manifest import AgentManifest
from core.events.bus import EventBus
from core.workers.pool import Worker, WorkerLimit, WorkerPool


class AgentRuntime:
    """Drive the lifecycle around worker slots for an agent."""

    def __init__(
        self,
        lifecycle: AgentLifecycle,
        pool: WorkerPool | None = None,
        events: EventBus | None = None,
    ) -> None:
        self._lifecycle = lifecycle
        self.pool = pool or WorkerPool(ram_limit_mb=8192)
        self._events = events
        self.pool.bind(self._on_worker_event)

    def active(self, agent_id: str) -> int:
        return self.pool.active(agent_id)

    def begin(
        self,
        manifest: AgentManifest,
        *,
        task_id: str | None = None,
        mission_id: str | None = None,
        model_id: str | None = None,
        trace_id: str | None = None,
        cpu_percent: float | None = None,
    ) -> Worker:
        before = self.pool.active(manifest.id)
        try:
            worker = self.pool.start(
                agent_id=manifest.id,
                max_workers=manifest.max_workers,
                task_id=task_id,
                mission_id=mission_id,
                model_id=model_id,
                trace_id=trace_id,
                capabilities=list(manifest.capabilities),
                tools=list(manifest.tools),
                permissions={key: list(value) for key, value in manifest.permissions.items()},
                resources=manifest.resources,
                context=f"task {task_id or 'unassigned'}",
                cpu_percent=cpu_percent,
            )
        except WorkerLimit as exc:
            if exc.reason == "cpu":
                raise WorkerLimit(f"{manifest.id} is waiting for CPU") from exc
            if exc.reason == "resources":
                raise WorkerLimit(f"{manifest.id} is waiting for memory") from exc
            raise WorkerLimit(f"{manifest.id} is at max_workers") from exc
        if before == 0:
            self._mark_running(manifest)
        return worker

    def _mark_running(self, manifest: AgentManifest) -> None:
        state = self._lifecycle.state(manifest.id)
        if state is AgentState.UNLOADED:
            self._lifecycle.transition(manifest.id, AgentState.AVAILABLE)
        if self._lifecycle.state(manifest.id) is AgentState.RUNNING:
            return
        self._lifecycle.transition(manifest.id, AgentState.RESERVED)
        self._lifecycle.transition(manifest.id, AgentState.INITIALIZING)
        self._lifecycle.transition(manifest.id, AgentState.RUNNING)

    def succeed(self, manifest: AgentManifest) -> None:
        self.pool.complete(manifest.id)
        if self.pool.active(manifest.id) > 0:
            return
        if self._lifecycle.state(manifest.id) is AgentState.RUNNING:
            self._lifecycle.transition(manifest.id, AgentState.VERIFYING)
            self._lifecycle.transition(manifest.id, AgentState.COMPLETED)
            self._finish(manifest)

    def release(self, manifest: AgentManifest) -> None:
        """Pause one worker while a person confirms an action."""

        self.pool.pause_running(manifest.id)
        if self.pool.active(manifest.id) > 0:
            return
        if self._lifecycle.state(manifest.id) is AgentState.RUNNING:
            self._lifecycle.transition(manifest.id, AgentState.RECOVERING)
            self._lifecycle.transition(manifest.id, AgentState.AVAILABLE)

    def cancel(self, worker_id: str) -> Worker:
        return self.pool.cancel(worker_id)

    def terminate(self, worker_id: str) -> Worker:
        return self.pool.terminate(worker_id)

    def fail(self, manifest: AgentManifest, *, retry: bool) -> None:
        if not retry:
            self.pool.fail(manifest.id)
            if self.pool.active(manifest.id) > 0:
                return
            self.pool.terminate_failed(manifest.id)
        current = self._lifecycle.state(manifest.id)
        if current is AgentState.RUNNING and not retry:
            self._lifecycle.transition(manifest.id, AgentState.FAILED)
        if retry:
            if current is AgentState.RUNNING:
                self._lifecycle.transition(manifest.id, AgentState.FAILED)
            self._lifecycle.transition(manifest.id, AgentState.RECOVERING)
            self._lifecycle.transition(manifest.id, AgentState.INITIALIZING)
            self._lifecycle.transition(manifest.id, AgentState.RUNNING)
            return
        if self._lifecycle.state(manifest.id) is AgentState.FAILED:
            self._lifecycle.transition(manifest.id, AgentState.UNLOADED)
            self._lifecycle.transition(manifest.id, AgentState.AVAILABLE)

    def _on_worker_event(self, event_type: str, worker: Worker) -> None:
        if self._events is None:
            return
        self._events.publish(
            event_type,
            agent_id=worker.agent_id,
            task_id=worker.current_task,
            mission_id=worker.current_mission,
            worker_id=worker.worker_id,
            model_id=worker.model,
            trace_id=worker.trace_id,
            payload={"status": worker.status, "lifecycle": worker.lifecycle.value},
        )

    def _finish(self, manifest: AgentManifest) -> None:
        if manifest.lifecycle.persistent:
            self._lifecycle.transition(manifest.id, AgentState.AVAILABLE)
            return
        self.pool.terminate_idle(manifest.id)
        self._lifecycle.transition(manifest.id, AgentState.UNLOADED)
        self._lifecycle.transition(manifest.id, AgentState.AVAILABLE)
