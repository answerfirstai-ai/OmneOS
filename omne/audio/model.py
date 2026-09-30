"""Audio records read from the Linux audio stack.

OMNE does not capture or transmit microphone audio. Speech recognition is not
implemented. A missing measurement stays null.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ProviderName = Literal["mock", "linux"]
StackName = Literal["pipewire", "alsa", "unknown"]
SessionManager = Literal["wireplumber", "unknown"]
DeviceKind = Literal["microphone", "speaker", "headphones", "bluetooth", "other"]
DeviceRole = Literal["input", "output"]
MicrophoneState = Literal["unknown", "absent", "present", "muted", "active"]
AudioAction = Literal["set_default", "set_volume", "set_mute"]
AudioEventType = Literal[
    "audio.device.added",
    "audio.device.removed",
    "audio.device.changed",
    "audio.default.changed",
    "audio.volume.changed",
    "audio.mute.changed",
    "audio.stream.started",
    "audio.stream.stopped",
    "audio.microphone.changed",
]


class AudioDevice(BaseModel):
    """One sink or source published by the audio stack."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: DeviceKind
    role: DeviceRole
    volume: int | None = Field(default=None, ge=0, le=100)
    muted: bool | None = None
    bus: str | None = None


class AudioStream(BaseModel):
    """One client stream. The record does not contain samples."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    node: str = Field(min_length=1)
    role: DeviceRole
    state: str = Field(min_length=1)
    device_id: str | None = None
    application: str | None = None


class AudioState(BaseModel):
    """One read of the Linux audio stack."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: ProviderName
    observed: bool
    stack: StackName
    session_manager: SessionManager
    stack_commanded: bool = False
    devices: list[AudioDevice] = Field(default_factory=list)
    default_input: str | None = None
    default_output: str | None = None
    defaults_known: bool
    streams: list[AudioStream] = Field(default_factory=list)
    streams_known: bool
    microphone: MicrophoneState
    capture_open: bool = False
    recognition: Literal["not_implemented"] = "not_implemented"
    transmitting: bool = False
    gaps: list[str] = Field(default_factory=list)

    @field_validator("stack_commanded")
    @classmethod
    def _not_commanded(cls, value: bool) -> bool:
        if value:
            raise ValueError("stack_commanded must be false")
        return value

    @field_validator("capture_open")
    @classmethod
    def _capture_stays_closed(cls, value: bool) -> bool:
        if value:
            raise ValueError("capture_open must be false")
        return value

    @field_validator("transmitting")
    @classmethod
    def _not_transmitting(cls, value: bool) -> bool:
        if value:
            raise ValueError("transmitting must be false")
        return value


class AudioRequest(BaseModel):
    """A requested mixer change. The request has no audio samples."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: AudioAction
    agent_id: str = Field(min_length=1)
    device: str | None = None
    role: DeviceRole | None = None
    volume: int | None = Field(default=None, ge=0, le=100)
    muted: bool | None = None

    def public_arguments(self) -> dict[str, object]:
        """Arguments safe to hand to the permission policy and the audit log."""

        payload = self.model_dump()
        return {key: value for key, value in payload.items() if value is not None}


class AudioEvent(BaseModel):
    """One audio event. Payloads do not carry samples."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: AudioEventType
    payload: dict[str, Any] = Field(default_factory=dict)


class ApplyOutcome(BaseModel):
    """Whether a request changed the recorded audio session."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    applied: bool
    reason: str
    state: AudioState
    events: list[AudioEvent] = Field(default_factory=list)


def derive_microphone(
    devices: list[AudioDevice],
    streams: list[AudioStream],
    *,
    devices_known: bool,
    streams_known: bool,
) -> MicrophoneState:
    """Classify the microphone without opening it."""

    if not devices_known or not streams_known:
        return "unknown"
    inputs = [device for device in devices if device.role == "input"]
    if not inputs:
        return "absent"
    if any(stream.role == "input" and stream.state == "running" for stream in streams):
        return "active"
    if any(device.muted is True for device in inputs):
        return "muted"
    return "present"
