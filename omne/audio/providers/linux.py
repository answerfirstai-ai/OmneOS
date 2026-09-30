"""Read the Linux audio stack without opening a device.

PipeWire remains the session mixer when it is installed. WirePlumber remains
the session manager. This module reads proc, sysfs, unit files, and a dump
file the session has already written. It does not start a session, open a
capture device, or write a mixer control.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from omne.audio.model import (
    ApplyOutcome,
    AudioDevice,
    AudioRequest,
    AudioState,
    AudioStream,
    DeviceKind,
    DeviceRole,
    SessionManager,
    StackName,
    derive_microphone,
)

HOST_UNCHANGED = "host audio stack is not commanded"
_PCM_LINE = re.compile(r"^(\d+)-(\d+):\s*([^:]+?)\s*:")
_CARD_LINE = re.compile(r"^\s*(\d+)\s+\[([^\]]+)\]:")
_SYS_PCM = re.compile(r"^pcmC(\d+)D(\d+)([pc])$")
_UNIT_DIRS = (
    Path("usr/lib/systemd/user"),
    Path("lib/systemd/user"),
    Path("etc/systemd/user"),
    Path("usr/lib/systemd/system"),
    Path("lib/systemd/system"),
)


class LinuxAudioProvider:
    """Report devices, defaults, and streams from one filesystem root."""

    def __init__(self, *, root: Path | None = None) -> None:
        self._root = root if root is not None else Path("/")

    def inspect(self) -> AudioState:
        if not self._root.is_dir():
            return AudioState(
                provider="linux",
                observed=False,
                stack="unknown",
                session_manager="unknown",
                defaults_known=False,
                streams_known=False,
                microphone="unknown",
                gaps=["linux"],
            )
        gaps: list[str] = []
        stack, session = _stack(self._root)
        parsed, dump_gap = _dump(self._root)
        if dump_gap:
            gaps.append(dump_gap)
        if parsed is None:
            devices, streams, devices_known, streams_known, alsa_gap = _alsa(self._root)
            if alsa_gap:
                gaps.append(alsa_gap)
            default_input = None
            default_output = None
            defaults_known = False
        else:
            devices = parsed[0]
            streams = parsed[1]
            default_input = parsed[2]
            default_output = parsed[3]
            defaults_known = parsed[4]
            devices_known = True
            streams_known = True
            stack = "pipewire"
        microphone = derive_microphone(
            devices,
            streams,
            devices_known=devices_known,
            streams_known=streams_known,
        )
        return AudioState(
            provider="linux",
            observed=True,
            stack=stack,
            session_manager=session,
            devices=sorted(devices, key=lambda item: item.id),
            default_input=default_input,
            default_output=default_output,
            defaults_known=defaults_known,
            streams=sorted(streams, key=lambda item: item.id),
            streams_known=streams_known,
            microphone=microphone,
            gaps=sorted(set(gaps)),
        )

    def apply(self, request: AudioRequest) -> ApplyOutcome:
        del request
        return ApplyOutcome(
            applied=False,
            reason=HOST_UNCHANGED,
            state=self.inspect(),
            events=[],
        )


def _stack(root: Path) -> tuple[StackName, SessionManager]:
    pipewire = _unit(root, "pipewire.service")
    wireplumber = _unit(root, "wireplumber.service")
    session: SessionManager = "wireplumber" if wireplumber else "unknown"
    if pipewire or wireplumber:
        return "pipewire", session
    if (root / "proc" / "asound").exists() or (root / "sys" / "class" / "sound").exists():
        return "alsa", session
    return "unknown", session


def _unit(root: Path, name: str) -> bool:
    return any((root / directory / name).is_file() for directory in _UNIT_DIRS)


def _dump(
    root: Path,
) -> tuple[
    tuple[list[AudioDevice], list[AudioStream], str | None, str | None, bool] | None, str | None
]:
    path = root / "run" / "pipewire" / "dump.json"
    if not path.exists():
        return None, None
    text = _optional(path)
    if text is None:
        return None, "pipewire"
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return None, "pipewire"
    if not isinstance(loaded, list):
        return None, "pipewire"
    devices: list[AudioDevice] = []
    streams: list[AudioStream] = []
    default_input: str | None = None
    default_output: str | None = None
    defaults_known = False
    for item in loaded:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type", ""))
        if kind.endswith("Interface:Metadata"):
            found_input, found_output, known = _defaults(item)
            if known:
                defaults_known = True
                default_input = found_input
                default_output = found_output
            continue
        if not kind.endswith("Interface:Node"):
            continue
        props = _node_props(item)
        media = props.get("media.class")
        if not isinstance(media, str):
            continue
        if media in {"Audio/Sink", "Audio/Source"}:
            device = _node_device(item, props, media)
            if device is not None:
                devices.append(device)
        elif media in {"Stream/Output/Audio", "Stream/Input/Audio"}:
            streams.append(_node_stream(item, props, media))
    return (devices, streams, default_input, default_output, defaults_known), None


def _defaults(item: dict[str, Any]) -> tuple[str | None, str | None, bool]:
    props = _node_props(item)
    name = props.get("metadata.name")
    if name not in {None, "default"}:
        return None, None, False
    rows = item.get("metadata")
    if not isinstance(rows, list):
        return None, None, False
    default_input: str | None = None
    default_output: str | None = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = row.get("key")
        parsed = _meta_name(row.get("value"))
        if key == "default.audio.sink":
            default_output = parsed
        elif key == "default.audio.source":
            default_input = parsed
    return default_input, default_output, True


def _node_device(item: dict[str, Any], props: dict[str, Any], media: str) -> AudioDevice | None:
    role: DeviceRole = "output" if media == "Audio/Sink" else "input"
    node_name = props.get("node.name")
    description = props.get("node.description")
    if isinstance(node_name, str) and node_name.strip():
        device_id = node_name.strip()
    else:
        raw_id = item.get("id")
        if not isinstance(raw_id, int):
            return None
        device_id = f"pw-{raw_id}"
    if isinstance(description, str) and description.strip():
        label = description.strip()
    else:
        label = device_id
    mixer = _mixer(item)
    bus = props.get("device.bus")
    return AudioDevice(
        id=device_id,
        name=label,
        kind=_kind(device_id, label, role, bus if isinstance(bus, str) else None),
        role=role,
        volume=mixer[0],
        muted=mixer[1],
        bus=bus if isinstance(bus, str) and bus else None,
    )


def _node_stream(item: dict[str, Any], props: dict[str, Any], media: str) -> AudioStream:
    role: DeviceRole = "output" if media == "Stream/Output/Audio" else "input"
    raw_id = item.get("id")
    stream_id = f"pw-stream-{raw_id}" if isinstance(raw_id, int) else "pw-stream"
    node = props.get("node.name")
    application = props.get("application.name")
    info = item.get("info")
    state = "unknown"
    if isinstance(info, dict) and isinstance(info.get("state"), str) and info["state"].strip():
        state = info["state"].strip().lower()
    return AudioStream(
        id=stream_id,
        node=node.strip() if isinstance(node, str) and node.strip() else stream_id,
        role=role,
        state=state,
        application=application.strip()
        if isinstance(application, str) and application.strip()
        else None,
    )


def _mixer(item: dict[str, Any]) -> tuple[int | None, bool | None]:
    info = item.get("info")
    if not isinstance(info, dict):
        return None, None
    params = info.get("params")
    if not isinstance(params, dict):
        return None, None
    props = params.get("Props")
    row: dict[str, Any] | None = None
    if isinstance(props, list):
        for candidate in props:
            if isinstance(candidate, dict):
                row = candidate
                break
    elif isinstance(props, dict):
        row = props
    if row is None:
        return None, None
    return _percent(row.get("volume")), _flag(row.get("mute"))


def _percent(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    if number < 0 or number > 1:
        return None
    return round(number * 100)


def _flag(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _meta_name(value: object) -> str | None:
    if isinstance(value, dict):
        name = value.get("name")
        return name.strip() if isinstance(name, str) and name.strip() else None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.startswith("{"):
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError:
            return None
        if isinstance(loaded, dict) and isinstance(loaded.get("name"), str):
            name = loaded["name"].strip()
            return name or None
        return None
    return text or None


def _node_props(item: dict[str, Any]) -> dict[str, Any]:
    found: dict[str, Any] = {}
    raw = item.get("props")
    if isinstance(raw, dict):
        found.update(raw)
    info = item.get("info")
    if isinstance(info, dict) and isinstance(info.get("props"), dict):
        found.update(info["props"])
    return found


def _alsa(
    root: Path,
) -> tuple[list[AudioDevice], list[AudioStream], bool, bool, str | None]:
    if (root / "proc" / "asound" / "pcm").exists():
        return _alsa_proc(root)
    return _alsa_sys(root)


def _alsa_sys(
    root: Path,
) -> tuple[list[AudioDevice], list[AudioStream], bool, bool, str | None]:
    directory = root / "sys" / "class" / "sound"
    if not directory.exists():
        return [], [], True, True, None
    listed = _list_dir(directory)
    if listed is None:
        return [], [], False, False, "devices"
    devices: list[AudioDevice] = []
    streams: list[AudioStream] = []
    streams_known = True
    gap: str | None = None
    for path in listed:
        match = _SYS_PCM.fullmatch(path.name)
        if match is None:
            continue
        card, device, direction = match.group(1), match.group(2), match.group(3)
        role: DeviceRole = "output" if direction == "p" else "input"
        card_name = _optional(directory / f"card{card}" / "id") or ""
        built, active, known = _pcm(root, card, device, card_name, card_name, role)
        devices.append(built)
        if not known:
            streams_known = False
            gap = "streams"
        elif active is not None:
            streams.append(active)
    return devices, streams, True, streams_known, gap


def _alsa_proc(
    root: Path,
) -> tuple[list[AudioDevice], list[AudioStream], bool, bool, str | None]:
    path = root / "proc" / "asound" / "pcm"
    text = _optional(path)
    if text is None:
        return [], [], False, False, "devices"
    cards = _card_names(root)
    devices: list[AudioDevice] = []
    streams: list[AudioStream] = []
    streams_known = True
    gap: str | None = None
    for line in text.splitlines():
        match = _PCM_LINE.match(line)
        if match is None:
            continue
        card = str(int(match.group(1)))
        device = str(int(match.group(2)))
        label = match.group(3).strip()
        card_name = cards.get(card, "")
        if "playback" in line:
            built, active, known = _pcm(root, card, device, label, card_name, "output")
            devices.append(built)
            if not known:
                streams_known = False
                gap = "streams"
            elif active is not None:
                streams.append(active)
        if "capture" in line:
            built, active, known = _pcm(root, card, device, label, card_name, "input")
            devices.append(built)
            if not known:
                streams_known = False
                gap = "streams"
            elif active is not None:
                streams.append(active)
    return devices, streams, True, streams_known, gap


def _card_names(root: Path) -> dict[str, str]:
    text = _optional(root / "proc" / "asound" / "cards")
    if text is None:
        return {}
    names: dict[str, str] = {}
    for line in text.splitlines():
        match = _CARD_LINE.match(line)
        if match is not None:
            names[match.group(1)] = match.group(2).strip()
    return names


def _pcm(
    root: Path,
    card: str,
    device: str,
    label: str,
    card_name: str,
    role: DeviceRole,
) -> tuple[AudioDevice, AudioStream | None, bool]:
    direction = "p" if role == "output" else "c"
    device_id = f"alsa-card{card}-pcm{device}-{role}"
    status = (
        root / "proc" / "asound" / f"card{card}" / f"pcm{device}{direction}" / "sub0" / "status"
    )
    active: AudioStream | None = None
    known = True
    if status.exists():
        text = _optional(status)
        if text is None:
            known = False
        elif "state: RUNNING" in text or "state: DRAINING" in text:
            active = AudioStream(
                id=f"{device_id}-stream",
                node=label or device_id,
                role=role,
                state="running",
                device_id=device_id,
            )
    return (
        AudioDevice(
            id=device_id,
            name=label or device_id,
            kind=_kind(card_name, label, role, None),
            role=role,
        ),
        active,
        known,
    )


def _kind(card_name: str, label: str, role: DeviceRole, bus: str | None) -> DeviceKind:
    blob = f"{card_name} {label} {bus or ''}".lower()
    if bus == "bluetooth" or "bluez" in blob or "bluetooth" in blob:
        return "bluetooth"
    if role == "output" and ("headphone" in blob or "headset" in blob):
        return "headphones"
    if role == "input":
        return "microphone"
    if "hdmi" in blob or "displayport" in blob:
        return "other"
    return "speaker"


def _list_dir(path: Path) -> list[Path] | None:
    if not path.is_dir():
        return []
    try:
        return sorted(path.iterdir(), key=lambda item: item.name)
    except OSError:
        return None


def _optional(path: Path) -> str | None:
    try:
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    return text or None
