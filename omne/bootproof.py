"""Boot proof for a running core.

The markers are printed only after the core reports the corresponding result.
This module does not start QEMU and it does not call NVIDIA.
"""

from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any

_CORE = "http://127.0.0.1:8787"
_OBJECTIVE = "remember this sentence"
_USABLE = frozenset({"AVAILABLE", "LOADED", "BUSY", "IDLE"})


def markers(*, task_status: object, lifecycles: object) -> list[str]:
    """Serial lines for one completed task and one usable model."""

    lines: list[str] = []
    if task_status == "COMPLETED":
        lines.append("agent task completed")
    if isinstance(lifecycles, list) and any(
        isinstance(item, str) and item in _USABLE for item in lifecycles
    ):
        lines.append("model runtime ready")
    return lines


def task_status_from(payload: object) -> str | None:
    """Read the status field from a ``/tasks`` response."""

    task = _mapping(payload).get("task")
    status = _mapping(task).get("status")
    return status if isinstance(status, str) else None


def lifecycles_from(payload: object) -> list[str]:
    """Read model lifecycle values from a ``/models`` response."""

    models = _mapping(payload).get("models")
    if not isinstance(models, list):
        return []
    found: list[str] = []
    for item in models:
        lifecycle = _mapping(item).get("lifecycle")
        if isinstance(lifecycle, str):
            found.append(lifecycle)
    return found


def main() -> int:
    """Ask the running core for proof, then print the doctor report."""

    task = _request(f"{_CORE}/tasks", {"objective": _OBJECTIVE})
    models = _request(f"{_CORE}/models", None)
    for line in markers(
        task_status=task_status_from(task),
        lifecycles=lifecycles_from(models),
    ):
        print(line, flush=True)
    completed = subprocess.run(["/usr/bin/OMNE", "doctor"], check=False)
    return int(completed.returncode)


def _request(url: str, body: dict[str, str] | None) -> object:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST" if data is not None else "GET",
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read()
    except (OSError, urllib.error.URLError, TimeoutError, ValueError):
        return None
    if not isinstance(payload, bytes):
        return None
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return None


def _mapping(value: object) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}
