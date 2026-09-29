"""Apply window requests after a grant check, then emit events."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from omne.windowing.model import ApplyOutcome, WindowingState, WindowRequest
from omne.windowing.permission import (
    GRANT_REQUIRED,
    WindowAccess,
    decide,
)
from omne.windowing.provider import WindowProvider
from omne.windowing.session import INCOMPLETE, NOT_OBSERVED

EventSink = Callable[[str, dict[str, Any], str | None], None]


class WindowingService:
    """The only path that turns a request into a recorded window change."""

    def __init__(self, provider: WindowProvider, sink: EventSink | None = None) -> None:
        self._provider = provider
        self._sink = sink

    def state(self) -> WindowingState:
        return self._provider.state()

    def apply(
        self,
        request: WindowRequest,
        grants: Mapping[str, Sequence[str]],
        environment: str,
    ) -> ApplyOutcome:
        current = self._provider.state()
        if not current.known:
            return ApplyOutcome(
                applied=False,
                reason=NOT_OBSERVED,
                state=current,
                events=[],
            )
        blocked = _blocked(current, request, grants, environment)
        if blocked is not None:
            return ApplyOutcome(applied=False, reason=blocked, state=current, events=[])
        outcome = self._provider.apply(request)
        if outcome.applied and self._sink is not None:
            for event in outcome.events:
                self._sink(event.type, dict(event.payload), request.agent_id)
        return outcome


def _blocked(
    current: WindowingState,
    request: WindowRequest,
    grants: Mapping[str, Sequence[str]],
    environment: str,
) -> str | None:
    if request.action == "launch":
        decision = decide(
            kind="launch",
            agent_id=request.agent_id,
            owner=None,
            grants=grants,
            environment=environment,
        )
        if decision.access is not WindowAccess.ALLOW:
            return decision.reason
        return None
    if request.action == "workspace" and request.window_id is None:
        decision = decide(
            kind="session",
            agent_id=request.agent_id,
            owner=None,
            grants=grants,
            environment=environment,
        )
        if decision.access is not WindowAccess.ALLOW:
            return decision.reason
        return None
    if not request.window_id:
        decision = decide(
            kind="window",
            agent_id=request.agent_id,
            owner=None,
            grants=grants,
            environment=environment,
        )
        if decision.access is not WindowAccess.ALLOW:
            return decision.reason
        return INCOMPLETE
    window = next((item for item in current.windows if item.id == request.window_id), None)
    if window is None:
        decision = decide(
            kind="window",
            agent_id=request.agent_id,
            owner=None,
            grants=grants,
            environment=environment,
        )
        if decision.reason == GRANT_REQUIRED:
            return GRANT_REQUIRED
        if decision.access is WindowAccess.ALLOW:
            return "window is unknown"
        granted = grants.get("window", ())
        if "own" in granted and "manage" not in granted:
            return "window is unknown"
        return decision.reason
    decision = decide(
        kind="window",
        agent_id=request.agent_id,
        owner=window.owner,
        grants=grants,
        environment=environment,
    )
    if decision.access is not WindowAccess.ALLOW:
        return decision.reason
    return None
