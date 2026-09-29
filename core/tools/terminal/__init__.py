"""Controlled command execution."""

from __future__ import annotations

import subprocess
from typing import Any

from core.permissions.policies import dangerous_command, resolve_inside_workspace
from core.tools.base import ToolContext, ToolError
from core.tools.command import SubprocessCommands


class TerminalTool:
    id = "terminal.execute"

    def __init__(self, commands: SubprocessCommands | None = None) -> None:
        self._commands = commands or SubprocessCommands()

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        reason = dangerous_command(arguments.get("argv"))
        if reason is not None and reason.startswith("command must"):
            raise ToolError(reason, code="invalid_input")
        argv = arguments.get("argv")
        if not isinstance(argv, list):
            raise ToolError("argv must be a list of strings", code="invalid_input")
        cwd = arguments.get("cwd", ".")
        if not isinstance(cwd, str) or not cwd:
            raise ToolError("cwd must be a non-empty string", code="invalid_input")
        return {"argv": [str(item) for item in argv], "cwd": cwd}

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        reason = dangerous_command(arguments["argv"])
        if reason is not None:
            raise ToolError(reason, code="denied")
        try:
            cwd = resolve_inside_workspace(context.workspace_root, arguments["cwd"])
        except ValueError as exc:
            raise ToolError(str(exc), code="path_denied") from exc
        try:
            output = self._commands.run(
                arguments["argv"],
                cwd=cwd,
                timeout=float(context.timeout_seconds),
            )
        except (TimeoutError, subprocess.TimeoutExpired) as exc:
            raise ToolError("command timed out", code="timeout") from exc
        except OSError as exc:
            raise ToolError(str(exc), code="command_failed") from exc
        return {
            "exit_code": output.exit_code,
            "stdout": output.stdout,
            "stderr": output.stderr,
        }
