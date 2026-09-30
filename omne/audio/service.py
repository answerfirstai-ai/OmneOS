"""Permission-gate mixer changes and publish audio events."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from omne.audio.model import ApplyOutcome, AudioEvent, AudioRequest, AudioState
from omne.audio.provider import AudioProvider

Authorize = Callable[[str, dict[str, object], Mapping[str, Sequence[str]], str], tuple[str, str]]
EventSink = Callable[[str, dict[str, Any]], None]

_ACTIONS = {
    "set_default": "audio.set_default",
    "set_volume": "audio.set_volume",
    "set_mute": "audio.set_mute",
}


class AudioService:
    """Inspect freely. Apply a mixer change only after the permission system allows it."""

    def __init__(
        self,
        provider: AudioProvider,
        sink: EventSink | None = None,
        authorize: Authorize | None = None,
    ) -> None:
        self._provider = provider
        self._sink = sink
        self._authorize = authorize or _deny_all
        self._previous: AudioState | None = None

    def inspect(self) -> AudioState:
        current = self._provider.inspect()
        previous = self._previous
        self._previous = current
        if previous is not None and self._sink is not None:
            for event in _diff(previous, current):
                self._sink(event.type, dict(event.payload))
        return current

    def apply(
        self,
        request: AudioRequest,
        grants: Mapping[str, Sequence[str]],
        environment: str,
        *,
        permitted: bool = False,
    ) -> ApplyOutcome:
        if not permitted:
            decision, reason = self._authorize(
                _ACTIONS[request.action],
                request.public_arguments(),
                grants,
                environment,
            )
            if decision != "ALLOW":
                return ApplyOutcome(
                    applied=False,
                    reason=reason,
                    state=self._provider.inspect(),
                    events=[],
                )
        outcome = self._provider.apply(request)
        if outcome.applied:
            self._previous = outcome.state
            if self._sink is not None:
                for event in outcome.events:
                    self._sink(event.type, dict(event.payload))
        return outcome


def _deny_all(
    _tool_id: str,
    _arguments: dict[str, object],
    _grants: Mapping[str, Sequence[str]],
    _environment: str,
) -> tuple[str, str]:
    return "DENY", "audio permission was not evaluated"


def _diff(before: AudioState, after: AudioState) -> list[AudioEvent]:
    events: list[AudioEvent] = []
    previous = {device.id: device for device in before.devices}
    current = {device.id: device for device in after.devices}
    for device_id in sorted(set(current) - set(previous)):
        device = current[device_id]
        events.append(
            AudioEvent(
                type="audio.device.added",
                payload={"id": device.id, "kind": device.kind, "role": device.role},
            )
        )
    for device_id in sorted(set(previous) - set(current)):
        device = previous[device_id]
        events.append(
            AudioEvent(
                type="audio.device.removed",
                payload={"id": device.id, "kind": device.kind, "role": device.role},
            )
        )
    for device_id in sorted(set(previous) & set(current)):
        left = previous[device_id]
        right = current[device_id]
        if left.volume != right.volume:
            events.append(
                AudioEvent(
                    type="audio.volume.changed",
                    payload={"id": device_id, "volume": right.volume},
                )
            )
        if left.muted != right.muted:
            events.append(
                AudioEvent(
                    type="audio.mute.changed",
                    payload={"id": device_id, "muted": right.muted},
                )
            )
        fields = _changed_fields(left.model_dump(mode="json"), right.model_dump(mode="json"))
        fields = [field for field in fields if field not in {"volume", "muted"}]
        if fields:
            events.append(
                AudioEvent(
                    type="audio.device.changed",
                    payload={"id": device_id, "fields": fields},
                )
            )
    if before.default_input != after.default_input or before.default_output != after.default_output:
        events.append(
            AudioEvent(
                type="audio.default.changed",
                payload={"input": after.default_input, "output": after.default_output},
            )
        )
    events.extend(_stream_events(before, after))
    if before.microphone != after.microphone:
        events.append(
            AudioEvent(type="audio.microphone.changed", payload={"state": after.microphone})
        )
    return events


def _stream_events(before: AudioState, after: AudioState) -> list[AudioEvent]:
    previous = {stream.id: stream for stream in before.streams}
    current = {stream.id: stream for stream in after.streams}
    events: list[AudioEvent] = []
    for stream_id in sorted(set(current)):
        stream = current[stream_id]
        was = previous.get(stream_id)
        started = stream.state == "running" and (was is None or was.state != "running")
        if started:
            events.append(
                AudioEvent(
                    type="audio.stream.started",
                    payload={"id": stream.id, "node": stream.node, "role": stream.role},
                )
            )
    for stream_id in sorted(set(previous)):
        stream = previous[stream_id]
        now = current.get(stream_id)
        stopped = stream.state == "running" and (now is None or now.state != "running")
        if stopped:
            events.append(
                AudioEvent(
                    type="audio.stream.stopped",
                    payload={"id": stream.id, "node": stream.node, "role": stream.role},
                )
            )
    return events


def _changed_fields(before: dict[str, object], after: dict[str, object]) -> list[str]:
    return sorted(key for key in before if before.get(key) != after.get(key))
