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
from tests.support import runtime_settings

from core.api.runtime import build_OMNE
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
                "OMNE_HOST": "127.0.0.1",
                "OMNE_PORT": str(_free_port()),
                "OMNE_LOG_LEVEL": "ERROR",
                "OMNE_CORS_ORIGINS": "http://127.0.0.1:4173",
                "OMNE_WORKSPACE_ROOT": str(tmp_path / "secret-workspace"),
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
        environ={"OMNE_WORKSPACE_ROOT": str(tmp_path / "secret-workspace")},
        cwd=tmp_path,
    )

    payload = health_payload(settings)

    assert set(payload) == _HEALTH_KEYS
    assert "secret-workspace" not in json.dumps(payload)


def test_health_endpoint(server: CoreServer) -> None:
    status, body, _origin = _request(f"http://127.0.0.1:{server.port}/health")

    assert status == 200
    assert body["status"] == "ok"
    assert body["service"] == "OMNE-core"
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


def test_desktop_without_runtime_is_unavailable(server: CoreServer) -> None:
    status, body, _origin = _request(f"http://127.0.0.1:{server.port}/desktop")

    assert status == 503
    assert body["error"] == "runtime_unavailable"


def test_desktop_returns_shell_panels(tmp_path: Path) -> None:
    settings = runtime_settings(tmp_path, OMNE_HOST="127.0.0.1", OMNE_PORT=str(_free_port()))
    started = CoreServer(settings, build_OMNE(settings))
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
        status, body, _origin = _request(f"http://127.0.0.1:{started.port}/desktop")
    finally:
        started.stop()

    assert status == 200
    assert set(body) >= {"agents", "events", "models", "tasks", "voice"}
    assert "missions" in body
    assert "workers" in body
    assert "compute" not in body


def test_network_endpoint_is_read_only(tmp_path: Path) -> None:
    settings = runtime_settings(tmp_path, OMNE_HOST="127.0.0.1", OMNE_PORT=str(_free_port()))
    started = CoreServer(settings, build_OMNE(settings))
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
        status, body, _origin = _request(f"http://127.0.0.1:{started.port}/network")
        posted, payload, _posted_origin = _request(
            f"http://127.0.0.1:{started.port}/network",
            method="POST",
        )
    finally:
        started.stop()

    assert status == 200
    network = body["network"]
    assert isinstance(network, dict)
    assert network["provider"] == "mock"
    assert network["stack_commanded"] is False
    assert posted == 404
    assert payload["error"] == "not_found"


def test_disallowed_origin_is_omitted(server: CoreServer) -> None:
    _status, _body, origin = _request(
        f"http://127.0.0.1:{server.port}/health",
        origin="http://evil.example",
    )

    assert origin is None
