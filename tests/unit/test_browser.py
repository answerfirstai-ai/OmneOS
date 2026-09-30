"""Browser layers stay separate, and the host browser is not driven."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

import pytest
from tests.conftest import ROOT
from tests.support import runtime_settings

from core.agents.registry import AgentRegistry
from core.api.routes import route_get, route_post
from core.api.runtime import build_OMNE
from core.events.bus import EventBus
from core.permissions.audit import AuditLog
from core.permissions.evaluator import PermissionEvaluator
from core.permissions.policies import PermissionRequest
from core.tools import build_registry
from core.tools.base import ToolContext
from core.tools.browser import BrowserOpenTool
from core.tools.command import CommandOutput
from core.tools.gateway import ToolGateway
from omne.browser.model import BrowserRequest
from omne.browser.providers.linux import LinuxBrowserProvider
from omne.browser.providers.mock import MockBrowserProvider
from omne.browser.select import browser_service, select_provider
from omne.browser.service import BrowserService

_GRANTS = {
    "browser": ["launch", "session", "inspect", "research", "render", "interact", "automate"]
}


def test_mock_session_separates_the_four_layers(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network")

    monkeypatch.setattr("urllib.request.urlopen", explode)
    events: list[str] = []
    service = BrowserService(
        MockBrowserProvider(),
        sink=lambda event_type, _payload: events.append(event_type),
        authorize=_allow,
    )
    launched = service.apply(_request("launch"), _GRANTS, "testing")

    assert launched.applied is True
    state = launched.state
    assert state.engine_installed is False
    assert state.engine_imported is False
    assert state.engine_dependency == "playwright"
    assert state.commanded is False
    assert state.attached is False
    assert [layer.id for layer in state.layers] == [
        "application",
        "automation",
        "research",
        "rendering",
    ]
    assert state.layers[0].available is True
    assert state.layers[1].available is False
    session = state.sessions[0]
    assert session.process is not None
    assert session.process.synthetic is True
    assert session.process.started_by_omne is False
    assert session.tabs[0].url == "about:blank"
    assert session.attached is False

    navigated = service.apply(
        _request("navigate", session_id=session.id, url="https://example.com"),
        _GRANTS,
        "testing",
    )
    inspected = service.apply(_request("inspect", session_id=session.id), _GRANTS, "testing")
    researched = service.apply(_request("research", query="example domain"), _GRANTS, "testing")
    rendered = service.apply(_request("screenshot", session_id=session.id), _GRANTS, "testing")
    yielded = service.apply(_request("interact", session_id=session.id), _GRANTS, "testing")
    blocked = service.apply(
        _request("automate", session_id=session.id, kind="click", target="docs"),
        _GRANTS,
        "testing",
    )

    assert navigated.applied is True
    assert inspected.inspection is not None
    assert inspected.inspection.title == "Example Domain"
    assert inspected.inspection.credentials is False
    assert inspected.inspection.excerpt == "This domain is for use in documentation."
    assert researched.research is not None
    assert researched.research.network is False
    assert researched.research.retrieved is False
    assert researched.research.simulated is True
    assert rendered.screenshot is not None
    assert rendered.screenshot.byte_length == 0
    assert rendered.screenshot.simulated is True
    assert yielded.applied is True
    assert yielded.state.sessions[0].control == "user"
    assert yielded.state.sessions[0].authentication == "user"
    assert blocked.applied is False
    assert blocked.reason == "the user controls this browser session"
    assert "password" not in json.dumps(blocked.state.model_dump())
    assert events == [
        "browser.launched",
        "browser.navigated",
        "browser.inspected",
        "browser.researched",
        "browser.rendered",
        "browser.user_control",
    ]


def test_launch_without_permission_does_not_create_a_session() -> None:
    service = BrowserService(MockBrowserProvider(), authorize=_policy)
    denied = service.apply(_request("launch"), {}, "testing")
    confirmed = service.apply(_request("launch"), _GRANTS, "testing")
    production = service.apply(_request("launch"), _GRANTS, "production")

    assert denied.applied is False
    assert denied.state.sessions == []
    assert confirmed.applied is False
    assert confirmed.reason == "high-risk operation requires confirmation"
    assert production.applied is False
    assert production.reason == "high-risk operation is denied in production"
    assert service.status().sessions == []


def test_existing_browser_tool_does_not_open_a_session(tmp_path: Path) -> None:
    service = browser_service("testing")
    registry = build_registry(browser=service)
    gateway = ToolGateway(registry, PermissionEvaluator(), AuditLog(), EventBus())
    context = _context(tmp_path)
    result = gateway.invoke(
        tool_id="browser.open",
        arguments={"url": "https://example.com"},
        context=context,
        grants={"browser": ["navigate"]},
        environment="testing",
    )

    assert result.ok is True
    assert result.unavailable is True
    assert result.output["available"] is False
    assert service.status().sessions == []

    class _Commands:
        def __init__(self) -> None:
            self.argv: list[str] = []

        def run(
            self,
            argv: list[str],
            *,
            cwd: Path,
            timeout: float,
            env: dict[str, str] | None = None,
        ) -> CommandOutput:
            del cwd, timeout, env
            self.argv = argv
            return CommandOutput(exit_code=0, stdout="", stderr="")

    commands = _Commands()
    tool = BrowserOpenTool("/usr/bin/firefox", commands)
    output = tool.execute(tool.validate({"url": "https://example.com"}), context)
    assert commands.argv == ["/usr/bin/firefox", "https://example.com"]
    assert output["available"] is True
    assert output["url"] == "https://example.com"
    assert "stdout" in output


def test_gateway_rejects_control_without_the_grant(tmp_path: Path) -> None:
    service = browser_service("testing")
    gateway = ToolGateway(
        build_registry(browser=service),
        PermissionEvaluator(),
        AuditLog(),
        EventBus(),
    )
    context = _context(tmp_path)
    launched = gateway.invoke(
        tool_id="browser.launch",
        arguments={},
        context=context,
        grants=_GRANTS,
        environment="testing",
        approved=True,
    )
    assert launched.ok is True
    assert service.status().sessions[0].simulated is True
    denied = gateway.invoke(
        tool_id="browser.automate",
        arguments={"session_id": "session-1", "kind": "click", "target": "docs"},
        context=context,
        grants={"browser": ["navigate"]},
        environment="testing",
        approved=True,
    )
    secret = gateway.invoke(
        tool_id="browser.automate",
        arguments={
            "session_id": "session-1",
            "kind": "click",
            "target": "password",
            "text": "secret",
        },
        context=context,
        grants=_GRANTS,
        environment="testing",
        approved=True,
    )

    assert denied.ok is False
    assert denied.error is not None
    assert denied.error["code"] == "denied"
    assert secret.ok is False
    assert secret.error is not None
    assert secret.error["code"] == "invalid_tool"
    assert service.status().sessions[0].actions == []


def test_linux_browser_is_observed_without_control(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _text(
        tmp_path / "usr" / "share" / "applications" / "firefox.desktop",
        "\n".join(
            [
                "[Desktop Entry]",
                "Type=Application",
                "Name=Firefox",
                "Exec=firefox %u",
                "Categories=Network;WebBrowser;",
                "",
            ]
        ),
    )
    _text(
        tmp_path / "usr" / "share" / "applications" / "shell.desktop",
        "\n".join(
            [
                "[Desktop Entry]",
                "Type=Application",
                "Name=Shell",
                'Exec=bash -c "echo hi"',
                "Categories=Network;WebBrowser;",
                "",
            ]
        ),
    )
    _text(
        tmp_path / "usr" / "share" / "applications" / "files.desktop",
        "\n".join(
            [
                "[Desktop Entry]",
                "Type=Application",
                "Name=Files",
                "Exec=nautilus",
                "Categories=System;FileManager;",
                "",
            ]
        ),
    )
    command = tmp_path / "proc" / "4242" / "cmdline"
    command.parent.mkdir(parents=True)
    command.write_bytes(b"firefox\0https://user:secret@example.invalid\0")
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))

    def explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("subprocess")

    monkeypatch.setattr("subprocess.run", explode)
    monkeypatch.setattr("subprocess.Popen", explode)
    state = LinuxBrowserProvider(root=tmp_path).status()
    after = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    outcome = LinuxBrowserProvider(root=tmp_path).apply(_request("launch"))

    assert after == before
    assert state.applications == ["firefox"]
    assert state.engine_installed is False
    assert state.engine_imported is False
    assert state.processes[0].executable == "firefox"
    assert state.processes[0].started_by_omne is False
    assert state.sessions == []
    automation = next(layer for layer in state.layers if layer.id == "automation")
    research = next(layer for layer in state.layers if layer.id == "research")
    rendering = next(layer for layer in state.layers if layer.id == "rendering")
    assert automation.available is False
    assert research.available is False
    assert rendering.available is False
    rendered = json.dumps(state.model_dump())
    assert "example.invalid" not in rendered
    assert "echo hi" not in rendered
    assert outcome.applied is False
    assert outcome.reason == "host browser automation is not installed"
    for path in Path("omne/browser").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "import playwright" not in text
        assert "import selenium" not in text
        assert "urllib.request" not in text
        assert "subprocess" not in text


def test_testing_api_is_read_only(tmp_path: Path) -> None:
    omne = build_OMNE(runtime_settings(tmp_path))
    status, body = route_get(omne, "/browser", {})

    assert status.value == 200
    record = body["browser"]
    assert isinstance(record, dict)
    assert record["provider"] == "mock"
    assert record["engine_installed"] is False
    assert record["engine_dependency"] == "playwright"
    assert record["commanded"] is False
    assert record["attached"] is False
    posted, payload = route_post(omne, "/browser", {"url": "https://example.com"})
    assert posted.value == 404
    assert payload["error"] == "not_found"


def test_only_the_browser_worker_holds_automation() -> None:
    loaded = AgentRegistry().discover(ROOT / "agents", known_tools=build_registry().ids())
    by_id = {agent.id: agent for agent in loaded}

    assert "automate" in by_id["browser-worker"].permissions["browser"]
    assert "automate" not in by_id["browser"].permissions["browser"]
    assert "launch" not in by_id["browser"].permissions["browser"]
    assert by_id["browser"].tools == ["browser.open", "browser.search"]
    holders = [agent.id for agent in loaded if "automate" in agent.permissions.get("browser", [])]
    assert holders == ["browser-worker"]


def test_testing_selects_mock_even_on_linux(tmp_path: Path) -> None:
    assert isinstance(select_provider("testing"), MockBrowserProvider)
    if sys.platform.startswith("linux"):
        provider = select_provider("development", root=tmp_path)
        assert isinstance(provider, LinuxBrowserProvider)
        assert provider.status().applications == []


def _allow(
    _tool_id: str,
    _arguments: dict[str, object],
    _grants: object,
    _environment: str,
) -> tuple[str, str]:
    return "ALLOW", "granted by policy"


def _policy(
    tool_id: str,
    arguments: dict[str, object],
    grants: Mapping[str, Sequence[str]],
    environment: str,
) -> tuple[str, str]:
    result = PermissionEvaluator().evaluate(
        PermissionRequest(
            tool_id=tool_id,
            arguments=dict(arguments),
            grants={key: list(value) for key, value in grants.items()},
            environment=environment,
            workspace_root="/tmp",
        )
    )
    return result.decision.value, result.reason


def _request(
    action: Literal[
        "launch", "navigate", "inspect", "research", "screenshot", "interact", "automate"
    ],
    *,
    session_id: str | None = None,
    url: str | None = None,
    query: str | None = None,
    kind: Literal["click", "wait"] | None = None,
    target: str | None = None,
) -> BrowserRequest:
    return BrowserRequest(
        action=action,
        agent_id="browser-worker",
        session_id=session_id,
        url=url,
        query=query,
        kind=kind,
        target=target,
    )


def _context(tmp_path: Path) -> ToolContext:
    return ToolContext(
        task_id="task",
        agent_id="browser",
        user="local",
        workspace_root=tmp_path,
        timeout_seconds=5,
    )


def _text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
