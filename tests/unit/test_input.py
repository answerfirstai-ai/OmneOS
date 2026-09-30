"""Input bindings come from configuration and do not record keystrokes."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
from tests.conftest import ROOT
from tests.support import runtime_settings

from core.api.routes import route_get, route_post
from core.api.runtime import build_OMNE
from core.config.settings import load_settings
from core.permissions.evaluator import PermissionEvaluator
from core.permissions.policies import PermissionRequest
from omne.input.model import InputDevice, InputRequest
from omne.input.providers.linux import LinuxInputProvider
from omne.input.providers.mock import MockInputProvider
from omne.input.select import select_provider
from omne.input.service import InputService

BITMAP = "KEY=1234abcd"


def test_activation_opens_the_command_surface_without_a_key() -> None:
    provider = MockInputProvider()
    service = InputService(
        provider,
        activation="alt+ctrl+space",
        cancel="ctrl+alt+escape",
        push_to_talk="shift+ctrl+alt+space",
    )
    state = service.inspect()

    assert state.activation is not None
    assert state.activation.label == "ctrl+alt+space"
    assert state.cancel is not None
    assert state.cancel.label == "ctrl+alt+escape"
    assert state.push_to_talk_state == "prepared"
    assert state.delivery == "desktop"
    assert state.host_grab is False
    assert state.key_stream is False
    assert state.listening is False
    assert state.attention == "idle"

    opened = service.apply(
        InputRequest(action="activate", agent_id="coding"), {"input": ["use"]}, "testing"
    )
    assert opened.applied is False
    assert opened.state.attention == "idle"

    allowed = InputService(
        provider,
        activation="ctrl+alt+space",
        cancel="ctrl+alt+escape",
        push_to_talk="ctrl+alt+shift+space",
        authorize=_allow,
    )
    opened = allowed.apply(
        InputRequest(action="activate", agent_id="coding"), {"input": ["use"]}, "testing"
    )
    assert opened.applied is True
    assert opened.state.attention == "command"
    assert opened.state.revision == 1
    assert opened.events[0].type == "input.activated"
    assert "key" not in opened.events[0].payload
    rendered = json.dumps(opened.model_dump())
    assert BITMAP not in rendered

    cancelled = allowed.apply(
        InputRequest(action="cancel", agent_id="coding"), {"input": ["use"]}, "testing"
    )
    assert cancelled.applied is True
    assert cancelled.state.attention == "idle"
    assert cancelled.events[0].type == "input.cancelled"
    again = allowed.apply(
        InputRequest(action="cancel", agent_id="coding"), {"input": ["use"]}, "testing"
    )
    assert again.events == []


def test_bind_requires_confirmation_and_does_not_grab(tmp_path: Path) -> None:
    provider = MockInputProvider()
    seen: list[dict[str, object]] = []

    def authorize(
        tool_id: str,
        arguments: dict[str, object],
        grants: Mapping[str, Sequence[str]],
        environment: str,
    ) -> tuple[str, str]:
        seen.append({"tool": tool_id, **arguments})
        result = PermissionEvaluator().evaluate(
            PermissionRequest(
                tool_id=tool_id,
                arguments=arguments,
                grants={key: list(value) for key, value in grants.items()},
                environment=environment,
                workspace_root=str(tmp_path),
            )
        )
        return result.decision.value, result.reason

    service = InputService(provider, activation="ctrl+alt+space", authorize=authorize)
    request = InputRequest(action="bind", agent_id="coding")
    denied = service.apply(request, {}, "testing")
    assert denied.applied is False
    assert denied.reason.startswith("agent grant")
    assert denied.state.host_grab is False

    testing = service.apply(request, {"input": ["bind"]}, "testing")
    assert testing.applied is False
    assert "confirmation" in testing.reason

    production = service.apply(request, {"input": ["bind"]}, "production")
    assert production.applied is False
    assert "denied in production" in production.reason
    assert BITMAP not in json.dumps(seen)


def test_device_changes_publish_events_without_keycodes() -> None:
    provider = MockInputProvider()
    events: list[str] = []
    service = InputService(provider, sink=lambda event_type, _payload: events.append(event_type))
    service.inspect()
    provider.set_devices([InputDevice(id="keyboard-test", name="Keyboard", kind="keyboard")])
    state = service.inspect()

    assert state.devices[0].kind == "keyboard"
    assert events == ["input.device.added"]
    assert state.key_stream is False


def test_linux_devices_drop_key_bitmaps(tmp_path: Path) -> None:
    _text(tmp_path / "usr" / "bin" / "labwc", "")
    portal = tmp_path / "usr" / "share" / "dbus-1" / "interfaces"
    _text(portal / "org.freedesktop.impl.portal.GlobalShortcuts.xml", "<interface/>\n")
    _text(
        tmp_path / "proc" / "bus" / "input" / "devices",
        "\n".join(
            [
                'N: Name="AT Translated Set 2 keyboard"',
                "H: Handlers=sysrq kbd event0",
                f"B: {BITMAP}",
                "",
                'N: Name="Virtual mouse"',
                "H: Handlers=mouse0 event1",
                f"B: {BITMAP}",
                "",
                'N: Name="Power button"',
                "H: Handlers=kbd event2",
                "",
                "",
            ]
        ),
    )
    before = (tmp_path / "proc" / "bus" / "input" / "devices").read_text(encoding="utf-8")
    report = LinuxInputProvider(root=tmp_path).inspect()

    assert report.provider == "linux"
    assert report.observed is True
    assert report.compositor == "labwc"
    assert report.portal == "global-shortcuts"
    assert report.devices_known is True
    names = {item.name: item.kind for item in report.devices}
    assert names["AT Translated Set 2 keyboard"] == "keyboard"
    assert names["Virtual mouse"] == "mouse"
    rendered = json.dumps(report.model_dump())
    assert BITMAP not in rendered
    assert "event0" not in rendered
    assert "event1" not in rendered
    LinuxInputProvider(root=tmp_path).apply(InputRequest(action="bind", agent_id="coding"))
    assert (tmp_path / "proc" / "bus" / "input" / "devices").read_text(encoding="utf-8") == before


def test_missing_devices_stay_empty(tmp_path: Path) -> None:
    report = LinuxInputProvider(root=tmp_path).inspect()

    assert report.observed is True
    assert report.devices == []
    assert report.devices_known is True
    assert report.compositor == "unknown"
    assert report.portal == "unknown"


def test_linux_provider_does_not_open_an_event_node(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("subprocess")

    monkeypatch.setattr("subprocess.run", explode)
    monkeypatch.setattr("subprocess.Popen", explode)
    source = Path(sys.modules["omne.input.providers.linux"].__file__ or "")
    text = source.read_text(encoding="utf-8")
    assert "subprocess" not in text
    assert "write_text" not in text
    assert "/dev/input" not in text
    assert "evtest" not in text
    LinuxInputProvider(root=tmp_path).inspect()


def test_shipped_shortcut_is_configuration_not_core_source() -> None:
    settings = load_settings(
        environ={},
        config_path=ROOT / "configs" / "development" / "OMNE.toml",
        cwd=ROOT,
    )

    assert settings.activation_shortcut
    assert settings.cancel_shortcut
    assert settings.push_to_talk_shortcut
    assert settings.activation_shortcut != settings.cancel_shortcut
    for folder in (ROOT / "core", ROOT / "omne"):
        for path in folder.rglob("*.py"):
            assert settings.activation_shortcut not in path.read_text(encoding="utf-8")
    for path in (ROOT / "shell" / "src").rglob("*.ts"):
        if path.name.endswith(".test.ts"):
            continue
        assert settings.activation_shortcut not in path.read_text(encoding="utf-8")


def test_unmodified_shortcut_is_rejected(tmp_path: Path) -> None:
    config = tmp_path / "OMNE.toml"
    config.write_text('activation_shortcut = "a"\n', encoding="utf-8")

    from core.config.errors import ConfigurationError

    with pytest.raises(ConfigurationError, match="shortcut"):
        load_settings(config_path=config, environ={}, cwd=tmp_path)


def test_testing_api_stays_unbound_and_voice_stays_off(tmp_path: Path) -> None:
    omne = build_OMNE(runtime_settings(tmp_path))
    status, body = route_get(omne, "/input", {})

    assert status.value == 200
    record = body["input"]
    assert isinstance(record, dict)
    assert record["provider"] == "mock"
    assert record["activation"] is None
    assert record["delivery"] == "unbound"
    assert record["host_grab"] is False
    assert record["key_stream"] is False
    assert record["listening"] is False
    assert record["push_to_talk_state"] == "unconfigured"
    voice = omne.voice_status()
    assert voice["listening"] is False
    assert voice["permission"] == "DENY"
    posted, payload = route_post(omne, "/input", {"action": "activate"})
    assert posted.value == 404
    assert payload["error"] == "not_found"


def test_testing_selects_mock_even_on_linux(tmp_path: Path) -> None:
    assert isinstance(select_provider("testing"), MockInputProvider)
    if sys.platform.startswith("linux"):
        provider = select_provider("development", root=tmp_path)
        assert isinstance(provider, LinuxInputProvider)
        assert provider.inspect().devices == []


def _allow(
    _tool_id: str,
    _arguments: dict[str, object],
    _grants: Mapping[str, Sequence[str]],
    _environment: str,
) -> tuple[str, str]:
    return "ALLOW", "granted by policy"


def _text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
