"""Applications are looked up and launched without a shell."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

import pytest
from tests.support import runtime_settings

from core.api.routes import route_get, route_post
from core.api.runtime import build_OMNE
from core.decision.engine import DecisionEngine
from core.events.bus import EventBus
from core.intent.engine import IntentEngine
from core.orchestrator.planner.planner import plan_objective
from core.permissions.audit import AuditLog
from core.permissions.evaluator import PermissionEvaluator
from core.permissions.policies import PermissionRequest
from core.tools import build_registry
from core.tools.base import ToolContext
from core.tools.gateway import ToolGateway
from omne.applications.model import ApplicationRequest
from omne.applications.providers.linux import LinuxApplicationProvider
from omne.applications.providers.mock import MockApplicationProvider
from omne.applications.select import application_service, select_provider
from omne.applications.service import ApplicationService

_GRANTS = {"application": ["launch", "focus", "close"]}


def test_open_firefox_runs_the_pipeline_on_the_mock() -> None:
    events: list[str] = []
    service = ApplicationService(
        MockApplicationProvider(),
        sink=lambda event_type, _payload: events.append(event_type),
        authorize=_allow,
    )
    report = service.open_named("Firefox", _GRANTS, "testing")

    assert report.intent == "application.open"
    assert report.application_id == "firefox"
    assert report.permission == "ALLOW"
    assert report.launched is True
    assert report.process_observed is True
    assert report.window_observed is True
    assert report.application is not None
    assert report.application.state == "focused"
    assert report.application.commanded is False
    assert events == ["application.launched"]
    rendered = json.dumps(report.model_dump())
    assert "sh -c" not in rendered

    focused = service.apply(
        _request("focus"),
        _GRANTS,
        "testing",
        permitted=True,
    )
    assert focused.applied is True
    closed = service.apply(_request("close"), _GRANTS, "testing", permitted=True)
    assert closed.applied is True
    firefox = service.inspect("firefox")
    assert firefox is not None
    assert firefox.processes == []


def test_launch_without_permission_does_not_start_a_process() -> None:
    service = ApplicationService(MockApplicationProvider(), authorize=_policy)
    denied = service.open_named("Firefox", {}, "testing")
    confirmed = service.open_named("Firefox", _GRANTS, "testing")
    production = service.open_named("Firefox", _GRANTS, "production")

    assert denied.permission == "DENY"
    assert denied.launched is False
    assert confirmed.permission == "CONFIRM"
    assert confirmed.launched is False
    assert production.permission == "DENY"
    assert production.launched is False
    firefox = service.inspect("firefox")
    assert firefox is not None
    assert firefox.processes == []


def test_search_inspect_and_ambiguous_names() -> None:
    service = application_service("testing")

    assert [item.name for item in service.search("web")] == ["Firefox"]
    assert service.inspect("firefox") is not None
    assert service.inspect("missing") is None
    missing = service.open_named("Not Installed", _GRANTS, "testing", permitted=True)
    assert missing.report == "application was not found"
    ambiguous = service.open_named("F", _GRANTS, "testing", permitted=True)
    assert ambiguous.report == "more than one application matches"
    unsafe = service.open_named("firefox; rm", {}, "testing", permitted=True)
    assert unsafe.report == "application name is not a command"
    assert unsafe.launched is False


def test_intent_and_plan_name_the_application() -> None:
    intent = IntentEngine().interpret("Open Firefox")
    assert intent.intent == "application.open"
    assert intent.entities == {"name": "Firefox"}
    decision = DecisionEngine().decide(
        intent,
        mode="testing",
        local_available=False,
        cloud_available=False,
        cpu_wait=False,
        trace_id="trace",
    )
    assert decision.decision == "DIRECT_TOOL"
    plan = plan_objective("Open Firefox")
    assert plan[0].calls[0].tool_id == "application.launch"
    assert plan[0].calls[0].arguments == {"name": "Firefox"}
    assert "argv" not in plan[0].calls[0].arguments
    assert IntentEngine().interpret("open http://example.com").intent == "browser.open"
    shell = IntentEngine().interpret("open firefox; rm -rf /")
    assert shell.intent != "application.open"


def test_gateway_requires_confirmation_and_rejects_a_shell() -> None:
    gateway, context = _gateway()
    service = application_service("testing")
    registry = build_registry(applications=service)
    gateway = ToolGateway(registry, PermissionEvaluator(), AuditLog(), EventBus())
    result = gateway.invoke(
        tool_id="application.launch",
        arguments={"name": "Firefox"},
        context=context,
        grants=_GRANTS,
        environment="testing",
    )

    assert result.confirmation_required is True
    firefox = service.inspect("firefox")
    assert firefox is not None
    assert firefox.processes == []
    rejected = gateway.invoke(
        tool_id="application.launch",
        arguments={"name": "Firefox", "argv": ["sh", "-c", "true"]},
        context=context,
        grants=_GRANTS,
        environment="testing",
        approved=True,
    )
    assert rejected.ok is False
    assert rejected.error is not None
    assert rejected.error["code"] == "invalid_tool"


def test_linux_desktop_files_are_observed_without_launching(tmp_path: Path) -> None:
    _text(
        tmp_path / "usr" / "share" / "applications" / "firefox.desktop",
        "\n".join(
            [
                "[Desktop Entry]",
                "Type=Application",
                "Name=Firefox",
                "Exec=firefox %u",
                "Icon=firefox",
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
                "",
            ]
        ),
    )
    _text(
        tmp_path / "usr" / "share" / "applications" / "piped.desktop",
        "[Desktop Entry]\nType=Application\nName=Piped\nExec=firefox | cat\n",
    )
    command = tmp_path / "proc" / "4242" / "cmdline"
    command.parent.mkdir(parents=True)
    command.write_bytes(b"firefox\0https://example.invalid\0")
    _text(
        tmp_path / "run" / "omne" / "windows.json",
        json.dumps(
            {"windows": [{"id": "win-1", "title": "Firefox", "app_id": "firefox", "focused": True}]}
        ),
    )
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    catalog = LinuxApplicationProvider(root=tmp_path).catalog()
    after = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))

    assert after == before
    apps = {item.id: item for item in catalog.applications}
    assert apps["firefox"].launchable is True
    assert apps["firefox"].executable == "firefox"
    assert apps["firefox"].state == "focused"
    assert apps["firefox"].processes[0].pid == 4242
    assert apps["firefox"].processes[0].executable == "firefox"
    assert apps["firefox"].windows[0].title == "Firefox"
    assert apps["shell"].launchable is False
    assert apps["shell"].executable is None
    assert apps["piped"].launchable is False
    rendered = json.dumps(catalog.model_dump())
    assert "example.invalid" not in rendered
    assert "echo hi" not in rendered
    outcome = LinuxApplicationProvider(root=tmp_path).apply(_request("launch"))
    assert outcome.applied is False
    assert outcome.reason == "host application launch is not installed"
    assert outcome.catalog.commanded is False


def test_linux_provider_does_not_spawn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("subprocess")

    monkeypatch.setattr("subprocess.run", explode)
    monkeypatch.setattr("subprocess.Popen", explode)
    source = Path(sys.modules["omne.applications.providers.linux"].__file__ or "")
    text = source.read_text(encoding="utf-8")
    for banned in ("subprocess", "Popen", "shell=True", "os.system"):
        assert banned not in text
    LinuxApplicationProvider(root=tmp_path).catalog()


def test_testing_api_is_read_only(tmp_path: Path) -> None:
    omne = build_OMNE(runtime_settings(tmp_path))
    status, body = route_get(omne, "/applications", {})

    assert status.value == 200
    record = body["applications"]
    assert isinstance(record, dict)
    assert record["provider"] == "mock"
    rows = record["applications"]
    assert isinstance(rows, list)
    names = [item["name"] for item in rows if isinstance(item, dict)]
    assert names == ["Firefox", "Files"]
    assert record["commanded"] is False
    posted, payload = route_post(omne, "/applications", {"name": "Firefox"})
    assert posted.value == 404
    assert payload["error"] == "not_found"


def test_testing_selects_mock_even_on_linux(tmp_path: Path) -> None:
    assert isinstance(select_provider("testing"), MockApplicationProvider)
    if sys.platform.startswith("linux"):
        provider = select_provider("development", root=tmp_path)
        assert isinstance(provider, LinuxApplicationProvider)
        assert provider.catalog().applications == []


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


def _request(action: Literal["launch", "focus", "close"]) -> ApplicationRequest:
    return ApplicationRequest(action=action, application_id="firefox", agent_id="coding")


def _gateway() -> tuple[ToolGateway, ToolContext]:
    gateway = ToolGateway(build_registry(), PermissionEvaluator(), AuditLog(), EventBus())
    context = ToolContext(
        task_id="task",
        agent_id="coding",
        user="local",
        workspace_root=Path("/tmp"),
        timeout_seconds=5,
    )
    return gateway, context


def _text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
