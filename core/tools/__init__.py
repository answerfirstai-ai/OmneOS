"""Permission-gated tools."""

from typing import cast

from core.tools.base import Tool, ToolResult
from core.tools.browser import browser_tools
from core.tools.filesystem import filesystem_tools
from core.tools.gateway import ToolGateway
from core.tools.git import git_tools
from core.tools.processes import process_tools
from core.tools.registry import ToolRegistry
from core.tools.system import system_tools

__all__ = [
    "ToolGateway",
    "ToolRegistry",
    "ToolResult",
    "browser_tools",
    "build_registry",
    "filesystem_tools",
    "git_tools",
    "process_tools",
    "system_tools",
]


def build_registry(*, browser_command: str = "") -> ToolRegistry:
    """Register the built-in tools."""

    registry = ToolRegistry()
    for tool in (
        *filesystem_tools(),
        *process_tools(),
        *system_tools(),
        *git_tools(),
        *browser_tools(browser_command),
    ):
        registry.register(cast(Tool, tool))
    from core.tools.terminal import TerminalTool

    registry.register(TerminalTool())
    return registry
