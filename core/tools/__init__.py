"""Permission-gated tools."""

from typing import cast

from core.tools.applications import application_tools
from core.tools.base import Tool, ToolResult
from core.tools.browser import browser_tools
from core.tools.filesystem import filesystem_tools
from core.tools.gateway import ToolGateway
from core.tools.git import git_tools
from core.tools.processes import process_tools
from core.tools.registry import ToolRegistry
from core.tools.system import system_tools
from omne.applications.select import application_service
from omne.applications.service import ApplicationService
from omne.browser.select import browser_service
from omne.browser.service import BrowserService
from omne.processes.select import process_service
from omne.processes.service import ProcessService

__all__ = [
    "ToolGateway",
    "ToolRegistry",
    "ToolResult",
    "application_tools",
    "browser_tools",
    "build_registry",
    "filesystem_tools",
    "git_tools",
    "process_tools",
    "system_tools",
]


def build_registry(
    *,
    browser_command: str = "",
    applications: ApplicationService | None = None,
    browser: BrowserService | None = None,
    processes: ProcessService | None = None,
) -> ToolRegistry:
    """Register the built-in tools."""

    registry = ToolRegistry()
    catalog = applications if applications is not None else application_service("testing")
    browsers = browser if browser is not None else browser_service("testing")
    table = processes if processes is not None else process_service("testing")
    for tool in (
        *filesystem_tools(),
        *process_tools(table),
        *system_tools(),
        *git_tools(),
        *browser_tools(browser_command, service=browsers),
        *application_tools(catalog),
    ):
        registry.register(cast(Tool, tool))
    from core.tools.terminal import TerminalTool

    registry.register(TerminalTool())
    return registry
