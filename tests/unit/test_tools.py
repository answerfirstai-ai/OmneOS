"""Tool validation and host boundaries."""

from __future__ import annotations

from pathlib import Path

from core.events.bus import EventBus
from core.permissions.audit import AuditLog
from core.permissions.evaluator import PermissionEvaluator
from core.tools import build_registry
from core.tools.base import ToolContext
from core.tools.gateway import ToolGateway

_GRANTS = {
    "filesystem": ["workspace"],
    "terminal": ["workspace"],
    "process": ["signal"],
    "system": ["read"],
    "git": ["read"],
    "browser": ["navigate"],
}


def _gateway(tmp_path: Path) -> tuple[ToolGateway, ToolContext]:
    gateway = ToolGateway(
        build_registry(),
        PermissionEvaluator(),
        AuditLog(),
        EventBus(),
    )
    context = ToolContext(
        task_id="task",
        agent_id="coding",
        user="local",
        workspace_root=tmp_path,
        timeout_seconds=5,
    )
    return gateway, context


def test_filesystem_round_trip_stays_in_the_workspace(tmp_path: Path) -> None:
    gateway, context = _gateway(tmp_path)
    written = gateway.invoke(
        tool_id="filesystem.write",
        arguments={"path": "notes/hello.txt", "content": "alpha"},
        context=context,
        grants=_GRANTS,
        environment="testing",
    )
    found = gateway.invoke(
        tool_id="filesystem.search",
        arguments={"query": "alpha"},
        context=context,
        grants=_GRANTS,
        environment="testing",
    )
    read = gateway.invoke(
        tool_id="filesystem.read",
        arguments={"path": "notes/hello.txt"},
        context=context,
        grants=_GRANTS,
        environment="testing",
    )

    assert written.ok is True
    assert found.output["matches"] == ["notes/hello.txt"]
    assert read.output["content"] == "alpha"
    assert (tmp_path / "notes" / "hello.txt").is_file()


def test_search_skips_binary_content_and_still_matches_names(tmp_path: Path) -> None:
    gateway, context = _gateway(tmp_path)
    (tmp_path / "photo.png").write_bytes(b"alpha-inside-binary")
    (tmp_path / "alpha.png").write_bytes(b"\x00\x01")
    (tmp_path / "notes.txt").write_text("alpha", encoding="utf-8")

    found = gateway.invoke(
        tool_id="filesystem.search",
        arguments={"query": "alpha"},
        context=context,
        grants=_GRANTS,
        environment="testing",
    )

    assert found.ok is True
    assert found.output["matches"] == ["alpha.png", "notes.txt"]


def test_filesystem_rejects_parent_escape(tmp_path: Path) -> None:
    gateway, context = _gateway(tmp_path)
    outside = tmp_path.parent / "outside-secret.txt"

    result = gateway.invoke(
        tool_id="filesystem.write",
        arguments={"path": "../outside-secret.txt", "content": "nope"},
        context=context,
        grants=_GRANTS,
        environment="testing",
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error["code"] == "denied"
    assert not outside.exists()


def test_terminal_does_not_run_without_confirmation(tmp_path: Path) -> None:
    gateway, context = _gateway(tmp_path)
    marker = tmp_path / "ran.txt"

    result = gateway.invoke(
        tool_id="terminal.execute",
        arguments={"argv": ["touch", "ran.txt"]},
        context=context,
        grants=_GRANTS,
        environment="testing",
    )

    assert result.confirmation_required is True
    assert not marker.exists()


def test_terminal_runs_after_approval(tmp_path: Path) -> None:
    gateway, context = _gateway(tmp_path)

    result = gateway.invoke(
        tool_id="terminal.execute",
        arguments={"argv": ["echo", "hello"]},
        context=context,
        grants=_GRANTS,
        environment="testing",
        approved=True,
    )

    assert result.ok is True
    assert result.output["stdout"].strip() == "hello"


def test_sudo_never_runs(tmp_path: Path) -> None:
    gateway, context = _gateway(tmp_path)

    result = gateway.invoke(
        tool_id="terminal.execute",
        arguments={"argv": ["sudo", "echo", "hello"]},
        context=context,
        grants=_GRANTS,
        environment="testing",
        approved=True,
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error["code"] == "denied"


def test_process_stop_refuses_pid_one(tmp_path: Path) -> None:
    gateway, context = _gateway(tmp_path)

    result = gateway.invoke(
        tool_id="process.stop",
        arguments={"pid": 1},
        context=context,
        grants=_GRANTS,
        environment="testing",
        approved=True,
    )

    assert result.ok is False


def test_browser_without_command_is_unavailable(tmp_path: Path) -> None:
    gateway, context = _gateway(tmp_path)

    result = gateway.invoke(
        tool_id="browser.open",
        arguments={"url": "https://example.com"},
        context=context,
        grants=_GRANTS,
        environment="testing",
    )

    assert result.ok is True
    assert result.unavailable is True
    assert result.output["available"] is False


def test_system_cpu_reports_a_measurement_or_null(tmp_path: Path) -> None:
    gateway, context = _gateway(tmp_path)

    result = gateway.invoke(
        tool_id="system.cpu",
        arguments={},
        context=context,
        grants=_GRANTS,
        environment="testing",
    )

    assert result.ok is True
    assert "usage_percent" in result.output
