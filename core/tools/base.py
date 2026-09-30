"""Tool contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class ToolError(Exception):
    """A tool rejected its input or could not complete the operation."""

    def __init__(self, message: str, *, code: str = "tool_error") -> None:
        super().__init__(message)
        self.code = code


class ToolResult(BaseModel):
    """Structured success or failure from a tool invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ok: bool
    tool_id: str
    output: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, str] | None = None
    confirmation_required: bool = False
    unavailable: bool = False


class ToolContext(BaseModel):
    """Runtime data a tool may use. Tools do not receive a raw shell."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    task_id: str | None
    agent_id: str | None
    user: str
    workspace_root: Path
    timeout_seconds: int
    profile: str = "WORKER"


class Tool(Protocol):
    """A registered tool. Host access happens only inside ``execute``."""

    id: str

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Return validated arguments or raise ``ToolError``."""

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        """Perform the operation and return a JSON-compatible output."""
