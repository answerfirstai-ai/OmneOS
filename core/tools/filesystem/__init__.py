"""Workspace-scoped filesystem tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.tools.base import ToolContext, ToolError
from omne.storage.classify import classify_path

_MAX_BYTES = 1_000_000
_MAX_SEARCH_RESULTS = 200
_BINARY_SUFFIXES = frozenset(
    {
        ".bin",
        ".db",
        ".dll",
        ".exe",
        ".gif",
        ".gz",
        ".ico",
        ".jpeg",
        ".jpg",
        ".mp3",
        ".mp4",
        ".otf",
        ".pdf",
        ".png",
        ".pyc",
        ".so",
        ".sqlite",
        ".tar",
        ".ttf",
        ".wasm",
        ".webp",
        ".woff",
        ".woff2",
        ".zip",
    }
)


class _FilesystemTool:
    def __init__(self, tool_id: str) -> None:
        self.id = tool_id

    def _path(self, arguments: dict[str, Any], context: ToolContext) -> Path:
        raw = arguments.get("path", ".")
        if not isinstance(raw, str) or not raw:
            raise ToolError("path must be a non-empty string", code="invalid_input")
        verdict = classify_path(raw, workspace=context.workspace_root)
        if not verdict.allowed:
            raise ToolError(verdict.reason, code="path_denied")
        return Path(verdict.resolved)


class ReadTool(_FilesystemTool):
    def __init__(self) -> None:
        super().__init__("filesystem.read")

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = arguments.get("path")
        if not isinstance(path, str) or not path:
            raise ToolError("path must be a non-empty string", code="invalid_input")
        return {"path": path}

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        path = self._path(arguments, context)
        if not path.is_file():
            raise ToolError(f"file not found: {path.name}", code="not_found")
        data = path.read_bytes()
        if len(data) > _MAX_BYTES:
            raise ToolError("file exceeds the read limit", code="too_large")
        return {"path": arguments["path"], "content": data.decode("utf-8", errors="replace")}


class WriteTool(_FilesystemTool):
    def __init__(self) -> None:
        super().__init__("filesystem.write")

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = arguments.get("path")
        content = arguments.get("content")
        if not isinstance(path, str) or not path:
            raise ToolError("path must be a non-empty string", code="invalid_input")
        if not isinstance(content, str):
            raise ToolError("content must be a string", code="invalid_input")
        if len(content.encode("utf-8")) > _MAX_BYTES:
            raise ToolError("content exceeds the write limit", code="too_large")
        return {"path": path, "content": content}

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        path = self._path(arguments, context)
        if ".git" in path.parts:
            raise ToolError("filesystem access inside .git is denied", code="path_denied")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(arguments["content"], encoding="utf-8")
        return {"path": arguments["path"], "bytes": len(arguments["content"].encode("utf-8"))}


class SearchTool(_FilesystemTool):
    def __init__(self) -> None:
        super().__init__("filesystem.search")

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ToolError("query must be a non-empty string", code="invalid_input")
        path = arguments.get("path", ".")
        if not isinstance(path, str) or not path:
            raise ToolError("path must be a non-empty string", code="invalid_input")
        return {"query": query, "path": path}

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        root = self._path(arguments, context)
        query = arguments["query"].lower()
        matches: list[str] = []
        if not root.exists():
            return {"matches": matches}
        files = (
            [root] if root.is_file() else sorted(item for item in root.rglob("*") if item.is_file())
        )
        for item in files:
            if ".git" in item.parts:
                continue
            relative = str(item.relative_to(context.workspace_root.resolve()))
            matched = query in item.name.lower() or query in relative.lower()
            if (
                not matched
                and item.suffix.lower() not in _BINARY_SUFFIXES
                and item.stat().st_size <= _MAX_BYTES
            ):
                text = item.read_text(encoding="utf-8", errors="ignore").lower()
                matched = query in text
            if matched:
                matches.append(relative)
            if len(matches) >= _MAX_SEARCH_RESULTS:
                break
        return {"matches": matches}


class CreateDirectoryTool(_FilesystemTool):
    def __init__(self) -> None:
        super().__init__("filesystem.create_directory")

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = arguments.get("path")
        if not isinstance(path, str) or not path:
            raise ToolError("path must be a non-empty string", code="invalid_input")
        return {"path": path}

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        path = self._path(arguments, context)
        path.mkdir(parents=True, exist_ok=True)
        return {"path": arguments["path"], "created": True}


def filesystem_tools() -> list[_FilesystemTool]:
    return [ReadTool(), WriteTool(), SearchTool(), CreateDirectoryTool()]
