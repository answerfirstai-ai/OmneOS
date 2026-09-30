"""Audio reads stay on the Linux stack and do not capture a microphone."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
from tests.support import runtime_settings

from core.api.routes import route_get, route_post
from core.api.runtime import build_OMNE
from core.permissions.evaluator import PermissionEvaluator
from core.permissions.policies import PermissionRequest
from omne.audio.model import AudioDevice, AudioRequest, AudioStream
from omne.audio.providers.linux import LinuxAudioProvider
from omne.audio.providers.mock import MockAudioProvider
from omne.audio.select import select_provider
from omne.audio.service import AudioService

SECRET = "s3cret-psk"


def test_mock_mixer_does_not_keep_samples() -> None:
    provider = MockAudioProvider()
    provider.set_devices(
        [
            AudioDevice(id="speaker", name="Built-in Speaker", kind="speaker", role="output"),
            AudioDevice(id="mic", name="Built-in Microphone", kind="microphone", role="input"),
        ]
    )
    provider.set_streams(
        [AudioStream(id="play", node="music", role="output", state="idle", device_id="speaker")]
    )
    volume = provider.apply(
        AudioRequest(action="set_volume", agent_id="coding", device="speaker", volume=40)
    )
    rendered = json.dumps(volume.model_dump())

    assert volume.applied is True
    assert volume.state.devices[1].volume == 40
    assert volume.events[0].type == "audio.volume.changed"
    assert SECRET not in rendered
    assert "samples" not in rendered
    assert volume.state.capture_open is False
    assert volume.state.transmitting is False
    assert volume.state.recognition == "not_implemented"

    muted = provider.apply(
        AudioRequest(action="set_mute", agent_id="coding", device="mic", muted=True)
    )
    assert muted.state.microphone == "muted"
    assert muted.events[0].type == "audio.mute.changed"
    assert muted.events[1].type == "audio.microphone.changed"
    default = provider.apply(
        AudioRequest(action="set_default", agent_id="coding", device="speaker", role="output")
    )
    assert default.state.default_output == "speaker"
    assert default.events[0].type == "audio.default.changed"
    again = provider.apply(
        AudioRequest(action="set_volume", agent_id="coding", device="speaker", volume=40)
    )
    assert again.applied is True
    assert again.events == []


def test_mutations_use_the_permission_system(tmp_path: Path) -> None:
    provider = MockAudioProvider()
    provider.set_devices(
        [AudioDevice(id="speaker", name="Built-in Speaker", kind="speaker", role="output")]
    )
    seen: list[dict[str, object]] = []

    def authorize(
        tool_id: str,
        arguments: dict[str, object],
        grants: Mapping[str, Sequence[str]],
        environment: str,
    ) -> tuple[str, str]:
        seen.append(arguments)
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

    service = AudioService(provider, authorize=authorize)
    request = AudioRequest(action="set_volume", agent_id="coding", device="speaker", volume=10)
    denied = service.apply(request, {}, "testing")
    assert denied.applied is False
    assert denied.reason.startswith("agent grant")
    assert denied.state.devices[0].volume is None

    testing = service.apply(request, {"audio": ["configure"]}, "testing")
    assert testing.applied is False
    assert "confirmation" in testing.reason
    assert testing.state.devices[0].volume is None

    production = service.apply(request, {"audio": ["configure"]}, "production")
    assert production.applied is False
    assert "denied in production" in production.reason
    assert SECRET not in json.dumps(seen)


def test_inspect_diff_publishes_stream_and_device_events() -> None:
    provider = MockAudioProvider()
    events: list[tuple[str, dict[str, object]]] = []
    service = AudioService(
        provider, sink=lambda event_type, payload: events.append((event_type, payload))
    )
    service.inspect()
    provider.set_devices(
        [AudioDevice(id="mic", name="Built-in Microphone", kind="microphone", role="input")]
    )
    provider.set_streams(
        [AudioStream(id="capture", node="capture", role="input", state="running", device_id="mic")]
    )
    state = service.inspect()

    kinds = [event[0] for event in events]
    assert state.microphone == "active"
    assert "audio.device.added" in kinds
    assert "audio.stream.started" in kinds
    assert "audio.microphone.changed" in kinds
    assert state.capture_open is False


def test_linux_dump_reports_session_facts_without_samples(tmp_path: Path) -> None:
    _dump_fixture(tmp_path)
    before = (tmp_path / "run" / "pipewire" / "dump.json").read_text(encoding="utf-8")
    report = LinuxAudioProvider(root=tmp_path).inspect()

    assert report.provider == "linux"
    assert report.observed is True
    assert report.stack == "pipewire"
    assert report.session_manager == "wireplumber"
    assert report.stack_commanded is False
    assert report.capture_open is False
    assert report.transmitting is False
    assert report.recognition == "not_implemented"
    assert report.defaults_known is True
    assert report.default_output == "alsa_output.analog-stereo"
    assert report.default_input == "alsa_input.analog-stereo"
    assert report.microphone == "active"
    by_id = {item.id: item for item in report.devices}
    speaker = by_id["alsa_output.analog-stereo"]
    assert speaker.kind == "speaker"
    assert speaker.volume == 40
    assert speaker.muted is False
    headset = by_id["bluez_output.headset"]
    assert headset.kind == "bluetooth"
    assert headset.muted is True
    assert headset.volume == 20
    assert by_id["alsa_input.analog-stereo"].kind == "microphone"
    assert report.streams[0].state == "running"
    assert report.streams[0].application == "Recorder"
    rendered = json.dumps(report.model_dump())
    assert SECRET not in rendered
    assert "samples" not in rendered

    refused = LinuxAudioProvider(root=tmp_path).apply(
        AudioRequest(
            action="set_mute", agent_id="coding", device="alsa_output.analog-stereo", muted=True
        )
    )
    assert refused.applied is False
    assert refused.reason == "host audio stack is not commanded"
    assert refused.events == []
    after = (tmp_path / "run" / "pipewire" / "dump.json").read_text(encoding="utf-8")
    assert after == before


def test_alsa_capture_is_not_a_volume(tmp_path: Path) -> None:
    _text(
        tmp_path / "proc" / "asound" / "cards",
        " 0 [PCH            ]: HDA-Intel - HDA Intel PCH\n",
    )
    _text(
        tmp_path / "proc" / "asound" / "pcm",
        "00-00: ALC897 Analog : ALC897 Analog : playback 1 : capture 1\n"
        "00-03: HDMI 0 : HDMI 0 : playback 1\n",
    )
    _text(tmp_path / "proc" / "asound" / "card0" / "pcm0c" / "sub0" / "status", "state: RUNNING\n")
    _text(tmp_path / "proc" / "asound" / "card0" / "pcm0p" / "sub0" / "status", "state: closed\n")
    report = LinuxAudioProvider(root=tmp_path).inspect()

    assert report.stack == "alsa"
    assert report.defaults_known is False
    assert report.default_output is None
    assert report.microphone == "active"
    by_id = {item.id: item for item in report.devices}
    assert by_id["alsa-card0-pcm0-output"].kind == "speaker"
    assert by_id["alsa-card0-pcm0-output"].volume is None
    assert by_id["alsa-card0-pcm0-input"].kind == "microphone"
    assert by_id["alsa-card0-pcm3-output"].kind == "other"
    assert report.capture_open is False
    assert [item.role for item in report.streams] == ["input"]


def test_missing_audio_stack_is_absent(tmp_path: Path) -> None:
    report = LinuxAudioProvider(root=tmp_path).inspect()

    assert report.observed is True
    assert report.stack == "unknown"
    assert report.devices == []
    assert report.microphone == "absent"
    assert report.streams_known is True
    assert report.defaults_known is False
    assert report.capture_open is False


def test_linux_provider_does_not_run_a_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("subprocess")

    monkeypatch.setattr("subprocess.run", explode)
    monkeypatch.setattr("subprocess.Popen", explode)
    source = Path(sys.modules["omne.audio.providers.linux"].__file__ or "")
    text = source.read_text(encoding="utf-8")
    assert "subprocess" not in text
    assert "write_text" not in text
    assert "pw-dump" not in text
    assert "wpctl" not in text
    assert "pactl" not in text
    LinuxAudioProvider(root=tmp_path).inspect()
    LinuxAudioProvider(root=tmp_path).apply(
        AudioRequest(action="set_volume", agent_id="coding", device="speaker", volume=10)
    )


def test_testing_api_is_a_read_only_mock_and_voice_stays_off(tmp_path: Path) -> None:
    omne = build_OMNE(runtime_settings(tmp_path))
    status, body = route_get(omne, "/audio", {})

    assert status.value == 200
    audio = body["audio"]
    assert isinstance(audio, dict)
    assert audio["provider"] == "mock"
    assert audio["observed"] is True
    assert audio["stack_commanded"] is False
    assert audio["capture_open"] is False
    assert audio["transmitting"] is False
    assert audio["recognition"] == "not_implemented"
    assert audio["microphone"] == "absent"
    assert audio["devices"] == []
    voice = omne.voice_status()
    assert voice["listening"] is False
    assert voice["hardware"] == "unavailable"
    assert voice["permission"] == "DENY"
    posted, payload = route_post(omne, "/audio", {"action": "set_mute", "muted": True})
    assert posted.value == 404
    assert payload["error"] == "not_found"


def test_testing_selects_mock_even_on_linux(tmp_path: Path) -> None:
    assert isinstance(select_provider("testing"), MockAudioProvider)
    if sys.platform.startswith("linux"):
        provider = select_provider("development", root=tmp_path)
        assert isinstance(provider, LinuxAudioProvider)
        assert provider.inspect().microphone == "absent"


def _dump_fixture(root: Path) -> None:
    _text(root / "usr" / "lib" / "systemd" / "user" / "pipewire.service", "[Service]\n")
    _text(root / "usr" / "lib" / "systemd" / "user" / "wireplumber.service", "[Service]\n")
    _text(
        root / "run" / "pipewire" / "dump.json",
        json.dumps(
            [
                {
                    "id": 30,
                    "type": "PipeWire:Interface:Node",
                    "props": {
                        "node.name": "alsa_output.analog-stereo",
                        "node.description": "Built-in Speaker",
                        "media.class": "Audio/Sink",
                    },
                    "info": {
                        "params": {"Props": [{"volume": 0.4, "mute": False, "secret": SECRET}]},
                        "state": "running",
                    },
                },
                {
                    "id": 31,
                    "type": "PipeWire:Interface:Node",
                    "props": {
                        "node.name": "alsa_input.analog-stereo",
                        "node.description": "Built-in Microphone",
                        "media.class": "Audio/Source",
                    },
                    "info": {"params": {"Props": [{"volume": 1.0, "mute": False}]}},
                },
                {
                    "id": 52,
                    "type": "PipeWire:Interface:Node",
                    "props": {
                        "node.name": "bluez_output.headset",
                        "node.description": "Headset",
                        "media.class": "Audio/Sink",
                        "device.bus": "bluetooth",
                    },
                    "info": {"params": {"Props": [{"volume": 0.2, "mute": True}]}},
                },
                {
                    "id": 80,
                    "type": "PipeWire:Interface:Node",
                    "props": {
                        "node.name": "speech-client",
                        "application.name": "Recorder",
                        "media.class": "Stream/Input/Audio",
                    },
                    "info": {"state": "running"},
                },
                {
                    "id": 2,
                    "type": "PipeWire:Interface:Metadata",
                    "props": {"metadata.name": "default"},
                    "metadata": [
                        {
                            "key": "default.audio.sink",
                            "value": '{"name":"alsa_output.analog-stereo"}',
                        },
                        {
                            "key": "default.audio.source",
                            "value": '{"name":"alsa_input.analog-stereo"}',
                        },
                    ],
                },
            ]
        ),
    )


def _text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
