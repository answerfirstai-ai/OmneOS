"""Process inspection and controlled process start, stop, and restart.

The tools call the process service. They do not spawn a process and they do
not send a signal.
"""

from __future__ import annotations

from typing import Any

from core.permissions.policies import dangerous_command
from core.tools.base import ToolContext, ToolError
from omne.processes.model import ProcessOutcome, ProcessRecord, ProcessRequest
from omne.processes.select import process_service
from omne.processes.service import ProcessService

_REJECTED = {"command", "shell", "password"}


class ProcessListTool:
    id = "process.list"

    def __init__(self, service: ProcessService) -> None:
        self._service = service

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        limit = arguments.get("limit", 50)
        if not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ToolError("limit must be an integer from 1 to 200", code="invalid_input")
        return {"limit": limit}

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        del context
        snapshot = self._service.status()
        if not snapshot.observed:
            return {"available": False, "processes": [], "reason": "process table was not observed"}
        rows = [_row(item) for item in snapshot.processes[: arguments["limit"]]]
        return {"available": True, "processes": rows}


class ProcessStartTool:
    id = "process.start"

    def __init__(self, service: ProcessService) -> None:
        self._service = service

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        _reject_shell_keys(arguments)
        argv = arguments.get("argv")
        if (
            not isinstance(argv, list)
            or not argv
            or not all(isinstance(item, str) for item in argv)
        ):
            raise ToolError("argv must be a non-empty list of strings", code="invalid_input")
        return {"argv": list(argv)}

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        reason = dangerous_command(arguments["argv"])
        if reason is not None:
            raise ToolError(reason, code="denied")
        outcome = self._service.apply(
            ProcessRequest(
                action="start",
                agent_id=context.agent_id or "local",
                task_id=context.task_id,
                argv=list(arguments["argv"]),
            ),
            {},
            "testing",
            permitted=True,
        )
        if not outcome.applied:
            raise ToolError(outcome.reason, code="denied")
        pid = _event_pid(outcome)
        record = _record(outcome, pid)
        return {
            "pid": pid,
            "applied": True,
            "reason": outcome.reason,
            "ownership": record.ownership.model_dump(mode="json"),
        }


class ProcessStopTool:
    id = "process.stop"

    def __init__(self, service: ProcessService) -> None:
        self._service = service

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return _pid(arguments)

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        outcome = self._service.apply(
            _lifecycle("stop", arguments["pid"], context), {}, "testing", permitted=True
        )
        if not outcome.applied:
            raise ToolError(outcome.reason, code="denied")
        return {"pid": arguments["pid"], "state": "stopped", "reason": outcome.reason}


class ProcessRestartTool:
    id = "process.restart"

    def __init__(self, service: ProcessService) -> None:
        self._service = service

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return _pid(arguments)

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        outcome = self._service.apply(
            _lifecycle("restart", arguments["pid"], context),
            {},
            "testing",
            permitted=True,
        )
        if not outcome.applied:
            raise ToolError(outcome.reason, code="denied")
        return {"pid": arguments["pid"], "state": "running", "reason": outcome.reason}


class ProcessCommandTool:
    id = "process.command"

    def __init__(self, service: ProcessService) -> None:
        self._service = service

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return _pid(arguments)

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        outcome = self._service.apply(
            ProcessRequest(
                action="command",
                agent_id=context.agent_id or "local",
                task_id=context.task_id,
                pid=arguments["pid"],
                reveal=True,
            ),
            {},
            "testing",
            permitted=True,
        )
        if not outcome.applied or outcome.command_line is None:
            raise ToolError(outcome.reason, code="denied")
        return {"pid": arguments["pid"], "command_line": outcome.command_line}


def process_tools(
    service: ProcessService | None = None,
) -> list[
    ProcessListTool | ProcessStartTool | ProcessStopTool | ProcessRestartTool | ProcessCommandTool
]:
    bound = service if service is not None else process_service("testing")
    return [
        ProcessListTool(bound),
        ProcessStartTool(bound),
        ProcessStopTool(bound),
        ProcessRestartTool(bound),
        ProcessCommandTool(bound),
    ]


def _reject_shell_keys(arguments: dict[str, Any]) -> None:
    if any(key in arguments for key in _REJECTED):
        raise ToolError("process start does not accept a shell command", code="invalid_input")


def _pid(arguments: dict[str, Any]) -> dict[str, Any]:
    _reject_shell_keys(arguments)
    pid = arguments.get("pid")
    if not isinstance(pid, int) or pid < 1:
        raise ToolError("pid must be an integer greater than or equal to 1", code="invalid_input")
    return {"pid": pid}


def _lifecycle(action: str, pid: int, context: ToolContext) -> ProcessRequest:
    if action == "stop":
        return ProcessRequest(
            action="stop",
            agent_id=context.agent_id or "local",
            task_id=context.task_id,
            pid=pid,
        )
    return ProcessRequest(
        action="restart",
        agent_id=context.agent_id or "local",
        task_id=context.task_id,
        pid=pid,
    )


def _event_pid(outcome: ProcessOutcome) -> int:
    if not outcome.events:
        raise ToolError(outcome.reason, code="denied")
    pid = outcome.events[0].payload.get("pid")
    if not isinstance(pid, int):
        raise ToolError(outcome.reason, code="denied")
    return pid


def _record(outcome: ProcessOutcome, pid: int) -> ProcessRecord:
    for item in outcome.state.processes:
        if item.pid == pid:
            return item
    raise ToolError(outcome.reason, code="denied")


def _row(record: ProcessRecord) -> dict[str, Any]:
    return {
        "pid": record.pid,
        "executable": record.executable,
        "state": record.state,
        "owner": record.owner,
        "protection": record.protection,
        "cpu_percent": record.cpu_percent,
        "cpu_seconds": record.cpu_seconds,
        "ram_bytes": record.ram_bytes,
        "parent_pid": record.parent_pid,
        "children": list(record.children),
        "started_at": record.started_at,
        "limits": record.limits.model_dump(mode="json"),
        "owned": record.owned,
        "ownership": record.ownership.model_dump(mode="json"),
    }
