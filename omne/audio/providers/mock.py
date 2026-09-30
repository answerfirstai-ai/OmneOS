"""In-memory audio session for tests and non-Linux hosts.

The mock starts with no devices. It does not invent a volume, a stream, or a sample.
"""

from __future__ import annotations

from omne.audio.model import (
    ApplyOutcome,
    AudioDevice,
    AudioEvent,
    AudioRequest,
    AudioState,
    AudioStream,
    derive_microphone,
)


class MockAudioProvider:
    """A session whose mixer changes stay inside the record."""

    def __init__(self) -> None:
        self._devices: list[AudioDevice] = []
        self._streams: list[AudioStream] = []
        self._default_input: str | None = None
        self._default_output: str | None = None

    def inspect(self) -> AudioState:
        return self._state()

    def set_devices(self, devices: list[AudioDevice]) -> None:
        self._devices = list(devices)

    def set_streams(self, streams: list[AudioStream]) -> None:
        self._streams = list(streams)

    def apply(self, request: AudioRequest) -> ApplyOutcome:
        if request.action == "set_volume":
            return self._volume(request)
        if request.action == "set_mute":
            return self._mute(request)
        return self._default(request)

    def _volume(self, request: AudioRequest) -> ApplyOutcome:
        device = self._require(request.device)
        if isinstance(device, ApplyOutcome):
            return device
        if request.volume is None:
            return self._refuse("request is incomplete")
        if device.volume == request.volume:
            return self._ok("volume", [])
        before = self._state().microphone
        self._replace(device.model_copy(update={"volume": request.volume}))
        events = [
            AudioEvent(
                type="audio.volume.changed",
                payload={"id": device.id, "volume": request.volume},
            )
        ]
        events.extend(self._microphone_event(before))
        return self._ok("volume", events)

    def _mute(self, request: AudioRequest) -> ApplyOutcome:
        device = self._require(request.device)
        if isinstance(device, ApplyOutcome):
            return device
        if request.muted is None:
            return self._refuse("request is incomplete")
        if device.muted is request.muted:
            return self._ok("mute", [])
        before = self._state().microphone
        self._replace(device.model_copy(update={"muted": request.muted}))
        events = [
            AudioEvent(
                type="audio.mute.changed",
                payload={"id": device.id, "muted": request.muted},
            )
        ]
        events.extend(self._microphone_event(before))
        return self._ok("mute", events)

    def _default(self, request: AudioRequest) -> ApplyOutcome:
        device = self._require(request.device)
        if isinstance(device, ApplyOutcome):
            return device
        if request.role is None:
            return self._refuse("request is incomplete")
        if device.role != request.role:
            return self._refuse("device role does not match")
        current = self._default_input if request.role == "input" else self._default_output
        if current == device.id:
            return self._ok("default", [])
        if request.role == "input":
            self._default_input = device.id
        else:
            self._default_output = device.id
        state = self._state()
        return self._ok(
            "default",
            [
                AudioEvent(
                    type="audio.default.changed",
                    payload={"input": state.default_input, "output": state.default_output},
                )
            ],
        )

    def _require(self, device_id: str | None) -> AudioDevice | ApplyOutcome:
        if not device_id:
            return self._refuse("request is incomplete")
        for device in self._devices:
            if device.id == device_id:
                return device
        return self._refuse("device is unknown")

    def _replace(self, device: AudioDevice) -> None:
        self._devices = [device if item.id == device.id else item for item in self._devices]

    def _microphone_event(self, before: str) -> list[AudioEvent]:
        state = self._state()
        if state.microphone == before:
            return []
        return [AudioEvent(type="audio.microphone.changed", payload={"state": state.microphone})]

    def _state(self) -> AudioState:
        devices = sorted(self._devices, key=lambda item: item.id)
        streams = sorted(self._streams, key=lambda item: item.id)
        return AudioState(
            provider="mock",
            observed=True,
            stack="unknown",
            session_manager="unknown",
            devices=devices,
            default_input=self._default_input,
            default_output=self._default_output,
            defaults_known=True,
            streams=streams,
            streams_known=True,
            microphone=derive_microphone(
                devices,
                streams,
                devices_known=True,
                streams_known=True,
            ),
        )

    def _ok(self, reason: str, events: list[AudioEvent]) -> ApplyOutcome:
        return ApplyOutcome(applied=True, reason=reason, state=self._state(), events=events)

    def _refuse(self, reason: str) -> ApplyOutcome:
        return ApplyOutcome(applied=False, reason=reason, state=self._state(), events=[])
