"""Boot proof for a running core.

The markers are printed only after the core reports the corresponding result.
This module does not start QEMU and it does not call NVIDIA.
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any

_CORE = "http://127.0.0.1:8787"
_OBJECTIVE = "write file boot.txt with content OMNE"
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

    status = _mapping(_mapping(payload).get("task")).get("status")
    return status if isinstance(status, str) else None


def task_failure(payload: object) -> str:
    """The first error on a task response. Empty when the task did not fail."""

    errors = _mapping(_mapping(payload).get("task")).get("errors")
    if not isinstance(errors, list) or not errors:
        return ""
    first = _mapping(errors[0])
    code = first.get("code")
    message = first.get("message")
    if not isinstance(code, str):
        return ""
    detail = message if isinstance(message, str) else ""
    text = f"{code}: {detail}".replace("\n", " ").strip()
    return text[:180]


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


def health_ready(payload: object) -> bool:
    """True when GET /health returned the running core."""

    body = _mapping(payload)
    return body.get("status") == "ok" and body.get("service") == "OMNE-core"


def main() -> int:
    """Ask the running core for proof, then print the doctor report."""

    if _wait_for_health(45):
        task = _request(f"{_CORE}/tasks", {"objective": _OBJECTIVE}, timeout=45)
        models = _request(f"{_CORE}/models", None, timeout=10)
        status = task_status_from(task)
        cycles = lifecycles_from(models)
        for line in markers(task_status=status, lifecycles=cycles):
            print(line, flush=True)
        if status != "COMPLETED":
            detail = task_failure(task)
            suffix = f" {detail}" if detail else ""
            print(f"boot_proof_task={status or 'absent'}{suffix}", flush=True)
        if not any(isinstance(item, str) and item in _USABLE for item in cycles):
            print("boot_proof_models=absent", flush=True)
    else:
        print("boot_proof_error=core health was not ready", flush=True)
    completed = subprocess.run(["/usr/bin/OMNE", "doctor"], check=False)
    return int(completed.returncode)


def _wait_for_health(seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if health_ready(_request(f"{_CORE}/health", None, timeout=2)):
            return True
        time.sleep(0.5)
    return health_ready(_request(f"{_CORE}/health", None, timeout=2))


def _request(url: str, body: dict[str, str] | None, *, timeout: float = 60) -> object:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST" if data is not None else "GET",
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
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
