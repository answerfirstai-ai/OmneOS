"""Read-only system telemetry tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.compute.monitor import SystemMonitor
from core.tools.base import ToolContext, ToolError


class _SystemTool:
    def __init__(self, tool_id: str, monitor: SystemMonitor) -> None:
        self.id = tool_id
        self._monitor = monitor

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if arguments:
            raise ToolError("system tools do not accept arguments", code="invalid_input")
        return {}


class CpuTool(_SystemTool):
    def __init__(self, monitor: SystemMonitor) -> None:
        super().__init__("system.cpu", monitor)

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        del arguments, context
        return self._monitor.cpu().model_dump()


class MemoryTool(_SystemTool):
    def __init__(self, monitor: SystemMonitor) -> None:
        super().__init__("system.memory", monitor)

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        del arguments, context
        return self._monitor.memory().model_dump()


class GpuTool(_SystemTool):
    def __init__(self, monitor: SystemMonitor) -> None:
        super().__init__("system.gpu", monitor)

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        del arguments, context
        return self._monitor.gpu().model_dump()


class DiskTool(_SystemTool):
    def __init__(self, monitor: SystemMonitor) -> None:
        super().__init__("system.disk", monitor)

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        del arguments
        return self._monitor.disk(context.workspace_root).model_dump()


class NetworkTool(_SystemTool):
    def __init__(self, monitor: SystemMonitor) -> None:
        super().__init__("system.network", monitor)

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        del arguments, context
        return self._monitor.network().model_dump()


def system_tools(monitor: SystemMonitor | None = None) -> list[_SystemTool]:
    active = monitor or SystemMonitor()
    return [
        CpuTool(active),
        MemoryTool(active),
        GpuTool(active),
        DiskTool(active),
        NetworkTool(active),
    ]


def system_disk_path(path: Path) -> Path:
    return path
