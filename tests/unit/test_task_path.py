"""A model decision reaches a tool only through the gateway."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.support import runtime_settings

from core.api.runtime import build_OMNE
from core.orchestrator.task import TaskStatus
from core.tools.command import SubprocessCommands


def test_model_read_goes_through_the_gateway_and_is_verified(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("hello from the disk", encoding="utf-8")
    omne = build_OMNE(runtime_settings(tmp_path))

    task = omne.execute_sync("read file notes.txt")
    child = next(item for item in omne.list_tasks() if item.parent_task == task.id)
    observation = child.observations[0]
    events = omne.list_events()

    view = omne.desktop_view()
    activity = next(item for item in view["activity"] if item["id"] == child.id)

    assert task.status is TaskStatus.COMPLETED
    assert child.assigned_agent == "coding"
    assert activity["decision"]["provider"] == "mock"
    assert activity["decision"]["tools"] == ["filesystem.read"]
    assert "hello from the disk" in activity["decision"]["observation"]
    assert activity["verification"]["status"] == "PASS"
    assert observation["kind"] == "decision"
    assert observation["provider"] == "mock"
    assert observation["tools"] == ["filesystem.read"]
    assert observation["rejected_tools"] == []
    assert observation["outputs"][0]["output"]["content"] == "hello from the disk"
    assert child.result is not None
    assert child.result["verification"]["status"] == "PASS"
    assert any(
        event.type == "tool.executed" and event.tool_id == "filesystem.read" for event in events
    )
    completed = [event for event in events if event.type == "model.completed"]
    assert completed
    assert all(event.payload.get("provider") == "mock" for event in completed)


def test_unknown_tool_name_is_rejected_before_the_gateway(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_run(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the model path spawned a process")

    monkeypatch.setattr(SubprocessCommands, "run", fail_run)
    omne = build_OMNE(runtime_settings(tmp_path))

    task = omne.execute_sync("invoke unknown tool os.system")
    child = next(item for item in omne.list_tasks() if item.parent_task == task.id)
    observation = child.observations[0]

    assert task.status is TaskStatus.COMPLETED
    assert observation["rejected_tools"] == ["os.system"]
    assert observation["tools"] == []
    assert observation["outputs"] == []
    assert not any(event.type.startswith("tool.") for event in omne.list_events())


def test_model_terminal_request_waits_and_can_be_denied(tmp_path: Path) -> None:
    omne = build_OMNE(runtime_settings(tmp_path))

    waiting = omne.execute_sync("ask for terminal.execute echo hello")
    assert waiting.status is TaskStatus.WAITING
    assert not any(
        event.type == "tool.executed" and event.tool_id == "terminal.execute"
        for event in omne.list_events()
    )

    denied = omne.confirm_sync(waiting.id, approved=False)

    assert denied.status is TaskStatus.FAILED
    assert not any(event.type == "tool.executed" for event in omne.list_events())


def test_model_terminal_request_runs_only_after_confirmation(tmp_path: Path) -> None:
    omne = build_OMNE(runtime_settings(tmp_path))

    waiting = omne.execute_sync("ask for terminal.execute echo hello")
    finished = omne.confirm_sync(waiting.id, approved=True)
    child = next(item for item in omne.list_tasks() if item.parent_task == finished.id)

    assert finished.status is TaskStatus.COMPLETED
    assert "hello" in str(child.observations[0]["outputs"][0]["output"].get("stdout", ""))
    assert any(
        event.type == "tool.executed" and event.tool_id == "terminal.execute"
        for event in omne.list_events()
    )


def test_model_confirmation_runs_the_read_only_after_approval(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("kept\n", encoding="utf-8")
    omne = build_OMNE(runtime_settings(tmp_path))

    waiting = omne.execute_sync("confirm before reading file notes.txt")
    waiting_view = omne.desktop_view()
    waiting_activity = next(
        item for item in waiting_view["activity"] if item["status"] == "WAITING"
    )
    assert waiting.status is TaskStatus.WAITING
    assert waiting_activity["decision"]["provider"] == "mock"
    assert waiting_activity["decision"]["tools"] == ["filesystem.read"]
    assert waiting_activity["decision"]["observation"] == ""
    assert waiting_view["confirmations"][0]["tool_id"] == "filesystem.read"
    assert not any(event.type == "tool.executed" for event in omne.list_events())

    finished = omne.confirm_sync(waiting.id, approved=True)
    child = next(item for item in omne.list_tasks() if item.parent_task == finished.id)

    assert finished.status is TaskStatus.COMPLETED
    assert child.observations[0]["outputs"][0]["output"]["content"] == "kept\n"


def test_model_launch_opens_an_application_window_after_confirmation(tmp_path: Path) -> None:
    omne = build_OMNE(runtime_settings(tmp_path))

    waiting = omne.execute_sync("launch application Files")
    assert waiting.status is TaskStatus.WAITING
    assert not any(event.type == "application.launched" for event in omne.list_events())

    finished = omne.confirm_sync(waiting.id, approved=True)
    catalog = omne.applications_view()
    applications = catalog["applications"]
    files = next(item for item in applications if item["name"] == "Files")
    views = omne.desktop_view()

    assert finished.status is TaskStatus.COMPLETED
    assert files["state"] == "focused"
    assert files["windows"][0]["title"] == "Files"
    assert files["commanded"] is False
    assert any(event.type == "application.launched" for event in omne.list_events())
    assert any(
        item["decision"]["tools"] == ["application.launch"]
        for item in views["activity"]
        if item["decision"]
    )


def test_model_question_can_be_cancelled_without_a_tool(tmp_path: Path) -> None:
    omne = build_OMNE(runtime_settings(tmp_path))

    waiting = omne.execute_sync("please clarify which file")
    questions = omne.desktop_view()["questions"]

    assert waiting.status is TaskStatus.WAITING
    assert any(
        isinstance(question, dict) and question.get("question") == "Which file should be read?"
        for question in questions
    )

    cancelled = omne.cancel(waiting.id)
    view = omne.desktop_view()

    assert cancelled.status is TaskStatus.CANCELLED
    assert omne.list_missions()[0].status.value == "CANCELLED"
    assert view["questions"] == []
    assert not any(event.type == "tool.executed" for event in omne.list_events())
