"""Read recovery checks. The probe does not start units or change disks.

A fixture root supplies the same files the host probe reads. The live host
asks systemd only whether a unit is active.
"""

from __future__ import annotations

import os
import socket
import subprocess
from pathlib import Path
from typing import Protocol

from omne.recovery.model import CHECKS, CheckName, ProbeReport, check_result


class RecoveryProbe(Protocol):
    """A read of the checks. Implementations do not start services."""

    def probe(self, *, data_dir: Path | None, port: int) -> ProbeReport:
        """Return the current checks."""


class MockRecoveryProbe:
    """A healthy machine. Tests replace individual checks through the service."""

    def probe(self, *, data_dir: Path | None, port: int) -> ProbeReport:
        del data_dir, port
        return ProbeReport(checks=[check_result(name, ok=True) for name in CHECKS])


class LinuxRecoveryProbe:
    """Read Linux, systemd, and the OMNE units. This does not activate them."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = Path("/") if root is None else root

    def probe(self, *, data_dir: Path | None, port: int) -> ProbeReport:
        if _is_host(self._root):
            return self._from_host(data_dir=data_dir, port=port)
        return self._from_fixture()

    def _from_fixture(self) -> ProbeReport:
        root = self._root
        linux_ok = _text(root / "proc" / "version").find("Linux") >= 0
        systemd_ok = _text(root / "proc" / "1" / "comm").strip() == "systemd"
        service = _text(root / "run" / "omne" / "omne-core.state").strip()
        shell = _text(root / "run" / "omne" / "omne-shell.state").strip()
        core_ok = _text(root / "run" / "omne" / "core.state").strip() == "up"
        ipc_ok = _text(root / "run" / "omne" / "ipc.state").strip() == "up"
        graphics_ok = _text(root / "run" / "omne" / "graphics.state").strip() == "ready"
        network_ok = _text(root / "run" / "omne" / "network.state").strip() == "ready"
        storage_ok = _text(root / "run" / "omne" / "storage.state").strip() == "ready"
        return _report(
            linux_ok=linux_ok,
            systemd_ok=systemd_ok,
            service_ok=service == "active",
            core_ok=core_ok,
            ipc_ok=ipc_ok,
            graphics_ok=graphics_ok,
            network_ok=network_ok,
            storage_ok=storage_ok,
            shell_failed=shell not in {"", "active"},
            shell_reason="shell stopped" if shell not in {"", "active"} else "",
        )

    def _from_host(self, *, data_dir: Path | None, port: int) -> ProbeReport:
        version = _text(Path("/proc/version"))
        comm = _text(Path("/proc/1/comm")).strip()
        service = _unit_state("omne-core.service")
        shell = _unit_state("omne-shell.service")
        storage_ok = data_dir is not None and data_dir.is_dir() and _writable(data_dir)
        return _report(
            linux_ok="Linux" in version,
            systemd_ok=comm == "systemd" or Path("/run/systemd/system").is_dir(),
            service_ok=service == "active",
            core_ok=True,
            ipc_ok=_ipc_open(port),
            graphics_ok=_graphics_ready(),
            network_ok=_network_ready(),
            storage_ok=storage_ok,
            shell_failed=shell not in {"active", "unknown"},
            shell_reason="shell stopped" if shell not in {"active", "unknown"} else "",
        )


def _report(
    *,
    linux_ok: bool,
    systemd_ok: bool,
    service_ok: bool,
    core_ok: bool,
    ipc_ok: bool,
    graphics_ok: bool,
    network_ok: bool,
    storage_ok: bool,
    shell_failed: bool,
    shell_reason: str,
) -> ProbeReport:
    flags: dict[CheckName, bool] = {
        "linux": linux_ok,
        "systemd": systemd_ok,
        "service": service_ok,
        "core": core_ok,
        "ipc": ipc_ok,
        "graphics": graphics_ok,
        "network": network_ok,
        "storage": storage_ok,
    }
    return ProbeReport(
        checks=[check_result(name, ok=flags[name]) for name in CHECKS],
        shell_failed=shell_failed,
        shell_reason=shell_reason,
    )


def _is_host(root: Path) -> bool:
    return root == Path("/")


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _writable(path: Path) -> bool:
    return path.is_dir() and os.access(path, os.W_OK)


def _unit_state(unit: str) -> str:
    """Ask systemd for the active state. This does not start the unit."""

    try:
        completed = subprocess.run(
            ["systemctl", "is-active", unit],
            check=False,
            capture_output=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    text = completed.stdout.decode("utf-8", errors="replace").strip()
    return text or "unknown"


def _ipc_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return True
    except OSError:
        return False


def _graphics_ready() -> bool:
    from omne.display.select import diagnose_display

    report = diagnose_display("production")
    return report.can_launch


def _network_ready() -> bool:
    from omne.network.select import network_service

    state = network_service("production").inspect()
    return state.default_route is not None
