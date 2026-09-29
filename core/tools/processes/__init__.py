"""Process inspection and controlled process start/stop."""

from __future__ import annotations

import os
import signal
from pathlib import Path
from typing import Any

from core.permissions.policies import dangerous_command, resolve_inside_workspace
from core.tools.base import ToolContext, ToolError
from core.tools.command import SubprocessCommands


class ProcessListTool:
    id = "process.list"

    def __init__(self, proc_root: Path | None = None) -> None:
        self._proc = proc_root or Path("/proc")

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        limit = arguments.get("limit", 50)
        if not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ToolError("limit must be an integer from 1 to 200", code="invalid_input")
        return {"limit": limit}

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        del context
        processes: list[dict[str, Any]] = []
        if not self._proc.is_dir():
            return {"available": False, "processes": [], "reason": "/proc is not available"}
        for entry in sorted(self._proc.iterdir(), key=lambda item: item.name):
            if not entry.name.isdigit():
                continue
            command = _command(entry)
            processes.append({"pid": int(entry.name), "command": command})
            if len(processes) >= arguments["limit"]:
                break
        return {"available": True, "processes": processes}


class ProcessStartTool:
    id = "process.start"

    def __init__(self, commands: SubprocessCommands | None = None) -> None:
        self._commands = commands or SubprocessCommands()

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        argv = arguments.get("argv")
        if (
            not isinstance(argv, list)
            or not argv
            or not all(isinstance(item, str) for item in argv)
        ):
            raise ToolError("argv must be a non-empty list of strings", code="invalid_input")
        cwd = arguments.get("cwd", ".")
        if not isinstance(cwd, str):
            raise ToolError("cwd must be a string", code="invalid_input")
        return {"argv": list(argv), "cwd": cwd}

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        reason = dangerous_command(arguments["argv"])
        if reason is not None:
            raise ToolError(reason, code="denied")
        cwd = resolve_inside_workspace(context.workspace_root, arguments["cwd"])
        pid = self._commands.start(arguments["argv"], cwd=cwd)
        return {"pid": pid}


class ProcessStopTool:
    id = "process.stop"

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        pid = arguments.get("pid")
        if not isinstance(pid, int) or pid <= 1:
            raise ToolError("pid must be an integer greater than 1", code="invalid_input")
        return {"pid": pid}

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        del context
        pid = arguments["pid"]
        if pid == os.getpid():
            raise ToolError("refusing to stop the JARVIS process", code="denied")
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError as exc:
            raise ToolError(f"process {pid} is not running", code="not_found") from exc
        except PermissionError as exc:
            raise ToolError(f"permission denied stopping process {pid}", code="denied") from exc
        return {"pid": pid, "signal": "SIGTERM"}


def _command(entry: Path) -> str:
    cmdline = entry / "cmdline"
    try:
        raw = cmdline.read_bytes().replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
    except OSError:
        return ""
    return raw


def process_tools() -> list[ProcessListTool | ProcessStartTool | ProcessStopTool]:
    return [ProcessListTool(), ProcessStartTool(), ProcessStopTool()]
