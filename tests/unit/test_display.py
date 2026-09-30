"""Display diagnostics stay empty until Linux graphics devices exist."""

from __future__ import annotations

import socket
import sys
from pathlib import Path

from tests.support import runtime_settings

from core.api.routes import route_get
from core.api.runtime import build_OMNE
from omne.display.providers.linux import LinuxDisplayProvider
from omne.display.providers.mock import MockDisplayProvider
from omne.display.select import select_provider


def test_testing_api_uses_the_mock_provider(tmp_path: Path) -> None:
    omne = build_OMNE(runtime_settings(tmp_path))
    status, body = route_get(omne, "/display", {})

    assert status.value == 200
    display = body["display"]
    assert isinstance(display, dict)
    assert display["provider"] == "mock"
    assert display["can_launch"] is False
    assert display["session"] == "not_running"
    assert display["monitors"] == []
    assert display["windows"] == []
    assert display["surface"]["active"] is False
    assert display["surface"]["uri"] == "http://127.0.0.1:4173/?surface=desktop"
    assert display["missing"] == ["graphical session"]


def test_mock_provider_does_not_invent_a_monitor() -> None:
    report = MockDisplayProvider().diagnose()

    assert report.provider == "mock"
    assert report.linux is sys.platform.startswith("linux")
    assert report.drm == "absent"
    assert report.gpu_acceleration == "unavailable"
    assert report.compositor_present is False
    assert report.fullscreen.known is True
    assert report.fullscreen.active is False
    assert report.can_launch is False


def test_testing_selects_mock_even_on_linux() -> None:
    provider = select_provider("testing")

    assert isinstance(provider, MockDisplayProvider)


def test_linux_provider_reports_what_is_missing(tmp_path: Path) -> None:
    report = LinuxDisplayProvider(root=tmp_path, environ={}).diagnose()

    assert report.provider == "labwc"
    assert report.session == "not_running"
    assert report.wayland is False
    assert report.windows_known is False
    assert report.fullscreen.known is False
    assert report.can_launch is False
    assert report.missing == [
        "drm card",
        "render node",
        "labwc",
        "connected monitor",
        "input device",
    ]


def test_linux_provider_can_launch_without_starting_a_session(tmp_path: Path) -> None:
    _card(tmp_path, "card0")
    _render(tmp_path, "renderD128")
    _connector(tmp_path, "card0-HDMI-A-1", status="connected", modes="1920x1080\n1280x720\n")
    _event(tmp_path, "event0")
    _labwc(tmp_path)

    report = LinuxDisplayProvider(root=tmp_path, environ={}).diagnose()

    assert report.can_launch is True
    assert report.missing == []
    assert report.drm == "present"
    assert report.gpu_acceleration == "present"
    assert report.compositor == "labwc"
    assert report.input == "present"
    assert report.session == "not_running"
    assert report.wayland is False
    assert len(report.monitors) == 1
    monitor = report.monitors[0]
    assert monitor.name == "HDMI-A-1"
    assert monitor.width == 1920
    assert monitor.height == 1080
    assert monitor.refresh_hz is None
    assert monitor.primary is False
    assert report.windows == []


def test_linux_provider_launches_with_pixman_when_the_render_node_is_absent(
    tmp_path: Path,
) -> None:
    _card(tmp_path, "card0")
    _connector(tmp_path, "card0-Virtual-1", status="connected", modes="1280x800\n")
    _event(tmp_path, "event0")
    _labwc(tmp_path)

    report = LinuxDisplayProvider(root=tmp_path, environ={}).diagnose()

    assert report.can_launch is True
    assert report.gpu_acceleration == "absent"
    assert report.missing == ["render node"]
    assert report.drm == "present"


def test_linux_provider_reads_several_monitors_and_refresh(tmp_path: Path) -> None:
    _card(tmp_path, "card0")
    _render(tmp_path, "renderD128")
    _connector(
        tmp_path,
        "card0-eDP-1",
        status="connected",
        modes="1280x800@60\n",
        enabled="enabled",
    )
    _connector(tmp_path, "card0-HDMI-A-1", status="disconnected", modes="1920x1080\n")
    _connector(
        tmp_path,
        "card0-DP-1",
        status="connected",
        modes="3840x2160@59.94\n",
        enabled="disabled",
    )
    _event(tmp_path, "event3")
    _labwc(tmp_path)

    report = LinuxDisplayProvider(root=tmp_path, environ={}).diagnose()
    names = [monitor.name for monitor in report.monitors]

    assert names == ["DP-1", "eDP-1"]
    primary = next(monitor for monitor in report.monitors if monitor.primary)
    assert primary.name == "eDP-1"
    assert primary.refresh_hz == 60
    other = next(monitor for monitor in report.monitors if monitor.name == "DP-1")
    assert other.refresh_hz == 59.94
    assert other.primary is False


def test_wayland_socket_marks_a_session_without_inventing_windows(tmp_path: Path) -> None:
    runtime = tmp_path / "run"
    runtime.mkdir()
    sock = socket.socket(socket.AF_UNIX)
    sock.bind(str(runtime / "wayland-0"))
    try:
        report = LinuxDisplayProvider(
            root=tmp_path,
            environ={"XDG_RUNTIME_DIR": str(runtime), "WAYLAND_DISPLAY": "wayland-0"},
        ).diagnose()
    finally:
        sock.close()

    assert report.wayland is True
    assert report.session == "running"
    assert report.windows_known is False
    assert report.windows == []
    assert report.can_launch is False


def test_unreadable_dri_stays_unavailable(tmp_path: Path) -> None:
    dri = tmp_path / "dev" / "dri"
    dri.mkdir(parents=True)
    dri.chmod(0)
    try:
        report = LinuxDisplayProvider(root=tmp_path, environ={}).diagnose()
    finally:
        dri.chmod(0o755)

    assert report.drm == "unavailable"
    assert report.gpu_acceleration == "unavailable"


def _card(root: Path, name: str) -> None:
    path = root / "dev" / "dri"
    path.mkdir(parents=True, exist_ok=True)
    (path / name).write_text("", encoding="utf-8")


def _render(root: Path, name: str) -> None:
    _card(root, name)


def _event(root: Path, name: str) -> None:
    path = root / "dev" / "input"
    path.mkdir(parents=True, exist_ok=True)
    (path / name).write_text("", encoding="utf-8")


def _labwc(root: Path) -> None:
    path = root / "usr" / "bin"
    path.mkdir(parents=True, exist_ok=True)
    (path / "labwc").write_text("", encoding="utf-8")


def _connector(
    root: Path,
    name: str,
    *,
    status: str,
    modes: str,
    enabled: str | None = None,
) -> None:
    path = root / "sys" / "class" / "drm" / name
    path.mkdir(parents=True)
    (path / "status").write_text(status + "\n", encoding="utf-8")
    (path / "modes").write_text(modes, encoding="utf-8")
    if enabled is not None:
        (path / "enabled").write_text(enabled + "\n", encoding="utf-8")
