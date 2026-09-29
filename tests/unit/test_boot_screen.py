"""The boot checklist reports real probes and does not invent a ready GPU."""

from __future__ import annotations

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

from tests.conftest import ROOT

BOOT = ROOT / "system" / "linux" / "omne-boot"


class _CoreHandler(BaseHTTPRequestHandler):
    health: ClassVar[dict[str, str]] = {
        "status": "ok",
        "service": "OMNE-core",
        "version": "0.1.0",
        "environment": "production",
    }
    models: ClassVar[dict[str, object]] = {
        "models": [{"id": "mock", "lifecycle": "AVAILABLE", "loaded": False}]
    }

    def do_GET(self) -> None:
        if self.path == "/health":
            body = json.dumps(self.health).encode("utf-8")
            status = 200
        elif self.path == "/models":
            body = json.dumps(self.models).encode("utf-8")
            status = 200
        else:
            body = b""
            status = 404
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        return


def _serve(handler: type[BaseHTTPRequestHandler]) -> tuple[ThreadingHTTPServer, int]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = int(server.server_address[1])
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, port


def _machine(root: Path, *, network: str, gpu: bool) -> None:
    (root / "proc").mkdir(parents=True)
    (root / "proc" / "cpuinfo").write_text("processor\t: 0\n", encoding="utf-8")
    (root / "proc" / "mounts").write_text("/dev/vda2 / ext4 rw 0 0\n", encoding="utf-8")
    iface = root / "sys" / "class" / "net" / "eth0"
    iface.mkdir(parents=True)
    (iface / "operstate").write_text(network, encoding="utf-8")
    if gpu:
        (root / "sys" / "class" / "drm" / "card0").mkdir(parents=True)


def _boot(root: Path, core: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(BOOT), "--once"],
        check=False,
        capture_output=True,
        text=True,
        env={
            "OMNE_BOOT_ROOT": str(root),
            "OMNE_BOOT_CORE": core,
            "PATH": "/usr/bin:/bin",
        },
    )


def test_ready_screen_uses_real_passes(tmp_path: Path) -> None:
    _machine(tmp_path, network="up", gpu=True)
    server, port = _serve(_CoreHandler)
    try:
        result = _boot(tmp_path, f"http://127.0.0.1:{port}")
    finally:
        server.shutdown()

    assert result.returncode == 0
    text = result.stdout
    assert text.startswith("OMNE\nInitializing...\n")
    assert "✓ Hardware" in text
    assert "✓ Storage" in text
    assert "✓ Network" in text
    assert "✓ GPU" in text
    assert "✓ Core" in text
    assert "✓ Models" in text
    assert text.rstrip().endswith("OMNE READY")
    assert "loaded" not in text.lower()
    assert "Ubuntu" not in text
    assert "login" not in text.lower()


def test_unavailable_gpu_and_models_are_not_checks(tmp_path: Path) -> None:
    class Handler(_CoreHandler):
        models: ClassVar[dict[str, object]] = {
            "models": [{"id": "local", "lifecycle": "UNAVAILABLE", "loaded": False}]
        }

    _machine(tmp_path, network="down", gpu=False)
    server, port = _serve(Handler)
    try:
        result = _boot(tmp_path, f"http://127.0.0.1:{port}")
    finally:
        server.shutdown()

    assert result.returncode == 0
    text = result.stdout
    assert "✓ Hardware" in text
    assert "✓ Storage" in text
    assert "· Network down" in text
    assert "✓ Network" not in text
    assert "· GPU unavailable" in text
    assert "✓ GPU" not in text
    assert "✓ Core" in text
    assert "· Models unavailable" in text
    assert "✓ Models" not in text
    assert "OMNE READY" in text


def test_core_failure_is_not_ready(tmp_path: Path) -> None:
    _machine(tmp_path, network="up", gpu=False)
    result = _boot(tmp_path, "http://127.0.0.1:9")

    assert result.returncode == 1
    assert "× Core" in result.stdout  # noqa: RUF001
    assert "· Models unavailable" in result.stdout
    assert "OMNE NOT READY" in result.stdout
    assert "OMNE READY" not in result.stdout


def test_boot_waits_until_core_answers(tmp_path: Path) -> None:
    class Handler(_CoreHandler):
        misses: ClassVar[int] = 2

        def do_GET(self) -> None:
            if type(self).misses > 0:
                type(self).misses -= 1
                self.send_response(503)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            super().do_GET()

    _machine(tmp_path, network="up", gpu=False)
    server, port = _serve(Handler)
    try:
        result = subprocess.run(
            [str(BOOT)],
            check=False,
            capture_output=True,
            text=True,
            env={
                "OMNE_BOOT_ROOT": str(tmp_path),
                "OMNE_BOOT_CORE": f"http://127.0.0.1:{port}",
                "OMNE_BOOT_ATTEMPTS": "4",
                "OMNE_BOOT_PAUSE": "0",
                "OMNE_BOOT_HOLD": "0",
                "PATH": "/usr/bin:/bin",
            },
        )
    finally:
        server.shutdown()

    assert result.returncode == 0
    assert "✓ Core" in result.stdout
    assert result.stdout.rstrip().endswith("OMNE READY")


def test_missing_hardware_is_not_ready(tmp_path: Path) -> None:
    server, port = _serve(_CoreHandler)
    try:
        result = _boot(tmp_path, f"http://127.0.0.1:{port}")
    finally:
        server.shutdown()

    assert result.returncode == 1
    assert "× Hardware" in result.stdout  # noqa: RUF001
    assert "× Storage" in result.stdout  # noqa: RUF001
    assert "OMNE NOT READY" in result.stdout
