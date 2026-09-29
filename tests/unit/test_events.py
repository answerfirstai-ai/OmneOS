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


def test_list_events_limit_returns_the_tail() -> None:
    bus = EventBus()
    published = [bus.publish("task.started").id for _ in range(5)]

    assert [event.id for event in bus.list_events(limit=2)] == published[-2:]
    assert bus.list_events(limit=0) == []
