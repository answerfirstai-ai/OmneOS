"""VM scoring blocks downstream checks when an earlier dependency fails."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

from tests.conftest import ROOT


def _score_module() -> ModuleType:
    path = ROOT / "scripts" / "linux" / "vm-score.py"
    spec = importlib.util.spec_from_file_location("vm_score", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


vm_score = _score_module()


def _log(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def _by_name(summary: dict[str, object]) -> dict[str, dict[str, object]]:
    checks = summary["checks"]
    assert isinstance(checks, list)
    return {str(item["name"]): item for item in checks}


def test_missing_core_health_blocks_the_desktop_chain(tmp_path: Path) -> None:
    log = _log(
        "Linux version 6.8",
        "Kernel command line: root=LABEL=OMNE",
        "Reached target local-fs.target",
        "Started systemd-networkd.service",
        "Reached target network.target",
        "virtio_net",
        "Started omne-core.service",
        "Reached target omne.target",
        "Reached target multi-user.target",
        "Reached target reboot.target",
        "Linux version 6.8",
        "Reached target multi-user.target",
        "Reached target poweroff.target",
    )
    summary = vm_score.score(
        log,
        run_id="core-missing",
        elapsed_ms=1000,
        guest_exited=True,
        snapshot_ok=True,
    )
    checks = _by_name(summary)

    assert summary["os_ready"] is False
    assert summary["first_failure"] == "core-health"
    assert checks["omne-service"]["status"] == "PASS"
    assert checks["core-health"]["status"] == "FAIL"
    assert checks["core-health"]["exit_code"] == 1
    for name in (
        "ipc",
        "graphical-session",
        "wayland",
        "omne-shell",
        "applications",
        "agents",
        "models",
        "recovery",
    ):
        assert checks[name]["status"] == "BLOCKED"
        assert checks[name]["exit_code"] is None
        assert checks[name]["error"] == "core-health unavailable"
    assert checks["network"]["status"] == "PASS"
    assert checks["reboot"]["status"] == "PASS"
    assert checks["shutdown"]["status"] == "PASS"

    vm_score.write_artifact(tmp_path, log, summary)
    saved = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert saved["first_failure"] == "core-health"
    assert (tmp_path / "core.log").is_file()
    assert (tmp_path / "services.log").read_text(encoding="utf-8").find("omne-core") >= 0


def test_health_without_a_session_fails_at_the_graphical_check() -> None:
    log = _log(
        "Linux version 6.8",
        "root=LABEL=OMNE",
        "Reached target local-fs.target",
        "Started systemd-networkd.service",
        "Reached target network.target",
        "virtio_net",
        "Started omne-core.service",
        "Reached target omne.target",
        "Reached target multi-user.target",
        "ipc ok",
        "OMNE READY",
        "Reached target reboot.target",
        "Linux version 6.8",
        "Reached target multi-user.target",
        "Reached target poweroff.target",
    )
    summary = vm_score.score(
        log,
        run_id="no-session",
        elapsed_ms=1000,
        guest_exited=True,
        snapshot_ok=True,
    )
    checks = _by_name(summary)

    assert summary["first_failure"] == "graphical-session"
    assert checks["core-health"]["status"] == "PASS"
    assert checks["ipc"]["status"] == "PASS"
    assert checks["graphical-session"]["status"] == "FAIL"
    assert checks["wayland"]["status"] == "BLOCKED"
    assert checks["omne-shell"]["status"] == "BLOCKED"
    assert checks["applications"]["status"] == "BLOCKED"


def test_a_complete_log_is_os_ready() -> None:
    log = _log(
        "Linux version 6.8",
        "root=LABEL=OMNE",
        "Reached target local-fs.target",
        "Started systemd-networkd.service",
        "Reached target network.target",
        "virtio_net",
        "Started omne-core.service",
        "Reached target omne.target",
        "Reached target multi-user.target",
        "ipc ok",
        "OMNE READY",
        "labwc running",
        "wayland display ready",
        "OMNE desktop ready",
        "application launched",
        "agent task completed",
        "model runtime ready",
        "SAFE_MODE",
        "Reached target reboot.target",
        "Linux version 6.8",
        "Reached target multi-user.target",
        "Reached target poweroff.target",
    )
    summary = vm_score.score(
        log,
        run_id="ready",
        elapsed_ms=1000,
        guest_exited=True,
        snapshot_ok=True,
    )

    assert summary["os_ready"] is True
    assert summary["first_failure"] is None
    assert all(check["status"] == "PASS" for check in summary["checks"])


def test_doctor_recovery_pass_counts_as_recovery() -> None:
    log = _log(
        "Linux version 6.8",
        "root=LABEL=OMNE",
        "Reached target local-fs.target",
        "Started systemd-networkd.service",
        "Reached target network.target",
        "virtio_net",
        "Started omne-core.service",
        "Reached target omne.target",
        "Reached target multi-user.target",
        "ipc ok",
        "OMNE READY",
        "labwc running",
        "wayland display ready",
        "OMNE desktop ready",
        "application launched",
        "agent task completed",
        "model runtime ready",
        "[PASS] Recovery",
        "SYSTEM STATUS: READY",
        "Reached target reboot.target",
        "Linux version 6.8",
        "Reached target multi-user.target",
        "Reached target poweroff.target",
    )
    summary = vm_score.score(
        log,
        run_id="doctor",
        elapsed_ms=1000,
        guest_exited=True,
        snapshot_ok=True,
    )

    assert summary["os_ready"] is True
    assert _by_name(summary)["recovery"]["status"] == "PASS"


def test_diag_frames_land_in_their_logs(tmp_path: Path) -> None:
    log = _log(
        "@@omne-diag ipc@@",
        '{"service": "OMNE-core", "status": "ok"}',
        "@@omne-diag end ipc@@",
    )
    summary = vm_score.score(
        log,
        run_id="diag",
        elapsed_ms=1,
        guest_exited=False,
        snapshot_ok=True,
    )
    vm_score.write_artifact(tmp_path, log, summary)
    ipc = (tmp_path / "ipc.log").read_text(encoding="utf-8")

    assert '"status": "ok"' in ipc
    checks = _by_name(summary)
    assert checks["iso-boots"]["status"] == "FAIL"
    assert checks["core-health"]["status"] == "BLOCKED"
    assert checks["ipc"]["status"] == "PASS"
    assert checks["graphical-session"]["status"] == "BLOCKED"
