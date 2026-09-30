"""Parse a desktop entry without executing it.

``Exec`` is split into an argument list only far enough to name the program.
Shell syntax is rejected, and the program is never started.
"""

from __future__ import annotations

import re
from pathlib import Path

from omne.applications.model import Application

_SHELL = re.compile(r"[|&;<>`$()\\]|[\n\r]")
_FIELD_CODE = re.compile(r"^%[%fFuUdDnNickvm]$")
_SHELLS = frozenset({"sh", "bash", "dash", "zsh", "fish", "ksh"})
_LAUNCH = "application:launch"


def parse_desktop_file(path: Path) -> Application | None:
    """Return one application, or none when the file is not an application."""

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    fields = _desktop_entry(text)
    if fields is None:
        return None
    kind = fields.get("Type", "Application")
    if kind != "Application":
        return None
    name = fields.get("Name", "").strip()
    if not name:
        return None
    executable = parse_executable(fields.get("Exec", ""))
    hidden = _truthy(fields.get("Hidden")) or _truthy(fields.get("NoDisplay"))
    categories = [item for item in fields.get("Categories", "").split(";") if item]
    launchable = executable is not None and not hidden
    return Application(
        id=path.name.removesuffix(".desktop"),
        name=name,
        desktop_entry=path.name,
        executable=executable,
        icon=fields.get("Icon", "").strip(),
        categories=categories,
        permissions=[_LAUNCH] if launchable else [],
        state="hidden" if hidden else "installed",
        launchable=launchable,
    )


def parse_executable(exec_line: str) -> str | None:
    """Return the program path from an ``Exec`` key, never a shell command."""

    if not exec_line.strip() or _SHELL.search(exec_line):
        return None
    tokens = [token for token in _split(exec_line) if not _FIELD_CODE.fullmatch(token)]
    if tokens and tokens[0] == "env":
        tokens = tokens[1:]
        while tokens and _assignment(tokens[0]):
            tokens = tokens[1:]
    if not tokens:
        return None
    program = tokens[0]
    if Path(program).name in _SHELLS:
        return None
    return program


def _desktop_entry(text: str) -> dict[str, str] | None:
    fields: dict[str, str] = {}
    group = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            group = line[1:-1].strip()
            continue
        if group != "Desktop Entry" or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if "[" in key:
            continue
        fields.setdefault(key, _unescape(value.strip()))
    if not fields:
        return None
    return fields


def _split(text: str) -> list[str]:
    tokens: list[str] = []
    current: list[str] = []
    quote = False
    for character in text:
        if character == '"':
            quote = not quote
            continue
        if character.isspace() and not quote:
            if current:
                tokens.append("".join(current))
                current = []
            continue
        current.append(character)
    if current:
        tokens.append("".join(current))
    return tokens


def _unescape(value: str) -> str:
    return (
        value.replace(r"\s", " ")
        .replace(r"\n", " ")
        .replace(r"\t", " ")
        .replace(r"\r", " ")
        .replace(r"\\", "\\")
    )


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() == "true"


def _assignment(token: str) -> bool:
    return "=" in token and not token.startswith("/") and not token.startswith("-")
