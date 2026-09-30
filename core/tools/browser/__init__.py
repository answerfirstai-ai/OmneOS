"""Browser tools.

``browser.open`` and ``browser.search`` keep their existing interface.
Navigation runs only when ``browser_command`` is configured. Otherwise the
tool reports that browser tooling is unavailable and does not contact the URL.

Session actions live beside that interface. They go through the browser
service and do not start a shell.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from core.tools.base import ToolContext, ToolError
from core.tools.browser.actions import _BrowserAction, session_tools
from core.tools.command import SubprocessCommands
from omne.browser.select import browser_service
from omne.browser.service import BrowserService


class _BrowserTool:
    def __init__(self, tool_id: str, command: str, commands: SubprocessCommands) -> None:
        self.id = tool_id
        self._command = command
        self._commands = commands

    def _unavailable(self) -> dict[str, Any]:
        return {
            "available": False,
            "reason": "browser tooling is not configured",
        }

    def _run(self, argument: str, context: ToolContext) -> dict[str, Any]:
        if not self._command:
            return self._unavailable()
        output = self._commands.run(
            [self._command, argument],
            cwd=context.workspace_root,
            timeout=float(context.timeout_seconds),
        )
        return {
            "available": True,
            "exit_code": output.exit_code,
            "stdout": output.stdout,
            "stderr": output.stderr,
        }


class BrowserOpenTool(_BrowserTool):
    def __init__(self, command: str, commands: SubprocessCommands) -> None:
        super().__init__("browser.open", command, commands)

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        url = arguments.get("url")
        if not isinstance(url, str) or not url:
            raise ToolError("url must be a non-empty string", code="invalid_input")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ToolError("url must be an absolute http or https URL", code="invalid_input")
        return {"url": url}

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        result = self._run(arguments["url"], context)
        result["url"] = arguments["url"]
        return result


class BrowserSearchTool(_BrowserTool):
    def __init__(self, command: str, commands: SubprocessCommands) -> None:
        super().__init__("browser.search", command, commands)

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ToolError("query must be a non-empty string", code="invalid_input")
        return {"query": query.strip()}

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        result = self._run(arguments["query"], context)
        result["query"] = arguments["query"]
        return result


def browser_tools(
    command: str = "",
    commands: SubprocessCommands | None = None,
    *,
    service: BrowserService | None = None,
) -> list[_BrowserTool | _BrowserAction]:
    active = commands or SubprocessCommands()
    bound = service if service is not None else browser_service("testing")
    return [
        BrowserOpenTool(command, active),
        BrowserSearchTool(command, active),
        *session_tools(bound),
    ]
