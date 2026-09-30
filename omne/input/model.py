"""Input records. OMNE stores declared shortcuts, not keystrokes.

A missing device stays absent. The host keyboard is not grabbed.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ProviderName = Literal["mock", "linux"]
CompositorName = Literal["labwc", "unknown"]
PortalName = Literal["global-shortcuts", "unknown"]
DeviceKind = Literal["keyboard", "mouse"]
Attention = Literal["idle", "command"]
PushToTalk = Literal["unconfigured", "prepared"]
InputAction = Literal["activate", "cancel", "bind"]
InputEventType = Literal[
    "input.activated",
    "input.cancelled",
    "input.device.added",
    "input.device.removed",
]
ModifierName = Literal["ctrl", "alt", "shift", "super"]
ButtonName = Literal["left", "right", "middle"]


class Chord(BaseModel):
    """One configured shortcut. It is not a captured key."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    modifiers: list[ModifierName] = Field(min_length=1)
    key: str | None = None
    button: ButtonName | None = None

    @model_validator(mode="after")
    def _one_target(self) -> Chord:
        if (self.key is None) == (self.button is None):
            raise ValueError("shortcut must include a modifier and a key")
        return self

    @property
    def label(self) -> str:
        token = self.key if self.key is not None else self.button
        return "+".join([*self.modifiers, token or ""])


class InputDevice(BaseModel):
    """A keyboard or mouse the kernel published. The record has no keycodes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: DeviceKind


class InputState(BaseModel):
    """One read of configured shortcuts and published input devices."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: ProviderName
    observed: bool
    compositor: CompositorName
    portal: PortalName
    delivery: Literal["desktop", "unbound"]
    host_grab: bool = False
    key_stream: bool = False
    pointer_stream: bool = False
    listening: bool = False
    activation: Chord | None = None
    cancel: Chord | None = None
    push_to_talk: Chord | None = None
    push_to_talk_state: PushToTalk
    attention: Attention
    revision: int = Field(ge=0)
    devices: list[InputDevice] = Field(default_factory=list)
    devices_known: bool
    gaps: list[str] = Field(default_factory=list)

    @field_validator("host_grab", "key_stream", "pointer_stream", "listening")
    @classmethod
    def _stay_closed(cls, value: bool) -> bool:
        if value:
            raise ValueError("input capture must stay closed")
        return value


class InputRequest(BaseModel):
    """A named binding action. The request has no keystroke."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: InputAction
    agent_id: str = Field(min_length=1)

    def public_arguments(self) -> dict[str, object]:
        """Arguments safe to hand to the permission policy and the audit log."""

        return self.model_dump()


class InputEvent(BaseModel):
    """One input event. Payloads name a binding, not a key."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: InputEventType
    payload: dict[str, Any] = Field(default_factory=dict)


class ApplyOutcome(BaseModel):
    """Whether a request changed the recorded input session."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    applied: bool
    reason: str
    state: InputState
    events: list[InputEvent] = Field(default_factory=list)


class DeviceReport(BaseModel):
    """Hardware and compositor facts. Shortcuts are supplied by configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: ProviderName
    observed: bool
    compositor: CompositorName
    portal: PortalName
    devices: list[InputDevice] = Field(default_factory=list)
    devices_known: bool
    gaps: list[str] = Field(default_factory=list)
