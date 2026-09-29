"""Event bus retention and persistence."""

from __future__ import annotations

from pathlib import Path

from core.events.bus import EventBus


def test_events_can_be_listed_after_an_id(tmp_path: Path) -> None:
    bus = EventBus(persist_path=tmp_path / "events.jsonl")
    first = bus.publish("task.started", task_id="1")
    second = bus.publish("task.completed", task_id="1")

    assert [event.id for event in bus.list_events(after=first.id)] == [second.id]
    assert (tmp_path / "events.jsonl").read_text(encoding="utf-8").count("task.started") == 1
