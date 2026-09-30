"""The security boundary denies host access that permission alone might allow."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

from core.compute.requirements import ResourceRequirements
from core.events.bus import EventBus
from core.permissions.audit import AuditLog
from core.permissions.evaluator import PermissionEvaluator
from core.permissions.policies import PermissionDecision, PermissionRequest, PermissionResult
from core.security.boundary import BoundaryDecision, BoundaryRequest, admit, resource_denial
from core.security.profiles import PROFILES, ProfileName
from core.tools.base import ToolContext
from core.tools.gateway import ToolGateway
from core.workers.pool import WorkerLimit, WorkerPool


def test_profiles_cover_every_component() -> None:
    assert set(PROFILES) == set(ProfileName)
    assert PROFILES[ProfileName.SYSTEM].host_spawn is False
    assert PROFILES[ProfileName.WORKER].network == "none"
    assert PROFILES[ProfileName.WORKER].capabilities == ()
    assert PROFILES[ProfileName.CORE].user == "omne"
    assert PROFILES[ProfileName.AGENT].user == "omne-agent"
    assert PROFILES[ProfileName.APPLICATION].user == "omne-app"


def test_unknown_and_system_profiles_are_denied() -> None:
    unknown = admit(BoundaryRequest(profile="root", kind="privilege"))
    system = admit(BoundaryRequest(profile="SYSTEM", kind="filesystem", workspace="/tmp", path="."))

    assert unknown.decision is BoundaryDecision.DENY
    assert unknown.reason == "security profile is unknown"
    assert system.decision is BoundaryDecision.DENY
    assert system.reason == "SYSTEM profile is not available to OMNE"


def test_boundary_fails_closed_when_evaluation_breaks(monkeypatch) -> None:
    def _broken(*_args, **_kwargs):
        raise RuntimeError("classifier bug")

    monkeypatch.setattr("core.security.boundary.classify_path", _broken)
    result = admit(
        BoundaryRequest(profile="WORKER", kind="filesystem", workspace="/tmp", path="notes.txt")
    )

    assert result.decision is BoundaryDecision.DENY
    assert result.reason == "security boundary failed closed"


def test_path_traversal_and_protected_files_are_denied(tmp_path: Path) -> None:
    cases = (
        "../etc/shadow",
        "/etc/shadow",
        "/etc/sudoers",
        "/etc/ssh/ssh_host_key",
        "/etc/omne/OMNE.toml",
        "/boot/grub/grub.cfg",
        "/efi/EFI/omne",
        "/dev/sda",
        "/dev/mem",
        "/root/.ssh/id_rsa",
        "/home/other/secret",
        "/lib/modules/current",
        "/sys/firmware/efi",
    )
    for raw in cases:
        result = admit(
            BoundaryRequest(profile="WORKER", kind="filesystem", workspace=str(tmp_path), path=raw)
        )
        assert result.decision is BoundaryDecision.DENY, raw
        assert result.reason != "path stays inside the workspace"

    allowed = admit(
        BoundaryRequest(
            profile="WORKER", kind="filesystem", workspace=str(tmp_path), path="notes.txt"
        )
    )
    assert allowed.decision is BoundaryDecision.ALLOW


def test_permission_allow_does_not_bypass_a_protected_path(tmp_path: Path) -> None:
    gateway = _permissive_gateway()
    outside = tmp_path.parent / "outside-secret.txt"

    result = gateway.invoke(
        tool_id="filesystem.write",
        arguments={"path": "../outside-secret.txt", "content": "nope"},
        context=_context(tmp_path),
        grants={"filesystem": ["workspace"]},
        environment="testing",
        approved=True,
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error["code"] == "denied"
    assert not outside.exists()


def test_privilege_escalation_is_denied_after_approval(tmp_path: Path) -> None:
    gateway = _permissive_gateway()
    for argv in (
        ["sudo", "true"],
        ["pkexec", "id"],
        ["nsenter", "-t", "1", "-m", "id"],
        ["capsh", "--"],
        ["mount", "/dev/sda", "/mnt"],
    ):
        result = gateway.invoke(
            tool_id="terminal.execute",
            arguments={"argv": argv},
            context=_context(tmp_path),
            grants={"terminal": ["workspace"]},
            environment="testing",
            approved=True,
        )
        assert result.ok is False, argv
        assert result.error is not None
        assert result.error["code"] == "denied"


def test_unauthorized_process_control_is_denied() -> None:
    pid = admit(BoundaryRequest(profile="WORKER", kind="process", pid=1))
    system = admit(BoundaryRequest(profile="WORKER", kind="process", argv=["systemctl", "stop"]))
    shell = admit(BoundaryRequest(profile="WORKER", kind="process", argv=["bash", "-c", "true"]))

    assert pid.decision is BoundaryDecision.DENY
    assert "pid 1" in pid.reason
    assert system.decision is BoundaryDecision.DENY
    assert shell.decision is BoundaryDecision.DENY


def test_unauthorized_network_is_denied() -> None:
    curl = admit(
        BoundaryRequest(profile="WORKER", kind="command", argv=["curl", "https://example.com"])
    )
    remote = admit(BoundaryRequest(profile="WORKER", kind="network", host="1.1.1.1"))
    core = admit(BoundaryRequest(profile="CORE", kind="network", host="8.8.8.8"))
    loopback = admit(BoundaryRequest(profile="CORE", kind="network", bind="127.0.0.1"))

    assert curl.decision is BoundaryDecision.DENY
    assert remote.decision is BoundaryDecision.DENY
    assert core.decision is BoundaryDecision.DENY
    assert loopback.decision is BoundaryDecision.ALLOW


def test_resource_exhaustion_is_denied() -> None:
    memory = resource_denial("WORKER", ram_mb=100_000)
    cpu = resource_denial("WORKER", cpu_threads=64)
    files = resource_denial("WORKER", file_mb=100_000)
    video = resource_denial("MODEL", vram_mb=1_000_000)
    fit = resource_denial("WORKER", ram_mb=4096, cpu_threads=4)

    assert memory is not None
    assert "memory" in memory
    assert cpu is not None
    assert files is not None
    assert video is not None
    assert fit is None
    pool = WorkerPool()
    try:
        pool.start(
            agent_id="coding",
            max_workers=2,
            task_id="task",
            mission_id=None,
            model_id=None,
            trace_id=None,
            resources=ResourceRequirements(ram_mb=100_000, cpu_threads=1),
        )
    except WorkerLimit as exc:
        assert exc.reason == "resources"
    else:
        raise AssertionError("an oversized worker was started")


def test_worker_sandbox_hides_protected_resources_and_keeps_the_host(tmp_path: Path) -> None:
    (tmp_path / "marker.txt").write_text("marker", encoding="utf-8")
    env = _sandbox_env()
    probe = r"""
import os, stat, pathlib, socket
print("null", open("/dev/null", "wb").write(b""))
print("shadow", open("/etc/shadow").read() == "")
print("home", os.listdir("/home"))
print("ssh", os.listdir("/etc/ssh"))
print("firmware", os.listdir("/sys/firmware"))
print("boot", os.listdir("/boot"))
blocks = [
    path.name
    for path in pathlib.Path("/dev").iterdir()
    if stat.S_ISBLK(path.lstat().st_mode)
]
print("blocks", ",".join(blocks))
print("marker", pathlib.Path("marker.txt").read_text().strip())
try:
    socket.socket().connect(("1.1.1.1", 80))
    print("net", "open")
except OSError as exc:
    print("net", exc.errno)
"""
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "core.security.launch",
            str(tmp_path),
            sys.executable,
            "-u",
            "-c",
            probe,
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr
    lines = dict(line.split(" ", 1) for line in completed.stdout.splitlines())
    assert lines["null"] == "0"
    assert lines["shadow"] == "True"
    assert lines["home"] == "[]"
    assert lines["ssh"] == "[]"
    assert lines["firmware"] == "[]"
    assert lines["boot"] == "[]"
    assert lines["blocks"] == ""
    assert lines["marker"] == "marker"
    assert lines["net"] != "open"
    assert "root:" not in completed.stdout
    assert (tmp_path / "marker.txt").read_text(encoding="utf-8") == "marker"
    assert stat.S_ISCHR(os.stat("/dev/null").st_mode)

    denied = subprocess.run(
        [
            sys.executable,
            "-m",
            "core.security.launch",
            str(tmp_path),
            sys.executable,
            "-c",
            "import os; os.unshare(os.CLONE_NEWUSER)",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert denied.returncode != 0


def test_sandbox_rejects_a_limit_above_the_ceiling(tmp_path: Path) -> None:
    env = _sandbox_env()
    env["OMNE_SANDBOX_AS"] = str(9000 * 1024 * 1024)
    completed = subprocess.run(
        [sys.executable, "-m", "core.security.launch", str(tmp_path), "echo", "nope"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )

    assert completed.returncode == 126
    assert completed.stderr.startswith("omne-sandbox:")
    assert "ceiling" in completed.stderr


def test_systemd_units_carry_the_profile_sandbox() -> None:
    root = Path("system/linux")
    core = (root / "omne-core.service").read_text(encoding="utf-8")
    shell = (root / "omne-shell.service").read_text(encoding="utf-8")
    for line in PROFILES[ProfileName.CORE].systemd:
        assert line in core
    for line in PROFILES[ProfileName.SHELL].systemd:
        assert line in shell
    assert "User=omne" in core
    assert "--bind 127.0.0.1 4173" in shell
    sysusers = (root / "omne.sysusers").read_text(encoding="utf-8")
    postinst = (root / "omne-core.postinst").read_text(encoding="utf-8")
    assert "u omne-agent " in sysusers
    assert "u omne-app " in sysusers
    assert "omne-agent" in postinst
    assert "omne-app" in postinst
    assert "grub" not in postinst


def _permissive_gateway() -> ToolGateway:
    from core.tools import build_registry

    def _allow(request: PermissionRequest) -> PermissionResult:
        return PermissionResult(
            decision=PermissionDecision.ALLOW,
            reason="test grant",
            policy_id="test",
        )

    registry = build_registry()
    return ToolGateway(registry, PermissionEvaluator(_allow), AuditLog(), EventBus())


def _context(workspace: Path) -> ToolContext:
    return ToolContext(
        task_id="task",
        agent_id="coding",
        user="local",
        workspace_root=workspace,
        timeout_seconds=5,
        profile="WORKER",
    )


def _sandbox_env() -> dict[str, str]:
    ceiling = PROFILES[ProfileName.WORKER].ceiling
    env = {"PATH": os.environ.get("PATH", "/usr/bin"), "LANG": "C"}
    env["OMNE_SANDBOX_AS"] = str(256 * 1024 * 1024)
    env["OMNE_SANDBOX_CPU"] = str(ceiling.cpu_seconds)
    env["OMNE_SANDBOX_NOFILE"] = str(min(64, ceiling.nofile))
    env["OMNE_SANDBOX_FSIZE"] = str(32 * 1024 * 1024)
    return env
