#!/usr/bin/env python3
"""Score one OMNE VM serial log and write a diagnostic artifact.

A check whose dependency did not pass is BLOCKED. The score does not treat a
missing downstream marker as a separate root cause.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

Graph = tuple[tuple[str, tuple[str, ...]], ...]

GRAPH: Graph = (
    ("iso-boots", ()),
    ("kernel", ("iso-boots",)),
    ("systemd", ("kernel",)),
    ("network", ("systemd",)),
    ("filesystem", ("systemd",)),
    ("omne-service", ("systemd",)),
    ("core-health", ("omne-service",)),
    ("ipc", ("core-health",)),
    ("graphical-session", ("ipc",)),
    ("wayland", ("graphical-session",)),
    ("omne-shell", ("wayland",)),
    ("applications", ("omne-shell",)),
    ("agents", ("applications",)),
    ("models", ("agents",)),
    ("recovery", ("models",)),
    ("reboot", ("systemd",)),
    ("shutdown", ("reboot",)),
)

_GRAPHICAL = re.compile(r"Reached target graphical\.target|labwc running|\[labwc\]")
_RECOVERY = re.compile(r"SAFE_MODE|recovery state RECOVERY")
_DIAG = re.compile(r"@@omne-diag ([a-z]+)@@\n(.*?)@@omne-diag end \1@@", re.DOTALL)

_SLICES: dict[str, tuple[str, ...]] = {
    "boot.log": ("Linux version", "Command line", "Kernel command line"),
    "systemd.log": ("systemd[", "Reached target", "Started ", "Failed "),
    "services.log": ("omne-core", "omne-shell", "omne-boot", "omne-diag", "omne.target"),
    "core.log": ("OMNE READY", "OMNE NOT READY", "OMNE Core"),
    "ipc.log": ("ipc ok", "/health", "OMNE-core"),
    "display.log": ("drm", "dri", "seatd"),
    "shell.log": ("omne-shell", "desktop_marker", "OMNE desktop ready"),
    "applications.log": ("application launched", "application_launch"),
    "agents.log": ("agent task completed", "agent_task"),
    "models.log": ("model runtime ready", '"lifecycle"'),
    "recovery.log": ("SAFE_MODE", "recovery", "RECOVERY"),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="score an OMNE VM serial log")
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--dest", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--elapsed-ms", type=int, default=0)
    parser.add_argument("--guest-exited", action="store_true")
    parser.add_argument("--snapshot-ok", action="store_true")
    args = parser.parse_args(argv)
    text = args.log.read_text(encoding="utf-8", errors="replace") if args.log.is_file() else ""
    summary = score(
        text,
        run_id=args.run_id,
        elapsed_ms=args.elapsed_ms,
        guest_exited=args.guest_exited,
        snapshot_ok=args.snapshot_ok,
    )
    write_artifact(args.dest, text, summary)
    for check in summary["checks"]:
        detail = check["error"] or check["evidence"]
        print(f"{check['status']} {check['name']}: {detail}")
    print(f"first-failure: {summary['first_failure'] or 'none'}")
    print(f"OS-ready: {'yes' if summary['os_ready'] else 'no'}")
    print(f"artifact: {args.dest}")
    return 0 if summary["os_ready"] else 2


def score(
    log: str,
    *,
    run_id: str,
    elapsed_ms: int,
    guest_exited: bool,
    snapshot_ok: bool,
) -> dict[str, Any]:
    raw = {name: _raw(name, log, guest_exited=guest_exited) for name, _deps in GRAPH}
    dependencies = {name: deps for name, deps in GRAPH}
    checks: list[dict[str, Any]] = []
    status_by_name: dict[str, str] = {}
    for name, deps in GRAPH:
        passed, evidence, error = raw[name]
        status = "PASS" if passed else "FAIL"
        exit_code: int | None = 0 if passed else 1
        blocker = _unready(name, status_by_name, dependencies)
        if blocker and not passed:
            status = "BLOCKED"
            exit_code = None
            error = f"{blocker} unavailable"
        status_by_name[name] = status
        checks.append(
            {
                "name": name,
                "status": status,
                "exit_code": exit_code,
                "duration_ms": None,
                "dependencies": list(deps),
                "error": "" if status == "PASS" else error,
                "evidence": evidence,
            }
        )
    first = next((check["name"] for check in checks if check["status"] == "FAIL"), None)
    os_ready = first is None and all(check["status"] == "PASS" for check in checks) and snapshot_ok
    if not snapshot_ok:
        first = first or "snapshot"
    return {
        "run_id": run_id,
        "os_ready": os_ready,
        "first_failure": first,
        "elapsed_ms": elapsed_ms,
        "snapshot": "PASS" if snapshot_ok else "FAIL",
        "guest_exited": guest_exited,
        "checks": checks,
    }


def _unready(
    name: str, status_by_name: dict[str, str], dependencies: dict[str, tuple[str, ...]]
) -> str:
    """Return the failed dependency that blocks this check, walking ancestors."""

    for dep in dependencies.get(name, ()):
        nested = _unready(dep, status_by_name, dependencies)
        state = status_by_name.get(dep)
        if state == "FAIL":
            return dep
        if state != "PASS":
            return nested or dep
        if nested:
            return nested
    return ""


def write_artifact(dest: Path, log: str, summary: dict[str, Any]) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    framed = {match.group(1): match.group(2) for match in _DIAG.finditer(log)}
    for filename, needles in _SLICES.items():
        lines = [line for line in log.splitlines() if any(needle in line for needle in needles)]
        body = "\n".join(lines)
        if body:
            body += "\n"
        section = filename.removesuffix(".log")
        if section in framed:
            body += framed[section]
            if not body.endswith("\n"):
                body += "\n"
        (dest / filename).write_text(body, encoding="utf-8")
    (dest / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _raw(name: str, log: str, *, guest_exited: bool) -> tuple[bool, str, str]:
    if name == "iso-boots":
        passed = "Linux version" in log and "root=LABEL=OMNE" in log
        return _result(
            passed,
            log,
            "root=LABEL=OMNE",
            "the serial log did not show an OMNE kernel command line",
        )
    if name == "kernel":
        passed = "Linux version" in log
        return _result(passed, log, "Linux version", "Linux version was not printed")
    if name == "systemd":
        passed = "Reached target multi-user.target" in log
        return _result(
            passed, log, "Reached target multi-user.target", "multi-user.target was not reached"
        )
    if name == "network":
        needles = (
            "Started systemd-networkd.service",
            "Reached target network.target",
            "virtio_net",
        )
        passed = all(needle in log for needle in needles)
        return _result(passed, log, "virtio_net", "the virtio network did not reach network.target")
    if name == "filesystem":
        passed = "root=LABEL=OMNE" in log and "Reached target local-fs.target" in log
        return _result(
            passed,
            log,
            "Reached target local-fs.target",
            "the root filesystem did not finish mounting",
        )
    if name == "omne-service":
        passed = "Started omne-core.service" in log and "Reached target omne.target" in log
        return _result(passed, log, "Started omne-core.service", "omne.target did not start")
    if name == "core-health":
        passed = "OMNE READY" in log
        return _result(
            passed, log, "OMNE READY", "the boot checklist did not report a healthy core"
        )
    if name == "ipc":
        passed = "ipc ok" in log or ('"status": "ok"' in log and '"service": "OMNE-core"' in log)
        return _result(passed, log, "ipc ok", "the core health endpoint was not reached")
    if name == "graphical-session":
        match = _GRAPHICAL.search(log)
        passed = match is not None
        evidence = match.group(0) if match is not None else ""
        error = "" if passed else "labwc and graphical.target were not started"
        return passed, evidence, error
    if name == "wayland":
        passed = "wayland display ready" in log
        return _result(passed, log, "wayland display ready", "a Wayland display was not recorded")
    if name == "omne-shell":
        passed = "OMNE desktop ready" in log and _GRAPHICAL.search(log) is not None
        return _result(
            passed,
            log,
            "OMNE desktop ready",
            "the shell service started without a visible OMNE desktop",
        )
    if name == "applications":
        passed = "application launched" in log
        return _result(passed, log, "application launched", "no application launch was observed")
    if name == "agents":
        passed = "agent task completed" in log
        return _result(passed, log, "agent task completed", "no safe agent task was observed")
    if name == "models":
        passed = "model runtime ready" in log
        return _result(passed, log, "model runtime ready", "the model runtime did not report ready")
    if name == "recovery":
        match = _RECOVERY.search(log)
        passed = match is not None
        evidence = match.group(0) if match is not None else ""
        error = "" if passed else "recovery mode was not observed"
        return passed, evidence, error
    if name == "reboot":
        passed = (
            log.count("Linux version") >= 2
            and log.count("Reached target multi-user.target") >= 2
            and "Reached target reboot.target" in log
        )
        return _result(passed, log, "Reached target reboot.target", "the guest did not reboot")
    if name == "shutdown":
        passed = "Reached target poweroff.target" in log and guest_exited
        return _result(passed, log, "Reached target poweroff.target", "the guest did not power off")
    return False, "", f"unknown check {name}"


def _result(passed: bool, log: str, needle: str, error: str) -> tuple[bool, str, str]:
    evidence = ""
    for line in log.splitlines():
        if needle in line:
            evidence = line.strip()[:240]
            break
    return passed, evidence, "" if passed else error


if __name__ == "__main__":
    raise SystemExit(main())
