"""Session browser tools.

These tools name a session, a URL, a query, or a target. They do not accept a
shell command, a typed secret, or a script.
"""

from __future__ import annotations

from typing import Any

from core.tools.base import ToolContext, ToolError
from omne.browser.model import AutomationKind, BrowserAction, BrowserRequest
from omne.browser.service import BrowserService
from omne.browser.urls import browser_query, browser_target, browser_url

_REJECTED = {
    "argv",
    "cmd",
    "command",
    "cookie",
    "exec",
    "javascript",
    "password",
    "script",
    "shell",
    "text",
    "token",
}


class _BrowserAction:
    def __init__(self, tool_id: str, service: BrowserService) -> None:
        self.id = tool_id
        self._service = service

    def _reject(self, arguments: dict[str, Any]) -> None:
        if any(key in arguments for key in _REJECTED):
            raise ToolError(
                "browser actions do not accept a shell command or a secret",
                code="invalid_input",
            )

    def _request(
        self, action: BrowserAction, arguments: dict[str, Any], context: ToolContext
    ) -> BrowserRequest:
        return BrowserRequest(
            action=action,
            agent_id=context.agent_id or "local",
            session_id=_optional(arguments, "session_id"),
            application_id=_optional(arguments, "application_id"),
            url=_optional(arguments, "url"),
            query=_optional(arguments, "query"),
            target=_optional(arguments, "target"),
            kind=_kind(arguments.get("kind")),
        )

    def _run(self, request: BrowserRequest) -> dict[str, Any]:
        outcome = self._service.apply(request, {}, "testing", permitted=True)
        return outcome.model_dump(mode="json")


class LaunchTool(_BrowserAction):
    def __init__(self, service: BrowserService) -> None:
        super().__init__("browser.launch", service)

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._reject(arguments)
        application_id = arguments.get("application_id")
        if application_id is None:
            return {}
        if not isinstance(application_id, str) or not application_id.strip():
            raise ToolError("application_id must be a non-empty string", code="invalid_input")
        return {"application_id": application_id.strip()}

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        return self._run(self._request("launch", arguments, context))


class NavigateTool(_BrowserAction):
    def __init__(self, service: BrowserService) -> None:
        super().__init__("browser.navigate", service)

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._reject(arguments)
        session_id = _required(arguments, "session_id")
        raw = arguments.get("url")
        url = browser_url(raw) if isinstance(raw, str) else None
        if url is None or url == "about:blank":
            raise ToolError("url must be an absolute http or https URL", code="invalid_input")
        return {"session_id": session_id, "url": url}

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        return self._run(self._request("navigate", arguments, context))


class InspectTool(_BrowserAction):
    def __init__(self, service: BrowserService) -> None:
        super().__init__("browser.inspect", service)

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._reject(arguments)
        return {"session_id": _required(arguments, "session_id")}

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        return self._run(self._request("inspect", arguments, context))


class ResearchTool(_BrowserAction):
    def __init__(self, service: BrowserService) -> None:
        super().__init__("browser.research", service)

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._reject(arguments)
        raw = arguments.get("query")
        query = browser_query(raw) if isinstance(raw, str) else None
        if query is None:
            raise ToolError("query must be a non-empty string", code="invalid_input")
        return {"query": query}

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        return self._run(self._request("research", arguments, context))


class ScreenshotTool(_BrowserAction):
    def __init__(self, service: BrowserService) -> None:
        super().__init__("browser.screenshot", service)

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._reject(arguments)
        return {"session_id": _required(arguments, "session_id")}

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        return self._run(self._request("screenshot", arguments, context))


class InteractTool(_BrowserAction):
    def __init__(self, service: BrowserService) -> None:
        super().__init__("browser.interact", service)

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._reject(arguments)
        return {"session_id": _required(arguments, "session_id")}

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        return self._run(self._request("interact", arguments, context))


class AutomateTool(_BrowserAction):
    def __init__(self, service: BrowserService) -> None:
        super().__init__("browser.automate", service)

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._reject(arguments)
        session_id = _required(arguments, "session_id")
        kind = _kind(arguments.get("kind"))
        raw = arguments.get("target")
        target = browser_target(raw) if isinstance(raw, str) else None
        if kind is None:
            raise ToolError("kind must be click or wait", code="invalid_input")
        if target is None:
            raise ToolError("target is not allowed", code="invalid_input")
        return {"session_id": session_id, "kind": kind, "target": target}

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        return self._run(self._request("automate", arguments, context))


def session_tools(service: BrowserService) -> list[_BrowserAction]:
    return [
        LaunchTool(service),
        NavigateTool(service),
        InspectTool(service),
        ResearchTool(service),
        ScreenshotTool(service),
        InteractTool(service),
        AutomateTool(service),
    ]


def _required(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"{key} must be a non-empty string", code="invalid_input")
    return value.strip()


def _optional(arguments: dict[str, Any], key: str) -> str | None:
    value = arguments.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _kind(value: object) -> AutomationKind | None:
    if value == "click":
        return "click"
    if value == "wait":
        return "wait"
    return None
