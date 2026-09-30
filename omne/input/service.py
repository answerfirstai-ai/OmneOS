"""Permission-gate input actions and publish binding events.

The service accepts activate, cancel, and bind. It never accepts a keystroke.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal

from omne.input.chords import parse_shortcut
from omne.input.model import (
    ApplyOutcome,
    Attention,
    DeviceReport,
    InputEvent,
    InputRequest,
    InputState,
    PushToTalk,
)
from omne.input.provider import InputProvider

Authorize = Callable[[str, dict[str, object], Mapping[str, Sequence[str]], str], tuple[str, str]]
EventSink = Callable[[str, dict[str, Any]], None]

_ACTIONS = {
    "activate": "input.activate",
    "cancel": "input.cancel",
    "bind": "input.bind",
}
_BIND_REFUSED = "global shortcut grab is not installed"


class InputService:
    """Inspect devices freely. Change attention only after the permission system allows it."""

    def __init__(
        self,
        provider: InputProvider,
        *,
        activation: str = "",
        cancel: str = "",
        push_to_talk: str = "",
        sink: EventSink | None = None,
        authorize: Authorize | None = None,
    ) -> None:
        self._provider = provider
        self._activation = parse_shortcut(activation)
        self._cancel_chord = parse_shortcut(cancel)
        self._push_to_talk = parse_shortcut(push_to_talk)
        self._sink = sink
        self._authorize = authorize or _deny_all
        self._attention: Attention = "idle"
        self._revision = 0
        self._devices: dict[str, str] | None = None

    def inspect(self) -> InputState:
        report = self._provider.inspect()
        current = self._state(report)
        previous = self._devices
        self._devices = {device.id: device.kind for device in current.devices}
        if previous is not None and report.devices_known and self._sink is not None:
            for event in _device_events(previous, self._devices):
                self._sink(event.type, dict(event.payload))
        return current

    def apply(
        self,
        request: InputRequest,
        grants: Mapping[str, Sequence[str]],
        environment: str,
    ) -> ApplyOutcome:
        decision, reason = self._authorize(
            _ACTIONS[request.action],
            request.public_arguments(),
            grants,
            environment,
        )
        report = self._provider.inspect()
        if decision != "ALLOW":
            return ApplyOutcome(applied=False, reason=reason, state=self._state(report), events=[])
        if request.action == "bind":
            self._provider.apply(request)
            return ApplyOutcome(
                applied=False,
                reason=_BIND_REFUSED,
                state=self._state(report),
                events=[],
            )
        if request.action == "activate":
            return self._activate(report)
        return self._cancel(report)

    def _activate(self, report: DeviceReport) -> ApplyOutcome:
        if self._activation is None:
            return ApplyOutcome(
                applied=False,
                reason="activation is not configured",
                state=self._state(report),
                events=[],
            )
        self._attention = "command"
        self._revision += 1
        self._devices = {device.id: device.kind for device in report.devices}
        event = InputEvent(type="input.activated", payload={"surface": "command"})
        self._emit(event)
        return ApplyOutcome(
            applied=True, reason="command", state=self._state(report), events=[event]
        )

    def _cancel(self, report: DeviceReport) -> ApplyOutcome:
        if self._attention == "idle":
            return ApplyOutcome(applied=True, reason="idle", state=self._state(report), events=[])
        self._attention = "idle"
        self._revision += 1
        self._devices = {device.id: device.kind for device in report.devices}
        event = InputEvent(type="input.cancelled", payload={"surface": "idle"})
        self._emit(event)
        return ApplyOutcome(applied=True, reason="idle", state=self._state(report), events=[event])

    def _state(self, report: DeviceReport) -> InputState:
        talk: PushToTalk = "prepared" if self._push_to_talk is not None else "unconfigured"
        delivery: Literal["desktop", "unbound"] = (
            "desktop" if self._activation is not None else "unbound"
        )
        return InputState(
            provider=report.provider,
            observed=report.observed,
            compositor=report.compositor,
            portal=report.portal,
            delivery=delivery,
            activation=self._activation,
            cancel=self._cancel_chord,
            push_to_talk=self._push_to_talk,
            push_to_talk_state=talk,
            attention=self._attention,
            revision=self._revision,
            devices=list(report.devices),
            devices_known=report.devices_known,
            gaps=list(report.gaps),
        )

    def _emit(self, event: InputEvent) -> None:
        if self._sink is not None:
            self._sink(event.type, dict(event.payload))


def _deny_all(
    _tool_id: str,
    _arguments: dict[str, object],
    _grants: Mapping[str, Sequence[str]],
    _environment: str,
) -> tuple[str, str]:
    return "DENY", "input permission was not evaluated"


def _device_events(before: dict[str, str], after: dict[str, str]) -> list[InputEvent]:
    events: list[InputEvent] = []
    for device_id in sorted(set(after) - set(before)):
        events.append(
            InputEvent(
                type="input.device.added",
                payload={"id": device_id, "kind": after[device_id]},
            )
        )
    for device_id in sorted(set(before) - set(after)):
        events.append(
            InputEvent(
                type="input.device.removed",
                payload={"id": device_id, "kind": before[device_id]},
            )
        )
    return events
