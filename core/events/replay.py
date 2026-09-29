"""Rebuild state from events without running tools."""

from __future__ import annotations

from typing import Any

from core.events.bus import Event


def replay_events(events: list[Event]) -> dict[str, Any]:
    """Fold events into a state document. This does not execute anything."""

    missions: dict[str, str] = {}
    tasks: dict[str, str] = {}
    workers: dict[str, str] = {}
    for event in events:
        if event.type.startswith("mission.") and event.mission_id:
            missions[event.mission_id] = event.type.removeprefix("mission.")
        if event.task_id and event.type.startswith("task."):
            tasks[event.task_id] = event.type.removeprefix("task.")
        if event.worker_id and event.type.startswith("worker."):
            workers[event.worker_id] = event.type.removeprefix("worker.")
    return {
        "missions": missions,
        "tasks": tasks,
        "workers": workers,
        "event_count": len(events),
        "side_effects": False,
    }
