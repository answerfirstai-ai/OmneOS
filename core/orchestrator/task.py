"""Task model and validated status transitions."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.compute.requirements import ResourceRequirements


class TaskStatus(StrEnum):
    QUEUED = "QUEUED"
    PLANNING = "PLANNING"
    WAITING = "WAITING"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    PAUSED = "PAUSED"
    RECOVERING = "RECOVERING"


TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.QUEUED: frozenset({TaskStatus.PLANNING, TaskStatus.CANCELLED}),
    TaskStatus.PLANNING: frozenset(
        {
            TaskStatus.WAITING,
            TaskStatus.RUNNING,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.PAUSED,
        }
    ),
    TaskStatus.WAITING: frozenset(
        {TaskStatus.RUNNING, TaskStatus.CANCELLED, TaskStatus.FAILED, TaskStatus.PAUSED}
    ),
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.VERIFYING,
            TaskStatus.WAITING,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.PAUSED,
            TaskStatus.RECOVERING,
        }
    ),
    TaskStatus.VERIFYING: frozenset(
        {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.RECOVERING}
    ),
    TaskStatus.FAILED: frozenset({TaskStatus.RECOVERING, TaskStatus.CANCELLED}),
    TaskStatus.RECOVERING: frozenset(
        {TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.FAILED, TaskStatus.CANCELLED}
    ),
    TaskStatus.PAUSED: frozenset(
        {TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.WAITING, TaskStatus.CANCELLED}
    ),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}


class InvalidTransition(Exception):
    """Raised when a task status change is not allowed."""

    def __init__(self, current: TaskStatus, proposed: TaskStatus) -> None:
        super().__init__(f"cannot move task from {current} to {proposed}")
        self.current = current
        self.proposed = proposed


class PlannedCall(BaseModel):
    """One unit of work inside a task."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str
    tool_id: str = ""
    arguments: dict[str, Any] = Field(default_factory=dict)
    prompt: str = ""
    output_path: str = ""


class TaskStep(BaseModel):
    """A node in the task dependency graph."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    objective: str
    status: TaskStatus
    dependencies: list[str] = Field(default_factory=list)
    assigned_agent: str | None = None
    required_tools: list[str] = Field(default_factory=list)


class TaskErrorRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class Task(BaseModel):
    """A persisted unit of work."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    objective: str
    status: TaskStatus = TaskStatus.QUEUED
    priority: int = 0
    created_at: datetime
    updated_at: datetime
    parent_task: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    assigned_agent: str | None = None
    assigned_model: str | None = None
    required_tools: list[str] = Field(default_factory=list)
    required_resources: ResourceRequirements = Field(default_factory=ResourceRequirements)
    permissions: list[str] = Field(default_factory=list)
    steps: list[TaskStep] = Field(default_factory=list)
    calls: list[PlannedCall] = Field(default_factory=list)
    observations: list[dict[str, Any]] = Field(default_factory=list)
    result: dict[str, Any] | None = None
    errors: list[TaskErrorRecord] = Field(default_factory=list)
    retry_count: int = 0
    retry_limit: int = 2
    metadata: dict[str, Any] = Field(default_factory=dict)
    pending_confirmation: dict[str, Any] | None = None


def transition_task(
    task: Task,
    status: TaskStatus,
    *,
    now: datetime,
    **updates: object,
) -> Task:
    """Return a copy of ``task`` in ``status`` when the edge is valid."""

    if status not in TRANSITIONS[task.status]:
        raise InvalidTransition(task.status, status)
    changes: dict[str, object] = {"status": status, "updated_at": now}
    changes.update(updates)
    return task.model_copy(update=changes)
