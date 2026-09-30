"""Application tools.

The arguments name an installed application. They are not a shell command.
"""

from __future__ import annotations

from typing import Any, Literal

from core.tools.base import ToolContext, ToolError
from omne.applications.model import ApplicationRequest
from omne.applications.service import ApplicationService

_UNSAFE = set("|&;<>`$()")
_REJECTED = {"argv", "command", "shell", "exec", "cmd"}


class _ApplicationTool:
    def __init__(self, tool_id: str, service: ApplicationService) -> None:
        self.id = tool_id
        self._service = service

    def _identity(self, arguments: dict[str, Any]) -> dict[str, str]:
        if any(key in arguments for key in _REJECTED):
            raise ToolError(
                "application launch does not accept a shell command",
                code="invalid_input",
            )
        name = arguments.get("name")
        app_id = arguments.get("id")
        if (name is None) == (app_id is None):
            raise ToolError("name or id is required", code="invalid_input")
        value = name if isinstance(name, str) else app_id
        if not isinstance(value, str) or not value.strip():
            raise ToolError("name or id must be a non-empty string", code="invalid_input")
        if any(character in value for character in _UNSAFE):
            raise ToolError(
                "application launch does not accept a shell command",
                code="invalid_input",
            )
        if isinstance(name, str):
            return {"name": " ".join(name.split())}
        return {"id": value.strip()}

    def _request(
        self,
        action: Literal["launch", "focus", "close"],
        app_id: str,
        context: ToolContext,
    ) -> ApplicationRequest:
        return ApplicationRequest(
            action=action,
            application_id=app_id,
            agent_id=context.agent_id or "local",
        )


class LaunchTool(_ApplicationTool):
    def __init__(self, service: ApplicationService) -> None:
        super().__init__("application.launch", service)

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._identity(arguments)

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        if "name" in arguments:
            report = self._service.open_named(
                arguments["name"],
                {},
                "testing",
                agent_id=context.agent_id or "local",
                permitted=True,
            )
            return report.model_dump(mode="json")
        request = self._request("launch", arguments["id"], context)
        outcome = self._service.apply(request, {}, "testing", permitted=True)
        return outcome.model_dump(mode="json")


class FocusTool(_ApplicationTool):
    def __init__(self, service: ApplicationService) -> None:
        super().__init__("application.focus", service)

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        identity = self._identity(arguments)
        if "id" not in identity:
            raise ToolError("id is required", code="invalid_input")
        return identity

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        outcome = self._service.apply(
            self._request("focus", arguments["id"], context),
            {},
            "testing",
            permitted=True,
        )
        return outcome.model_dump(mode="json")


class CloseTool(FocusTool):
    def __init__(self, service: ApplicationService) -> None:
        _ApplicationTool.__init__(self, "application.close", service)

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        outcome = self._service.apply(
            self._request("close", arguments["id"], context),
            {},
            "testing",
            permitted=True,
        )
        return outcome.model_dump(mode="json")


def application_tools(service: ApplicationService) -> list[_ApplicationTool]:
    return [LaunchTool(service), FocusTool(service), CloseTool(service)]
