"""Local HTTP server for JARVIS Core health reporting."""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from core import __version__
from core.config.settings import Settings
from core.logging_config import get_logger

logger = get_logger("api")


class ServerError(Exception):
    """Raised when the core HTTP server cannot bind to its address."""


def health_payload(settings: Settings) -> dict[str, str]:
    """Return the public health document.

    The payload intentionally excludes filesystem paths and other local details.
    """

    return {
        "status": "ok",
        "service": "jarvis-core",
        "version": __version__,
        "environment": settings.environment,
    }


class CoreHTTPServer(ThreadingHTTPServer):
    """Threading HTTP server that carries the active settings."""

    allow_reuse_address = True
    daemon_threads = True
    settings: Settings

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        super().__init__((settings.host, settings.port), CoreRequestHandler)


class CoreRequestHandler(BaseHTTPRequestHandler):
    """Serve ``/`` and ``/health`` as JSON."""

    server: CoreHTTPServer
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        status = HTTPStatus.INTERNAL_SERVER_ERROR
        payload: Mapping[str, object] = {"error": "internal_error"}
        try:
            status, payload = self._route_get()
        except Exception:
            logger.exception("request failed method=%s path=%s", self.command, self.path)
            status = HTTPStatus.INTERNAL_SERVER_ERROR
            payload = {"error": "internal_error"}
        self._send_json(status, payload)
        logger.info(
            "request method=%s path=%s status=%s",
            self.command,
            urlparse(self.path).path,
            int(status),
        )

    def do_POST(self) -> None:
        self._reject_method()

    def do_PUT(self) -> None:
        self._reject_method()

    def do_PATCH(self) -> None:
        self._reject_method()

    def do_DELETE(self) -> None:
        self._reject_method()

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self._apply_cors()
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        """Suppress the default stderr access log; structured logs are used instead."""

    def _route_get(self) -> tuple[HTTPStatus, Mapping[str, object]]:
        path = urlparse(self.path).path
        if path == "/health":
            return HTTPStatus.OK, health_payload(self.server.settings)
        if path == "/":
            return HTTPStatus.OK, {
                "service": "jarvis-core",
                "version": __version__,
                "health": "/health",
            }
        return HTTPStatus.NOT_FOUND, {"error": "not_found", "path": path}

    def _reject_method(self) -> None:
        self._send_json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "method_not_allowed"})
        logger.info(
            "request method=%s path=%s status=%s",
            self.command,
            urlparse(self.path).path,
            int(HTTPStatus.METHOD_NOT_ALLOWED),
        )

    def _send_json(self, status: HTTPStatus, payload: Mapping[str, object]) -> None:
        body = json.dumps(dict(payload), sort_keys=True).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self._apply_cors()
            self.end_headers()
            self.wfile.write(body)
        except Exception:
            logger.exception("failed to write response")

    def _apply_cors(self) -> None:
        origin = self.headers.get("Origin")
        allowed = _allowed_origin(self.server.settings.cors_origins, origin)
        if allowed is not None:
            self.send_header("Access-Control-Allow-Origin", allowed)
            self.send_header("Vary", "Origin")


def _allowed_origin(allowed_origins: list[str], origin: str | None) -> str | None:
    if origin is None or not allowed_origins:
        return None
    if allowed_origins == ["*"]:
        return "*"
    if origin in allowed_origins:
        return origin
    return None


class CoreServer:
    """Lifecycle wrapper around :class:`CoreHTTPServer`."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._httpd: CoreHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        if self._httpd is None:
            raise RuntimeError("JARVIS Core server is not running")
        return int(self._httpd.server_address[1])

    def start(self) -> None:
        if self._httpd is not None:
            raise RuntimeError("JARVIS Core server is already running")
        try:
            self._httpd = CoreHTTPServer(self.settings)
        except OSError as exc:
            raise ServerError(
                f"Unable to bind {self.settings.host}:{self.settings.port}: {exc.strerror}"
            ) from exc
        if self.settings.host in {"0.0.0.0", "::"}:
            logger.warning(
                "JARVIS Core is bound to a non-loopback address host=%s",
                self.settings.host,
            )
        logger.info("JARVIS Core listening host=%s port=%s", self.settings.host, self.port)

    def serve_forever(self) -> None:
        self.start()
        self._serve_loop()
        self._httpd = None

    def start_in_thread(self) -> None:
        self.start()
        self._thread = threading.Thread(target=self._serve_loop, name="jarvis-core", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        # HTTPServer.shutdown waits for serve_forever and must run on another thread.
        httpd = self._httpd
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)
            self._thread = None
        self._httpd = None

    def _serve_loop(self) -> None:
        httpd = self._httpd
        if httpd is None:
            return
        try:
            httpd.serve_forever(poll_interval=0.1)
        finally:
            httpd.server_close()
