"""HTTP server tests."""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from core.api.server import CoreServer, health_payload
from core.config.settings import load_settings

_HEALTH_KEYS = {"status", "service", "version", "environment"}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def server(tmp_path: Path) -> Iterator[CoreServer]:
    started = CoreServer(
        load_settings(
            environ={
                "JARVIS_HOST": "127.0.0.1",
                "JARVIS_PORT": str(_free_port()),
                "JARVIS_LOG_LEVEL": "ERROR",
                "JARVIS_CORS_ORIGINS": "http://127.0.0.1:4173",
                "JARVIS_WORKSPACE_ROOT": str(tmp_path / "secret-workspace"),
            },
            cwd=tmp_path,
        )
    )
    started.start_in_thread()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", started.port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.01)
    else:
        started.stop()
        raise RuntimeError("server did not accept connections")
    try:
        yield started
    finally:
        started.stop()


def _request(
    url: str, *, method: str = "GET", origin: str | None = None
) -> tuple[int, dict[str, object], str | None]:
    headers = {}
    if origin is not None:
        headers["Origin"] = origin
    request = urllib.request.Request(url, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            raw = response.read()
            body = json.loads(raw.decode("utf-8")) if raw else {}
            return response.status, body, response.headers.get("Access-Control-Allow-Origin")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        body = json.loads(raw.decode("utf-8")) if raw else {}
        return exc.code, body, exc.headers.get("Access-Control-Allow-Origin")


def test_health_payload_excludes_local_paths(tmp_path: Path) -> None:
    settings = load_settings(
        environ={"JARVIS_WORKSPACE_ROOT": str(tmp_path / "secret-workspace")},
        cwd=tmp_path,
    )

    payload = health_payload(settings)

    assert set(payload) == _HEALTH_KEYS
    assert "secret-workspace" not in json.dumps(payload)


def test_health_endpoint(server: CoreServer) -> None:
    status, body, _origin = _request(f"http://127.0.0.1:{server.port}/health")

    assert status == 200
    assert body["status"] == "ok"
    assert body["service"] == "jarvis-core"
    assert set(body) == _HEALTH_KEYS


def test_unknown_path_is_not_found(server: CoreServer) -> None:
    status, body, _origin = _request(f"http://127.0.0.1:{server.port}/missing")

    assert status == 404
    assert body["error"] == "not_found"


def test_post_is_method_not_allowed(server: CoreServer) -> None:
    status, body, _origin = _request(f"http://127.0.0.1:{server.port}/health", method="POST")

    assert status == 405
    assert body["error"] == "method_not_allowed"


def test_allowed_origin_is_echoed(server: CoreServer) -> None:
    _status, _body, origin = _request(
        f"http://127.0.0.1:{server.port}/health",
        origin="http://127.0.0.1:4173",
    )

    assert origin == "http://127.0.0.1:4173"


def test_options_allows_json_post_from_the_shell(server: CoreServer) -> None:
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.port}/tasks",
        headers={
            "Origin": "http://127.0.0.1:4173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
        method="OPTIONS",
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        assert response.status == 204
        assert response.headers.get("Access-Control-Allow-Origin") == "http://127.0.0.1:4173"
        assert "POST" in (response.headers.get("Access-Control-Allow-Methods") or "")
        assert "Content-Type" in (response.headers.get("Access-Control-Allow-Headers") or "")


def test_disallowed_origin_is_omitted(server: CoreServer) -> None:
    _status, _body, origin = _request(
        f"http://127.0.0.1:{server.port}/health",
        origin="http://evil.example",
    )

    assert origin is None
