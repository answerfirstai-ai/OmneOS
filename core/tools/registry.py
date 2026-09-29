"""Tool registration."""

from __future__ import annotations

from core.tools.base import Tool


class ToolRegistry:
    """Map tool identifiers to implementations."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.id in self._tools:
            raise ValueError(f"duplicate tool identifier: {tool.id}")
        self._tools[tool.id] = tool

    def get(self, tool_id: str) -> Tool:
        try:
            return self._tools[tool_id]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {tool_id}") from exc

    def ids(self) -> set[str]:
        return set(self._tools)
