"""Check permission, then record a browser action.

Launch, navigation, inspection, research, screenshots, user control, and
automation are separate permissions. None of them accept a shell command.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from omne.browser.model import BrowserOutcome, BrowserRequest, BrowserState
from omne.browser.provider import BrowserProvider

Authorize = Callable[[str, dict[str, object], Mapping[str, Sequence[str]], str], tuple[str, str]]
EventSink = Callable[[str, dict[str, Any]], None]

_ACTIONS = {
    "launch": "browser.launch",
    "navigate": "browser.navigate",
    "inspect": "browser.inspect",
    "research": "browser.research",
    "screenshot": "browser.screenshot",
    "interact": "browser.interact",
    "automate": "browser.automate",
}


class BrowserService:
    """Read availability freely. Change a session only after permission allows it."""

    def __init__(
        self,
        provider: BrowserProvider,
        *,
        sink: EventSink | None = None,
        authorize: Authorize | None = None,
    ) -> None:
        self._provider = provider
        self._sink = sink
        self._authorize = authorize or _deny_all

    def status(self) -> BrowserState:
        return self._provider.status()

    def apply(
        self,
        request: BrowserRequest,
        grants: Mapping[str, Sequence[str]],
        environment: str,
        *,
        permitted: bool = False,
    ) -> BrowserOutcome:
        if not permitted:
            decision, reason = self._authorize(
                _ACTIONS[request.action],
                request.public_arguments(),
                grants,
                environment,
            )
            if decision != "ALLOW":
                return BrowserOutcome(applied=False, reason=reason, state=self.status())
        outcome = self._provider.apply(request)
        if outcome.applied and self._sink is not None:
            for event in outcome.events:
                self._sink(event.type, dict(event.payload))
        return outcome


def _deny_all(
    _tool_id: str,
    _arguments: dict[str, object],
    _grants: Mapping[str, Sequence[str]],
    _environment: str,
) -> tuple[str, str]:
    return "DENY", "browser permission was not evaluated"
