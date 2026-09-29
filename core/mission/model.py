"""Mission records above the task graph."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MissionStatus(StrEnum):
    CREATED = "CREATED"
    ANALYZING = "ANALYZING"
    PLANNING = "PLANNING"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    PAUSED = "PAUSED"
    RECOVERING = "RECOVERING"


MISSION_TRANSITIONS: dict[MissionStatus, frozenset[MissionStatus]] = {
    MissionStatus.CREATED: frozenset({MissionStatus.ANALYZING, MissionStatus.CANCELLED}),
    MissionStatus.ANALYZING: frozenset(
        {
            MissionStatus.PLANNING,
            MissionStatus.WAITING,
            MissionStatus.FAILED,
            MissionStatus.CANCELLED,
        }
    ),
    MissionStatus.PLANNING: frozenset(
        {
            MissionStatus.READY,
            MissionStatus.WAITING,
            MissionStatus.FAILED,
            MissionStatus.CANCELLED,
        }
    ),
    MissionStatus.READY: frozenset(
        {MissionStatus.RUNNING, MissionStatus.PAUSED, MissionStatus.CANCELLED, MissionStatus.FAILED}
    ),
    MissionStatus.RUNNING: frozenset(
        {
            MissionStatus.WAITING,
            MissionStatus.VERIFYING,
            MissionStatus.PAUSED,
            MissionStatus.RECOVERING,
            MissionStatus.FAILED,
            MissionStatus.CANCELLED,
            MissionStatus.COMPLETED,
        }
    ),
    MissionStatus.WAITING: frozenset(
        {
            MissionStatus.RUNNING,
            MissionStatus.PAUSED,
            MissionStatus.CANCELLED,
            MissionStatus.FAILED,
        }
    ),
    MissionStatus.VERIFYING: frozenset(
        {MissionStatus.COMPLETED, MissionStatus.FAILED, MissionStatus.RECOVERING}
    ),
    MissionStatus.PAUSED: frozenset({MissionStatus.RUNNING, MissionStatus.CANCELLED}),
    MissionStatus.RECOVERING: frozenset(
        {MissionStatus.RUNNING, MissionStatus.FAILED, MissionStatus.CANCELLED}
    ),
    MissionStatus.COMPLETED: frozenset(),
    MissionStatus.FAILED: frozenset({MissionStatus.CANCELLED}),
    MissionStatus.CANCELLED: frozenset(),
}

_MISSION_EVENTS = {
    MissionStatus.CREATED: "mission.created",
    MissionStatus.ANALYZING: "mission.analyzing",
    MissionStatus.PLANNING: "mission.planned",
    MissionStatus.RUNNING: "mission.started",
    MissionStatus.WAITING: "mission.waiting",
    MissionStatus.VERIFYING: "mission.verifying",
    MissionStatus.COMPLETED: "mission.completed",
    MissionStatus.FAILED: "mission.failed",
    MissionStatus.CANCELLED: "mission.cancelled",
    MissionStatus.PAUSED: "mission.paused",
    MissionStatus.RECOVERING: "mission.resumed",
}


class MissionError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str


class Mission(BaseModel):
    """One user objective tracked above its tasks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    objective: str
    status: MissionStatus = MissionStatus.CREATED
    priority: int = 0
    created_at: datetime
    updated_at: datetime
    parent_mission_id: str | None = None
    objectives: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    trace_id: str
    context: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    errors: list[MissionError] = Field(default_factory=list)
    task_id: str | None = None


class InvalidMissionTransition(Exception):
    def __init__(self, current: MissionStatus, proposed: MissionStatus) -> None:
        super().__init__(f"cannot move mission from {current} to {proposed}")
        self.current = current
        self.proposed = proposed


def transition_mission(
    mission: Mission,
    status: MissionStatus,
    *,
    now: datetime,
    **updates: object,
) -> Mission:
    if status not in MISSION_TRANSITIONS[mission.status]:
        raise InvalidMissionTransition(mission.status, status)
    changes: dict[str, object] = {"status": status, "updated_at": now}
    changes.update(updates)
    return mission.model_copy(update=changes)


def mission_event(status: MissionStatus) -> str | None:
    if status is MissionStatus.RECOVERING:
        return "mission.resumed"
    return _MISSION_EVENTS.get(status)
