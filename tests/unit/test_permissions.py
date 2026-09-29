"""Permission decisions, audit, and fail-closed evaluation."""

from __future__ import annotations

from pathlib import Path

from core.events.bus import EventBus
from core.permissions.audit import AuditLog
from core.permissions.evaluator import PermissionEvaluator
from core.permissions.policies import PermissionDecision, PermissionRequest, decide
from core.tools.base import ToolContext
from core.tools.gateway import ToolGateway
from core.tools.registry import ToolRegistry


def _request(
    tool_id: str, arguments: dict[str, object], environment: str = "testing"
) -> PermissionRequest:
    return PermissionRequest(
        tool_id=tool_id,
        arguments=arguments,
        grants={
            "filesystem": ["workspace"],
            "terminal": ["workspace"],
            "process": ["list", "start", "signal"],
            "voice": ["transmit"],
        },
        environment=environment,
        workspace_root="/workspace",
    )


def test_workspace_read_is_allowed() -> None:
    result = decide(_request("filesystem.read", {"path": "notes.txt"}))

    assert result.decision is PermissionDecision.ALLOW


def test_path_outside_workspace_is_denied(tmp_path: Path) -> None:
    request = _request("filesystem.write", {"path": "../secret", "content": "x"})
    request = request.model_copy(update={"workspace_root": str(tmp_path)})

    result = decide(request)

    assert result.decision is PermissionDecision.DENY


def test_terminal_requires_confirmation_outside_production() -> None:
    result = decide(_request("terminal.execute", {"argv": ["echo", "hello"]}))

    assert result.decision is PermissionDecision.CONFIRM


def test_terminal_is_denied_in_production() -> None:
    result = decide(_request("terminal.execute", {"argv": ["echo", "hello"]}, "production"))

    assert result.decision is PermissionDecision.DENY


def test_sudo_is_always_denied() -> None:
    result = decide(_request("terminal.execute", {"argv": ["sudo", "true"]}))

    assert result.decision is PermissionDecision.DENY
    assert "sudo" in result.reason


def test_voice_transmission_is_denied() -> None:
    result = decide(_request("voice.transmit", {}))

    assert result.decision is PermissionDecision.DENY


def test_evaluator_fails_closed() -> None:
    def _broken(_request: PermissionRequest):
        raise RuntimeError("policy bug")

    result = PermissionEvaluator(_broken).evaluate(_request("filesystem.read", {"path": "a"}))

    assert result.decision is PermissionDecision.DENY
    assert result.policy_id == "fail-closed"


def test_gateway_audits_a_denial(tmp_path: Path) -> None:
    class _Tool:
        id = "filesystem.read"

        def validate(self, arguments: dict[str, object]) -> dict[str, object]:
            return arguments

        def execute(self, arguments: dict[str, object], context: ToolContext) -> dict[str, object]:
            raise AssertionError("denied tools must not execute")

    registry = ToolRegistry()
    registry.register(_Tool())
    audit = AuditLog(tmp_path / "audit.jsonl")
    gateway = ToolGateway(registry, PermissionEvaluator(), audit, EventBus())
    result = gateway.invoke(
        tool_id="filesystem.read",
        arguments={"path": "notes.txt"},
        context=ToolContext(
            task_id="t",
            agent_id=None,
            user="local",
            workspace_root=tmp_path,
            timeout_seconds=5,
        ),
        grants={},
        environment="testing",
    )

    assert result.ok is False
    assert audit.entries()[0].decision == "DENY"
    assert "DENY" in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
