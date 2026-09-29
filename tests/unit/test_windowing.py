"""Window records stay behind a grant and do not command labwc."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from tests.support import runtime_settings

from core.api.routes import route_get, route_post
from core.api.runtime import build_OMNE
from omne.windowing.model import ManagedWindow, WindowAction, WindowingState, WindowRequest
from omne.windowing.permission import CONFIRM_REQUIRED, FOREIGN_WINDOW, PRODUCTION_MANAGE
from omne.windowing.providers.linux import LinuxWindowProvider, resolve_snapshot_path
from omne.windowing.providers.mock import MockWindowProvider
from omne.windowing.select import select_provider
from omne.windowing.service import WindowingService

OWN = {"window": ["own"]}
MANAGE = {"window": ["manage"]}


def test_mock_launch_focus_close_move_and_workspace() -> None:
    provider = MockWindowProvider()
    service = WindowingService(provider)
    launched = service.apply(_launch("coding", "editor"), OWN, "testing")

    assert launched.applied is True
    assert [event.type for event in launched.events] == ["window.created", "window.focused"]
    editor = launched.state.windows[0]
    assert launched.state.focused_window_id == editor.id
    assert editor.owner == "coding"
    assert editor.workspace_id == "default"
    assert launched.state.compositor_commanded is False

    again = service.apply(_request("focus", "coding", window_id=editor.id), OWN, "testing")
    assert again.applied is True
    assert again.events == []

    notes = service.apply(_launch("coding", "notes"), OWN, "testing")
    notes_id = notes.state.focused_window_id
    assert notes_id is not None
    assert notes_id != editor.id
    assert [event.type for event in notes.events] == ["window.created", "window.focused"]

    moved = service.apply(
        _request("move", "coding", window_id=notes_id, x=40, y=50),
        OWN,
        "testing",
    )
    assert moved.applied is True
    assert moved.events[0].type == "window.changed"
    assert moved.events[0].payload["fields"] == ["x", "y"]
    assert _window(moved.state, notes_id).x == 40

    resized = service.apply(
        _request("resize", "coding", window_id=notes_id, width=640, height=480),
        OWN,
        "testing",
    )
    assert _window(resized.state, notes_id).width == 640
    assert resized.events[0].payload["fields"] == ["width", "height"]

    parked = service.apply(
        _request("workspace", "coding", window_id=notes_id, workspace_id="other"),
        OWN,
        "testing",
    )
    assert [event.type for event in parked.events] == ["window.changed", "workspace.changed"]
    assert parked.events[1].payload == {"workspace_id": "other", "window_id": notes_id}
    assert _window(parked.state, notes_id).workspace_id == "other"

    activated = service.apply(
        _request("workspace", "coding", workspace_id="other"),
        OWN,
        "testing",
    )
    assert activated.state.active_workspace_id == "other"
    assert activated.events[0].type == "workspace.changed"

    minimized = service.apply(_request("minimize", "coding", window_id=notes_id), OWN, "testing")
    assert _window(minimized.state, notes_id).minimized is True
    assert minimized.state.focused_window_id == editor.id
    assert "window.focused" in [event.type for event in minimized.events]

    maximized = service.apply(_request("maximize", "coding", window_id=editor.id), OWN, "testing")
    assert _window(maximized.state, editor.id).maximized is True
    assert maximized.events[0].payload["fields"] == ["maximized"]

    closed = service.apply(_request("close", "coding", window_id=editor.id), OWN, "testing")
    assert closed.applied is True
    assert closed.events[0].type == "window.closed"
    assert all(window.id != editor.id for window in closed.state.windows)
    assert sum(1 for window in closed.state.windows if window.focused) <= 1


def test_fullscreen_clears_the_other_window_on_the_same_monitor() -> None:
    service = WindowingService(MockWindowProvider())
    first = service.apply(_launch("coding", "editor"), OWN, "testing")
    first_id = first.state.windows[0].id
    second = service.apply(_launch("coding", "notes"), OWN, "testing")
    second_id = second.state.focused_window_id
    assert second_id is not None
    service.apply(
        _request("fullscreen", "coding", window_id=first_id, fullscreen=True),
        OWN,
        "testing",
    )
    outcome = service.apply(
        _request("fullscreen", "coding", window_id=second_id, fullscreen=True),
        OWN,
        "testing",
    )

    assert _window(outcome.state, first_id).fullscreen is False
    assert _window(outcome.state, second_id).fullscreen is True
    assert outcome.state.fullscreen_window_id == second_id
    assert outcome.events[0].payload["id"] == first_id


def test_missing_grant_denies_launch() -> None:
    outcome = WindowingService(MockWindowProvider()).apply(
        _launch("coding", "editor"), {}, "testing"
    )

    assert outcome.applied is False
    assert outcome.reason == "window grant is required"
    assert outcome.events == []
    assert outcome.state.windows == []


def test_own_grant_closes_an_owned_window_and_refuses_a_foreign_one() -> None:
    service = WindowingService(MockWindowProvider())
    launched = service.apply(_launch("coding", "editor"), OWN, "testing")
    window_id = launched.state.windows[0].id
    foreign = service.apply(_request("close", "research", window_id=window_id), OWN, "testing")

    assert foreign.applied is False
    assert foreign.reason == FOREIGN_WINDOW
    assert len(foreign.state.windows) == 1

    closed = service.apply(_request("close", "coding", window_id=window_id), OWN, "testing")
    assert closed.applied is True
    assert closed.state.windows == []


def test_manage_does_not_apply(tmp_path: Path) -> None:
    provider = _linux(tmp_path)
    service = WindowingService(provider)
    request = _request("close", "coding", window_id="browser")

    testing = service.apply(request, MANAGE, "testing")
    assert testing.applied is False
    assert testing.reason == CONFIRM_REQUIRED
    assert any(window.id == "browser" for window in testing.state.windows)

    production = service.apply(request, MANAGE, "production")
    assert production.applied is False
    assert production.reason == PRODUCTION_MANAGE
    assert any(window.id == "browser" for window in provider.state().windows)


def test_linux_snapshot_discovers_monitors_and_records_a_permitted_change(
    tmp_path: Path,
) -> None:
    provider = _linux(tmp_path)
    state = provider.state()

    assert state.provider == "labwc"
    assert state.known is True
    assert state.compositor_commanded is False
    assert [monitor.id for monitor in state.monitors] == ["HDMI-A-1", "DP-1"]
    editor = _window(state, "editor")
    assert editor.monitor_id == "HDMI-A-1"
    assert editor.x == 10
    assert _window(state, "browser").fullscreen is True
    assert state.fullscreen_window_id == "browser"

    service = WindowingService(provider)
    moved = service.apply(
        _request("move", "coding", window_id="editor", x=30, y=40, monitor_id="DP-1"),
        OWN,
        "testing",
    )
    assert moved.applied is True
    assert _window(moved.state, "editor").monitor_id == "DP-1"
    assert moved.events[0].payload["fields"] == ["x", "y", "monitor_id"]
    assert provider.state().compositor_commanded is False

    foreign = service.apply(_request("close", "coding", window_id="browser"), OWN, "testing")
    assert foreign.applied is False
    assert foreign.reason == FOREIGN_WINDOW
    assert any(window.id == "browser" for window in foreign.state.windows)

    refused = service.apply(
        _request("move", "coding", window_id="editor", x=1, y=1, monitor_id="VGA-1"),
        OWN,
        "testing",
    )
    assert refused.applied is False
    assert refused.reason == "monitor is unknown"
    assert _window(provider.state(), "editor").monitor_id == "DP-1"

    focused = service.apply(_request("focus", "coding", window_id="editor"), OWN, "testing")
    assert focused.state.focused_window_id == "editor"
    parked = service.apply(
        _request("workspace", "coding", window_id="editor", workspace_id="ws-2"),
        OWN,
        "testing",
    )
    assert _window(parked.state, "editor").workspace_id == "ws-2"
    closed = service.apply(_request("close", "coding", window_id="editor"), OWN, "testing")
    assert all(window.id != "editor" for window in closed.state.windows)
    assert provider.state().compositor_commanded is False


def test_missing_snapshot_is_not_an_empty_desktop(tmp_path: Path) -> None:
    runtime = tmp_path / "run"
    runtime.mkdir()
    (runtime / "wayland-0").write_text("not a session", encoding="utf-8")
    provider = LinuxWindowProvider(root=tmp_path)
    state = provider.state()

    assert state.known is False
    assert state.windows == []
    assert state.detail == "window list is not observed"
    outcome = provider.apply(_request("focus", "coding", window_id="editor"))
    assert outcome.applied is False
    assert outcome.reason == "window list is not observed"
    assert outcome.events == []


def test_host_root_is_not_observed() -> None:
    assert resolve_snapshot_path(Path("/"), None) is None
    state = LinuxWindowProvider(root=Path("/")).state()
    assert state.known is False
    assert state.detail == "window list is not observed"


def test_invalid_snapshot_stays_unknown(tmp_path: Path) -> None:
    path = tmp_path / "windows.json"
    path.write_text("{", encoding="utf-8")
    state = LinuxWindowProvider(root=tmp_path, snapshot_path=path).state()

    assert state.known is False
    assert state.windows == []
    assert state.detail == "window snapshot is invalid"


def test_linux_provider_does_not_run_a_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("subprocess")

    monkeypatch.setattr(subprocess, "run", explode)
    monkeypatch.setattr(subprocess, "Popen", explode)
    module = sys.modules["omne.windowing.providers.linux"]
    source = Path(module.__file__ or "")
    assert "subprocess" not in source.read_text(encoding="utf-8")
    provider = _linux(tmp_path)
    provider.state()
    provider.apply(_request("close", "coding", window_id="editor"))


def test_fixture_root_reads_the_default_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "run" / "omne" / "windows.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_snapshot()), encoding="utf-8")
    state = LinuxWindowProvider(root=tmp_path).state()

    assert state.known is True
    assert [window.id for window in state.windows] == ["editor", "browser"]


def test_testing_api_exposes_mock_window_state_and_refuses_post(tmp_path: Path) -> None:
    omne = build_OMNE(runtime_settings(tmp_path))
    status, body = route_get(omne, "/windowing", {})

    assert status.value == 200
    windowing = body["windowing"]
    assert isinstance(windowing, dict)
    assert windowing["provider"] == "mock"
    assert windowing["known"] is True
    assert windowing["windows"] == []
    assert windowing["compositor_commanded"] is False
    assert windowing["active_workspace_id"] == "default"

    posted, payload = route_post(omne, "/windowing", {"action": "close", "window_id": "editor"})
    assert posted.value == 404
    assert payload["error"] == "not_found"


def test_apply_window_publishes_window_created(tmp_path: Path) -> None:
    omne = build_OMNE(runtime_settings(tmp_path))
    outcome = omne.apply_window(_launch("coding", "editor", title="Editor"), OWN)

    assert outcome["applied"] is True
    created = [event for event in omne.list_events() if event.type == "window.created"]
    assert len(created) == 1
    assert created[0].source == "windowing"
    assert created[0].agent_id == "coding"
    assert created[0].payload["app_id"] == "editor"
    status, body = route_get(omne, "/windowing", {})
    assert status.value == 200
    windowing = body["windowing"]
    assert isinstance(windowing, dict)
    windows = windowing["windows"]
    assert isinstance(windows, list)
    assert len(windows) == 1
    assert windows[0]["owner"] == "coding"
    assert windows[0]["focused"] is True


def test_testing_selects_mock_even_on_linux(tmp_path: Path) -> None:
    assert isinstance(select_provider("testing"), MockWindowProvider)
    if sys.platform.startswith("linux"):
        provider = select_provider("development", root=tmp_path)
        assert isinstance(provider, LinuxWindowProvider)
        assert provider.state().known is False


def _launch(agent_id: str, app_id: str, *, title: str | None = None) -> WindowRequest:
    return WindowRequest(action="launch", agent_id=agent_id, app_id=app_id, title=title)


def _request(
    action: WindowAction,
    agent_id: str,
    *,
    window_id: str | None = None,
    x: int | None = None,
    y: int | None = None,
    width: int | None = None,
    height: int | None = None,
    monitor_id: str | None = None,
    workspace_id: str | None = None,
    fullscreen: bool | None = None,
) -> WindowRequest:
    return WindowRequest(
        action=action,
        agent_id=agent_id,
        window_id=window_id,
        x=x,
        y=y,
        width=width,
        height=height,
        monitor_id=monitor_id,
        workspace_id=workspace_id,
        fullscreen=fullscreen,
    )


def _window(state: WindowingState, window_id: str) -> ManagedWindow:
    return next(window for window in state.windows if window.id == window_id)


def _linux(tmp_path: Path) -> LinuxWindowProvider:
    path = tmp_path / "windows.json"
    path.write_text(json.dumps(_snapshot()), encoding="utf-8")
    return LinuxWindowProvider(root=tmp_path, snapshot_path=path)


def _snapshot() -> dict[str, object]:
    return {
        "compositor": "labwc",
        "workspaces": [
            {"id": "ws-1", "name": "One", "active": True},
            {"id": "ws-2", "name": "Two", "active": False},
        ],
        "monitors": [
            {"id": "HDMI-A-1", "name": "HDMI-A-1", "x": 0, "y": 0, "width": 1920, "height": 1080},
            {"id": "DP-1", "name": "DP-1", "x": 1920, "y": 0, "width": 1280, "height": 1024},
        ],
        "windows": [
            {
                "id": "editor",
                "title": "Editor",
                "app_id": "editor",
                "workspace_id": "ws-1",
                "monitor_id": "HDMI-A-1",
                "x": 10,
                "y": 20,
                "width": 800,
                "height": 600,
                "fullscreen": False,
                "minimized": False,
                "maximized": False,
                "focused": True,
                "mapped": True,
                "owner": "coding",
            },
            {
                "id": "browser",
                "title": "Browser",
                "app_id": "browser",
                "workspace_id": "ws-1",
                "monitor_id": "DP-1",
                "x": 0,
                "y": 0,
                "width": 1280,
                "height": 1024,
                "fullscreen": True,
                "minimized": False,
                "maximized": False,
                "focused": False,
                "mapped": True,
                "owner": None,
            },
        ],
    }
