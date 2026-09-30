"""The session reports labwc only after the Wayland socket exists."""

from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

from tests.conftest import ROOT


def _session_module() -> ModuleType:
    path = ROOT / "system" / "linux" / "omne-session"
    loader = SourceFileLoader("omne_session", str(path))
    spec = importlib.util.spec_from_loader("omne_session", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


session = _session_module()


def test_markers_stay_empty_until_the_socket_exists() -> None:
    assert session.session_markers(alive=True, socket_ready=False, desktop_ready=True) == []
    assert session.session_markers(alive=False, socket_ready=True, desktop_ready=True) == []


def test_markers_follow_the_socket_and_the_shell() -> None:
    running = session.session_markers(alive=True, socket_ready=True, desktop_ready=False)
    assert running == ["labwc running", "wayland display ready"]
    ready = session.session_markers(alive=True, socket_ready=True, desktop_ready=True)
    assert ready == ["labwc running", "wayland display ready", "OMNE desktop ready"]


def test_renderer_falls_back_when_the_render_node_is_absent() -> None:
    assert session.renderer_environment(["card0"]) == {"WLR_RENDERER": "pixman"}
    assert session.renderer_environment(["card0", "renderD128"]) == {}


def test_gpu_attempt_falls_back_to_pixman() -> None:
    environments = session.startup_environments({"HOME": "/var/lib/omne"}, ["card1", "renderD128"])
    assert environments[0]["WLR_BACKENDS"] == "drm"
    assert "WLR_RENDERER" not in environments[0]
    assert environments[1]["WLR_RENDERER"] == "pixman"
    assert "WAYLAND_DISPLAY" not in environments[1]


def test_labwc_uses_drm_instead_of_a_nested_display() -> None:
    env = session.labwc_environment(
        {"WAYLAND_DISPLAY": "wayland-1", "DISPLAY": ":0", "HOME": "/var/lib/omne"},
        ["card1", "renderD128"],
    )
    assert "WAYLAND_DISPLAY" not in env
    assert "DISPLAY" not in env
    assert env["WLR_BACKENDS"] == "drm"
    assert "WLR_RENDERER" not in env
    assert env["HOME"] == "/var/lib/omne"


def test_session_unit_does_not_gate_multi_user() -> None:
    unit = Path("system/linux/omne-session.service").read_text(encoding="utf-8")
    target = Path("system/linux/omne.target").read_text(encoding="utf-8")
    assert "After=multi-user.target" in unit
    assert "omne-session.service" not in target
    assert "WantedBy=multi-user.target" in unit
    assert "WAYLAND_DISPLAY" not in unit
