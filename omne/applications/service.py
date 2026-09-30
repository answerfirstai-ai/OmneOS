"""Look up an application, check permission, then record the action.

The open path is intent, lookup, permission, launch, process, window, report.
Launch never receives a shell command.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal

from omne.applications.model import (
    Application,
    ApplicationCatalog,
    ApplicationReport,
    ApplicationRequest,
    ApplyOutcome,
)
from omne.applications.provider import ApplicationProvider

Authorize = Callable[[str, dict[str, object], Mapping[str, Sequence[str]], str], tuple[str, str]]
EventSink = Callable[[str, dict[str, Any]], None]

_ACTIONS = {
    "launch": "application.launch",
    "focus": "application.focus",
    "close": "application.close",
}
_UNSAFE = set("|&;<>`$()")


class ApplicationService:
    """Search and inspect freely. Change an application only after permission allows it."""

    def __init__(
        self,
        provider: ApplicationProvider,
        *,
        sink: EventSink | None = None,
        authorize: Authorize | None = None,
    ) -> None:
        self._provider = provider
        self._sink = sink
        self._authorize = authorize or _deny_all
        self._seen: set[str] | None = None

    def catalog(self) -> ApplicationCatalog:
        current = self._provider.catalog()
        previous = self._seen
        self._seen = {item.id for item in current.applications}
        if previous is not None and current.observed and self._sink is not None:
            for app_id in sorted(self._seen - previous):
                self._sink("application.discovered", {"id": app_id})
        return current

    def search(self, query: str) -> list[Application]:
        needle = " ".join(query.split()).casefold()
        found = [
            item
            for item in self.catalog().applications
            if item.state != "hidden" and (not needle or _matches(item, needle))
        ]
        return found

    def inspect(self, application_id: str) -> Application | None:
        for item in self.catalog().applications:
            if item.id == application_id:
                return item
        return None

    def open_named(
        self,
        query: str,
        grants: Mapping[str, Sequence[str]],
        environment: str,
        *,
        agent_id: str = "local",
        permitted: bool = False,
    ) -> ApplicationReport:
        """Run the open pipeline for a name such as ``Firefox``."""

        name = " ".join(query.split())
        if not name or any(character in name for character in _UNSAFE):
            return _report(
                name, None, "absent", False, False, False, "application name is not a command"
            )
        app, problem = self._resolve(name)
        if app is None:
            reason = (
                "more than one application matches"
                if problem == "ambiguous"
                else "application was not found"
            )
            return _report(name, None, "absent", False, False, False, reason)
        if permitted:
            decision = "ALLOW"
        else:
            decision, _reason = self._authorize(
                "application.launch",
                {"application_id": app.id},
                grants,
                environment,
            )
        if decision != "ALLOW":
            return _report(
                name,
                app.id,
                _permission(decision),
                False,
                False,
                False,
                "launch permission was not granted",
                app,
            )
        outcome = self.apply(
            ApplicationRequest(action="launch", application_id=app.id, agent_id=agent_id),
            grants,
            environment,
            permitted=True,
        )
        observed = self.inspect(app.id) or app
        return _report(
            name,
            app.id,
            "ALLOW",
            outcome.applied,
            bool(observed.processes),
            bool(observed.windows),
            outcome.reason,
            observed,
        )

    def apply(
        self,
        request: ApplicationRequest,
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
                return ApplyOutcome(applied=False, reason=reason, catalog=self.catalog())
        outcome = self._provider.apply(request)
        self._seen = {item.id for item in outcome.catalog.applications}
        if outcome.applied and self._sink is not None:
            for event in outcome.events:
                self._sink(event.type, dict(event.payload))
        return outcome

    def _resolve(self, query: str) -> tuple[Application | None, str]:
        visible = [
            item
            for item in self.catalog().applications
            if item.state != "hidden" and item.launchable
        ]
        needle = query.casefold()
        exact = [
            item
            for item in visible
            if item.name.casefold() == needle or item.id.casefold() == needle
        ]
        if len(exact) == 1:
            return exact[0], ""
        if len(exact) > 1:
            return None, "ambiguous"
        partial = [
            item
            for item in visible
            if needle in item.name.casefold() or needle in item.id.casefold()
        ]
        if len(partial) == 1:
            return partial[0], ""
        if not partial:
            return None, "missing"
        return None, "ambiguous"


def _matches(app: Application, needle: str) -> bool:
    haystack = " ".join([app.name, app.id, *app.categories]).casefold()
    return needle in haystack


def _permission(decision: str) -> Literal["ALLOW", "DENY", "CONFIRM"]:
    if decision == "ALLOW":
        return "ALLOW"
    if decision == "CONFIRM":
        return "CONFIRM"
    return "DENY"


def _report(
    query: str,
    application_id: str | None,
    permission: Literal["ALLOW", "DENY", "CONFIRM", "absent"],
    launched: bool,
    process_observed: bool,
    window_observed: bool,
    report: str,
    application: Application | None = None,
) -> ApplicationReport:
    return ApplicationReport(
        query=query,
        application_id=application_id,
        permission=permission,
        launched=launched,
        process_observed=process_observed,
        window_observed=window_observed,
        report=report,
        application=application,
    )


def _deny_all(
    _tool_id: str,
    _arguments: dict[str, object],
    _grants: Mapping[str, Sequence[str]],
    _environment: str,
) -> tuple[str, str]:
    return "DENY", "application permission was not evaluated"
