"""Worker lifecycle.

An agent is a definition. A worker is one runtime instance, and these states
belong to that instance. They are not the agent definition states.
"""

from __future__ import annotations

from enum import StrEnum


class WorkerState(StrEnum):
    DISCOVERED = "DISCOVERED"
    AVAILABLE = "AVAILABLE"
    SPAWNED = "SPAWNED"
    RUNNING = "RUNNING"
    IDLE = "IDLE"
    PAUSED = "PAUSED"
    TERMINATED = "TERMINATED"
    FAILED = "FAILED"


TRANSITIONS: dict[WorkerState, frozenset[WorkerState]] = {
    WorkerState.DISCOVERED: frozenset({WorkerState.AVAILABLE, WorkerState.FAILED}),
    WorkerState.AVAILABLE: frozenset(
        {WorkerState.SPAWNED, WorkerState.TERMINATED, WorkerState.FAILED}
    ),
    WorkerState.SPAWNED: frozenset(
        {WorkerState.RUNNING, WorkerState.IDLE, WorkerState.FAILED, WorkerState.TERMINATED}
    ),
    WorkerState.RUNNING: frozenset(
        {WorkerState.IDLE, WorkerState.PAUSED, WorkerState.FAILED, WorkerState.TERMINATED}
    ),
    WorkerState.IDLE: frozenset({WorkerState.SPAWNED, WorkerState.TERMINATED, WorkerState.FAILED}),
    WorkerState.PAUSED: frozenset(
        {WorkerState.RUNNING, WorkerState.IDLE, WorkerState.TERMINATED, WorkerState.FAILED}
    ),
    WorkerState.FAILED: frozenset({WorkerState.AVAILABLE, WorkerState.TERMINATED}),
    WorkerState.TERMINATED: frozenset(),
}

ACTIVE_STATES = frozenset({WorkerState.RUNNING, WorkerState.SPAWNED})
REUSABLE_STATES = frozenset({WorkerState.IDLE, WorkerState.PAUSED})
OCCUPIED_STATES = frozenset(
    {
        WorkerState.DISCOVERED,
        WorkerState.AVAILABLE,
        WorkerState.SPAWNED,
        WorkerState.RUNNING,
        WorkerState.IDLE,
        WorkerState.PAUSED,
        WorkerState.FAILED,
    }
)


class InvalidWorkerTransition(Exception):
    """Raised when a worker lifecycle edge is not allowed."""

    def __init__(self, worker_id: str, current: WorkerState, proposed: WorkerState) -> None:
        super().__init__(f"{worker_id} cannot move from {current} to {proposed}")
        self.worker_id = worker_id
        self.current = current
        self.proposed = proposed


def can_transition(current: WorkerState, proposed: WorkerState) -> bool:
    return proposed in TRANSITIONS[current]
