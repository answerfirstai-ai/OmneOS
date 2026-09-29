"""Process-level startup test for `python -m core serve`."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from tests.conftest import ROOT


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_serve_process_answers_health(tmp_path: Path) -> None:
    port = _free_port()
    env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", ""),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "PYTHONPATH": str(ROOT),
        "PYTHONUNBUFFERED": "1",
        "OMNE_LOG_LEVEL": "INFO",
        "OMNE_LOG_FORMAT": "text",
        "OMNE_HOST": "127.0.0.1",
        "OMNE_PORT": str(port),
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "core", "serve"],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    url = f"http://127.0.0.1:{port}/health"
    body: dict[str, object] | None = None
    last_error = "health endpoint was not reached"
    deadline = time.monotonic() + 5
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                last_error = f"process exited early with status {process.returncode}"
                break
            try:
                with urllib.request.urlopen(url, timeout=0.5) as response:
                    loaded = json.loads(response.read().decode("utf-8"))
                    if isinstance(loaded, dict):
                        body = loaded
                        break
                    last_error = "health response was not an object"
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = str(exc)
                time.sleep(0.05)
        assert body is not None, last_error
        assert body["status"] == "ok"
        assert body["service"] == "OMNE-core"
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=5)
    assert process.returncode == 0, stderr
    assert "OMNE Core listening" in stderr
    assert stdout == ""
