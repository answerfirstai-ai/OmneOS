"""Permission-gate network changes and publish network events."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from omne.network.model import ApplyOutcome, NetworkRequest, NetworkState
from omne.network.provider import NetworkProvider

Authorize = Callable[[str, dict[str, object], Mapping[str, Sequence[str]], str], tuple[str, str]]
EventSink = Callable[[str, dict[str, Any]], None]

_ACTIONS = {
    "scan": "network.scan",
    "connect": "network.connect",
    "disconnect": "network.disconnect",
    "enable": "network.enable",
    "disable": "network.disable",
}


class NetworkService:
    """Inspect freely. Apply a change only after the permission system allows it."""

    def __init__(
        self,
        provider: NetworkProvider,
        sink: EventSink | None = None,
        authorize: Authorize | None = None,
    ) -> None:
        self._provider = provider
        self._sink = sink
        self._authorize = authorize or _deny_all
        self._previous: dict[str, object] | None = None

    def inspect(self) -> NetworkState:
        current = self._provider.inspect()
        signature = _signature(current)
        previous = self._previous
        self._previous = signature
        if previous is not None and previous != signature and self._sink is not None:
            self._sink("network.changed", {"fields": _changed_keys(previous, signature)})
        return current

    def apply(
        self,
        request: NetworkRequest,
        grants: Mapping[str, Sequence[str]],
        environment: str,
    ) -> ApplyOutcome:
        arguments = request.public_arguments()
        decision, reason = self._authorize(_ACTIONS[request.action], arguments, grants, environment)
        if decision != "ALLOW":
            return ApplyOutcome(
                applied=False,
                reason=reason,
                state=self._provider.inspect(),
                events=[],
            )
        outcome = self._provider.apply(request)
        if outcome.applied:
            self._previous = _signature(outcome.state)
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
    return "DENY", "network permission was not evaluated"


def _signature(state: NetworkState) -> dict[str, object]:
    payload = state.model_dump(mode="json")
    interfaces = payload.get("interfaces")
    if isinstance(interfaces, list):
        for item in interfaces:
            if isinstance(item, dict):
                item.pop("statistics", None)
    return payload


def _changed_keys(before: dict[str, object], after: dict[str, object]) -> list[str]:
    return sorted(key for key in before if before.get(key) != after.get(key))
