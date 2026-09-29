"""Running worker instances for an agent definition."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict


class Worker(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    worker_id: str
    agent_id: str
    status: str
    current_task: str | None = None
    current_mission: str | None = None
    model: str | None = None
    trace_id: str | None = None
    started_at: datetime
    last_activity: datetime


class WorkerLimit(Exception):
    """Raised when an agent has no remaining worker slots."""


def admit_worker(
    *,
    active: int,
    max_workers: int,
    cpu_percent: float | None,
    cpu_limit: float = 95.0,
) -> str:
    """Decide whether a worker may start.

    Unknown CPU telemetry is not treated as capacity. A full worker slot is a
    denial. High measured CPU waits instead of starting another worker.
    """

    if active >= max_workers:
        return "DENY"
    if cpu_percent is not None and cpu_percent >= cpu_limit:
        return "WAIT"
    return "ALLOW"


class WorkerPool:
    """Track workers. Creation is refused at max_workers."""

    def __init__(self) -> None:
        self._workers: dict[str, Worker] = {}
        self._by_agent: dict[str, list[str]] = {}

    def active(self, agent_id: str) -> int:
        return sum(
            1
            for worker_id in self._by_agent.get(agent_id, [])
            if self._workers[worker_id].status == "RUNNING"
        )

    def start(
        self,
        *,
        agent_id: str,
        max_workers: int,
        task_id: str | None,
        mission_id: str | None,
        model_id: str | None,
        trace_id: str | None,
    ) -> Worker:
        if self.active(agent_id) >= max_workers:
            raise WorkerLimit(f"{agent_id} already has {max_workers} workers")
        now = datetime.now(UTC)
        worker = Worker(
            worker_id=str(uuid4()),
            agent_id=agent_id,
            status="RUNNING",
            current_task=task_id,
            current_mission=mission_id,
            model=model_id,
            trace_id=trace_id,
            started_at=now,
            last_activity=now,
        )
        self._workers[worker.worker_id] = worker
        self._by_agent.setdefault(agent_id, []).append(worker.worker_id)
        return worker

    def complete(self, agent_id: str) -> Worker | None:
        return self._close(agent_id, "IDLE")

    def fail(self, agent_id: str) -> Worker | None:
        return self._close(agent_id, "FAILED")

    def list_workers(self) -> list[Worker]:
        return list(self._workers.values())

    def get(self, worker_id: str) -> Worker:
        try:
            return self._workers[worker_id]
        except KeyError as exc:
            raise KeyError(f"unknown worker: {worker_id}") from exc

    def _close(self, agent_id: str, status: str) -> Worker | None:
        open_ids = [
            worker_id
            for worker_id in self._by_agent.get(agent_id, [])
            if self._workers[worker_id].status == "RUNNING"
        ]
        if not open_ids:
            return None
        worker_id = open_ids[-1]
        worker = self._workers[worker_id].model_copy(
            update={"status": status, "last_activity": datetime.now(UTC)}
        )
        self._workers[worker_id] = worker
        return worker
