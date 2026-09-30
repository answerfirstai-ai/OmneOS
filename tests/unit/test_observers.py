"""Observer actions are allowed only through the gateway."""

from __future__ import annotations

from pathlib import Path

from core.events.bus import EventBus
from core.permissions.audit import AuditLog
from core.permissions.evaluator import PermissionEvaluator
from core.tools import build_registry
from core.tools.base import ToolContext
from core.tools.gateway import ToolGateway

_READ = {
    "network": ["scan"],
    "display": ["read"],
    "hardware": ["read"],
    "storage": ["read"],
    "audio": ["configure"],
    "input": ["use", "bind"],
}


def _gateway(tmp_path: Path) -> tuple[ToolGateway, ToolContext]:
    gateway = ToolGateway(build_registry(), PermissionEvaluator(), AuditLog(), EventBus())
    context = ToolContext(
        task_id="task",
        agent_id="system",
        user="local",
        workspace_root=tmp_path,
        timeout_seconds=5,
    )
    return gateway, context


def test_observer_reads_require_a_grant(tmp_path: Path) -> None:
    gateway, context = _gateway(tmp_path)

    denied = gateway.invoke(
        tool_id="network.scan",
        arguments={},
        context=context,
        grants={},
        environment="testing",
    )
    scanned = gateway.invoke(
        tool_id="network.scan",
        arguments={},
        context=context,
        grants=_READ,
        environment="testing",
    )
    display = gateway.invoke(
        tool_id="display.inspect",
        arguments={},
        context=context,
        grants=_READ,
        environment="testing",
    )
    hardware = gateway.invoke(
        tool_id="hardware.inspect",
        arguments={},
        context=context,
        grants=_READ,
        environment="testing",
    )
    storage = gateway.invoke(
        tool_id="storage.inspect",
        arguments={},
        context=context,
        grants=_READ,
        environment="testing",
    )

    assert denied.ok is False
    assert scanned.ok is True
    assert scanned.output["state"]["scan_known"] is True
    assert scanned.output["state"]["stack_commanded"] is False
    assert display.ok is True
    assert display.output["surface"]["uri"] == "http://127.0.0.1:4173/?surface=desktop"
    assert hardware.ok is True
    assert hardware.output["provider"] == "mock"
    assert storage.ok is True
    assert storage.output["provider"] == "mock"


def test_network_and_audio_changes_wait_for_confirmation(tmp_path: Path) -> None:
    gateway, context = _gateway(tmp_path)

    network = gateway.invoke(
        tool_id="network.connect",
        arguments={"interface": "eth0"},
        context=context,
        grants={**_READ, "network": ["scan", "configure"]},
        environment="testing",
    )
    audio = gateway.invoke(
        tool_id="audio.set_volume",
        arguments={"device": "speaker", "volume": 20},
        context=context,
        grants=_READ,
        environment="testing",
    )
    command = gateway.invoke(
        tool_id="network.scan",
        arguments={"command": "iwlist scan"},
        context=context,
        grants=_READ,
        environment="testing",
    )

    assert network.confirmation_required is True
    assert network.ok is False
    assert audio.confirmation_required is True
    assert command.ok is False
    assert command.error is not None
    assert command.error["code"] == "invalid_tool"
