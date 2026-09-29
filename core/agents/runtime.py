"""Start an agent for one task and unload it afterward."""

from __future__ import annotations

from core.agents.lifecycle import AgentLifecycle, AgentState
from core.agents.manifest import AgentManifest
from core.events.bus import EventBus
from core.workers.pool import Worker, WorkerLimit, WorkerPool, admit_worker


class AgentRuntime:
    """Drive the lifecycle around worker slots for an agent."""

    def __init__(
        self,
        lifecycle: AgentLifecycle,
        pool: WorkerPool | None = None,
        events: EventBus | None = None,
    ) -> None:
        self._lifecycle = lifecycle
        self.pool = pool or WorkerPool()
        self._events = events

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
        admission = admit_worker(
            active=self.pool.active(manifest.id),
            max_workers=manifest.max_workers,
            cpu_percent=cpu_percent,
        )
        if admission == "WAIT":
            raise WorkerLimit(f"{manifest.id} is waiting for CPU")
        if admission == "DENY" or self.pool.active(manifest.id) >= manifest.max_workers:
            raise WorkerLimit(f"{manifest.id} is at max_workers")
        if self.pool.active(manifest.id) == 0:
            state = self._lifecycle.state(manifest.id)
            if state is AgentState.UNLOADED:
                self._lifecycle.transition(manifest.id, AgentState.AVAILABLE)
            if self._lifecycle.state(manifest.id) is not AgentState.RUNNING:
                self._lifecycle.transition(manifest.id, AgentState.RESERVED)
                self._lifecycle.transition(manifest.id, AgentState.INITIALIZING)
                self._lifecycle.transition(manifest.id, AgentState.RUNNING)
        worker = self.pool.start(
            agent_id=manifest.id,
            max_workers=manifest.max_workers,
            task_id=task_id,
            mission_id=mission_id,
            model_id=model_id,
            trace_id=trace_id,
        )
        if self._events is not None:
            self._events.publish(
                "worker.started",
                agent_id=manifest.id,
                task_id=task_id,
                mission_id=mission_id,
                worker_id=worker.worker_id,
                model_id=model_id,
                trace_id=trace_id,
                payload={"status": worker.status},
            )
        return worker

    def succeed(self, manifest: AgentManifest) -> None:
        worker = self.pool.complete(manifest.id)
        self._publish_worker("worker.completed", worker)
        if self.pool.active(manifest.id) > 0:
            return
        if self._lifecycle.state(manifest.id) is AgentState.RUNNING:
            self._lifecycle.transition(manifest.id, AgentState.VERIFYING)
            self._lifecycle.transition(manifest.id, AgentState.COMPLETED)
            self._finish(manifest)

    def release(self, manifest: AgentManifest) -> None:
        """Return one worker while a person confirms an action."""

        worker = self.pool.complete(manifest.id)
        self._publish_worker("worker.completed", worker)
        if self.pool.active(manifest.id) > 0:
            return
        if self._lifecycle.state(manifest.id) is AgentState.RUNNING:
            self._lifecycle.transition(manifest.id, AgentState.RECOVERING)
            self._lifecycle.transition(manifest.id, AgentState.AVAILABLE)

    def fail(self, manifest: AgentManifest, *, retry: bool) -> None:
        if not retry:
            worker = self.pool.fail(manifest.id)
            self._publish_worker("worker.failed", worker)
            if self.pool.active(manifest.id) > 0:
                return
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

    def _publish_worker(self, event_type: str, worker: Worker | None) -> None:
        if self._events is None or worker is None:
            return
        self._events.publish(
            event_type,
            agent_id=worker.agent_id,
            task_id=worker.current_task,
            mission_id=worker.current_mission,
            worker_id=worker.worker_id,
            model_id=worker.model,
            trace_id=worker.trace_id,
            payload={"status": worker.status},
        )

    def _finish(self, manifest: AgentManifest) -> None:
        if manifest.lifecycle.persistent:
            self._lifecycle.transition(manifest.id, AgentState.AVAILABLE)
            return
        self._lifecycle.transition(manifest.id, AgentState.UNLOADED)
        self._lifecycle.transition(manifest.id, AgentState.AVAILABLE)
