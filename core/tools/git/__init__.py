"""Git inspection and controlled commit."""

from __future__ import annotations

from typing import Any

from core.permissions.policies import resolve_inside_workspace
from core.tools.base import ToolContext, ToolError
from core.tools.command import SubprocessCommands


class _GitTool:
    def __init__(self, tool_id: str, commands: SubprocessCommands) -> None:
        self.id = tool_id
        self._commands = commands

    def _run(self, argv: list[str], context: ToolContext) -> dict[str, Any]:
        output = self._commands.run(
            argv, cwd=context.workspace_root, timeout=float(context.timeout_seconds)
        )
        if output.exit_code != 0:
            raise ToolError(output.stderr.strip() or "git command failed", code="git_failed")
        return {"stdout": output.stdout, "stderr": output.stderr, "exit_code": output.exit_code}


class GitStatusTool(_GitTool):
    def __init__(self, commands: SubprocessCommands) -> None:
        super().__init__("git.status", commands)

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if arguments:
            raise ToolError("git.status does not accept arguments", code="invalid_input")
        return {}

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        del arguments
        return self._run(["git", "status", "--porcelain=v1"], context)


class GitDiffTool(_GitTool):
    def __init__(self, commands: SubprocessCommands) -> None:
        super().__init__("git.diff", commands)

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if arguments:
            raise ToolError("git.diff does not accept arguments", code="invalid_input")
        return {}

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        del arguments
        return self._run(["git", "diff"], context)


class GitBranchTool(_GitTool):
    def __init__(self, commands: SubprocessCommands) -> None:
        super().__init__("git.branch", commands)

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if arguments:
            raise ToolError("git.branch does not accept arguments", code="invalid_input")
        return {}

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        del arguments
        return self._run(["git", "branch", "--show-current"], context)


class GitCommitTool(_GitTool):
    def __init__(self, commands: SubprocessCommands) -> None:
        super().__init__("git.commit", commands)

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        message = arguments.get("message")
        if not isinstance(message, str) or not message.strip():
            raise ToolError("message must be a non-empty string", code="invalid_input")
        paths = arguments.get("paths", [])
        if not isinstance(paths, list) or not all(isinstance(item, str) for item in paths):
            raise ToolError("paths must be a list of strings", code="invalid_input")
        return {"message": message.strip(), "paths": list(paths)}

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        for raw in arguments["paths"]:
            try:
                resolve_inside_workspace(context.workspace_root, raw)
            except ValueError as exc:
                raise ToolError(str(exc), code="path_denied") from exc
        if arguments["paths"]:
            self._run(["git", "add", "--", *arguments["paths"]], context)
        return self._run(["git", "commit", "-m", arguments["message"]], context)


def git_tools(commands: SubprocessCommands | None = None) -> list[_GitTool]:
    active = commands or SubprocessCommands()
    return [
        GitStatusTool(active),
        GitDiffTool(active),
        GitBranchTool(active),
        GitCommitTool(active),
    ]
