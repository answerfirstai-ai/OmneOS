"""Boot proof prints a marker only after the core reports that result."""

from __future__ import annotations

from omne.bootproof import health_ready, lifecycles_from, markers, task_failure, task_status_from


def test_completed_task_and_available_model_are_marked() -> None:
    lines = markers(task_status="COMPLETED", lifecycles=["AVAILABLE", "UNAVAILABLE"])

    assert lines == ["agent task completed", "model runtime ready"]


def test_a_failed_task_and_an_unavailable_model_stay_unmarked() -> None:
    lines = markers(task_status="FAILED", lifecycles=["UNAVAILABLE"])

    assert lines == []


def test_task_failure_reads_the_first_error() -> None:
    payload = {"task": {"status": "FAILED", "errors": [{"code": "escalated", "message": "abort"}]}}

    assert task_failure(payload) == "escalated: abort"
    assert task_failure({"task": {"status": "COMPLETED"}}) == ""


def test_health_requires_the_core_payload() -> None:
    assert health_ready({"status": "ok", "service": "OMNE-core"}) is True
    assert health_ready({"status": "ok", "service": "other"}) is False
    assert health_ready(None) is False


def test_readers_ignore_a_missing_core() -> None:
    assert task_status_from(None) is None
    assert lifecycles_from({"models": [{"lifecycle": "IDLE"}, {"lifecycle": 1}]}) == ["IDLE"]
    assert task_status_from({"task": {"status": "COMPLETED"}}) == "COMPLETED"
