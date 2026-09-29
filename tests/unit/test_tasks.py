"""Task status transitions."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from core.orchestrator.task import InvalidTransition, Task, TaskStatus, transition_task


def _task() -> Task:
    now = datetime.now(UTC)
    return Task(id="task-1", objective="inspect", created_at=now, updated_at=now)


def test_running_task_can_complete() -> None:
    task = _task()
    task = transition_task(task, TaskStatus.PLANNING, now=datetime.now(UTC))
    task = transition_task(task, TaskStatus.RUNNING, now=datetime.now(UTC))
    task = transition_task(task, TaskStatus.VERIFYING, now=datetime.now(UTC))
    task = transition_task(task, TaskStatus.COMPLETED, now=datetime.now(UTC))

    assert task.status is TaskStatus.COMPLETED


def test_invalid_transition_is_rejected() -> None:
    task = _task()

    with pytest.raises(InvalidTransition):
        transition_task(task, TaskStatus.COMPLETED, now=datetime.now(UTC))
