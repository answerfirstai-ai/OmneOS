"""Trace identifiers for one OMNE mission."""

from __future__ import annotations

import contextvars
from uuid import uuid4

_CURRENT: contextvars.ContextVar[str | None] = contextvars.ContextVar("omne_trace_id", default=None)
_MISSION: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "omne_mission_id", default=None
)


def new_trace_id() -> str:
    """Start a trace and make it the current one."""

    trace_id = str(uuid4())
    _CURRENT.set(trace_id)
    return trace_id


def current_trace_id() -> str | None:
    """Return the trace active in this context, if any."""

    return _CURRENT.get()


def set_mission_id(mission_id: str | None) -> None:
    """Attach the active mission to later events in this context."""

    _MISSION.set(mission_id)


def current_mission_id() -> str | None:
    """Return the mission active in this context, if any."""

    return _MISSION.get()
