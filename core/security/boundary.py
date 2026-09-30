"""Fail-closed admission for a profile.

Permission is a separate gate. This one still denies a protected path, a
privileged command, a host signal, an open network, or a claim above the
profile ceiling when permission would have allowed it.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core.permissions.policies import dangerous_command
from core.security.commands import CommandClass, classify_command
from core.security.profiles import ProfileName, profile_for
from omne.processes.protect import refused_program
from omne.storage.classify import classify_path

BoundaryKind = Literal["filesystem", "command", "process", "network", "privilege", "resource"]

_HOST_COMMANDS = frozenset(
    {
        CommandClass.PRIVILEGED,
        CommandClass.DESTRUCTIVE,
        CommandClass.SYSTEM_CONFIGURATION,
        CommandClass.PACKAGE_INSTALL,
        CommandClass.PROCESS_CONTROL,
        CommandClass.NETWORK,
    }
)


class BoundaryDecision(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"


class BoundaryResult(BaseModel):
    """A closed decision. ALLOW is the only path that may continue."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: BoundaryDecision
    reason: str
    profile: str


class BoundaryRequest(BaseModel):
    """One question about a profile."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: str
    kind: BoundaryKind
    workspace: str = ""
    path: str = ""
    argv: list[str] = Field(default_factory=list)
    pid: int | None = None
    host: str = ""
    bind: str = ""
    ram_mb: int = 0
    vram_mb: int = 0
    cpu_threads: int = 0
    pids: int = 0
    file_mb: int = 0


def admit(request: BoundaryRequest) -> BoundaryResult:
    """Decide one request. Any failure is a denial."""

    try:
        return _admit(request)
    except Exception:
        return BoundaryResult(
            decision=BoundaryDecision.DENY,
            reason="security boundary failed closed",
            profile=request.profile,
        )


def resource_denial(
    profile: str,
    *,
    ram_mb: int = 0,
    vram_mb: int = 0,
    cpu_threads: int = 0,
    pids: int = 0,
    file_mb: int = 0,
) -> str | None:
    """Return a denial reason when a claim is above the profile ceiling."""

    result = admit(
        BoundaryRequest(
            profile=profile,
            kind="resource",
            ram_mb=ram_mb,
            vram_mb=vram_mb,
            cpu_threads=cpu_threads,
            pids=pids,
            file_mb=file_mb,
        )
    )
    if result.decision is BoundaryDecision.DENY:
        return result.reason
    return None


def admit_tool(
    *,
    profile: str,
    tool_id: str,
    arguments: dict[str, object],
    workspace: str,
) -> BoundaryResult:
    """Admit one tool call that permission has already allowed."""

    try:
        request = _tool_request(profile, tool_id, arguments, workspace)
    except Exception:
        return BoundaryResult(
            decision=BoundaryDecision.DENY,
            reason="security boundary failed closed",
            profile=profile,
        )
    if request is None:
        return BoundaryResult(
            decision=BoundaryDecision.ALLOW,
            reason="profile allows this tool",
            profile=profile,
        )
    return admit(request)


def _admit(request: BoundaryRequest) -> BoundaryResult:
    selected = profile_for(request.profile)
    if selected is None:
        return _deny(request.profile, "security profile is unknown")
    if selected.name is ProfileName.SYSTEM:
        return _deny(request.profile, "SYSTEM profile is not available to OMNE")
    if request.kind == "filesystem":
        return _filesystem(request)
    if request.kind == "command":
        return _command(request)
    if request.kind == "process":
        return _process(request)
    if request.kind == "network":
        return _network(request)
    if request.kind == "privilege":
        return _deny(request.profile, "privilege changes are denied")
    if request.kind == "resource":
        return _resource(request)
    return _deny(request.profile, "security action is unknown")


def _filesystem(request: BoundaryRequest) -> BoundaryResult:
    if not request.workspace:
        return _deny(request.profile, "workspace is required")
    verdict = classify_path(request.path or ".", workspace=Path(request.workspace))
    if not verdict.allowed:
        return _deny(request.profile, verdict.reason)
    return BoundaryResult(
        decision=BoundaryDecision.ALLOW,
        reason="path stays inside the workspace",
        profile=request.profile,
    )


def _command(request: BoundaryRequest) -> BoundaryResult:
    selected = profile_for(request.profile)
    if selected is None or not selected.host_spawn:
        return _deny(request.profile, "profile cannot spawn a host command")
    if selected.network == "none" and CommandClass.NETWORK in classify_command(request.argv):
        return _deny(request.profile, "profile network is closed")
    reason = dangerous_command(request.argv)
    if reason is not None:
        return _deny(request.profile, reason)
    refusal = refused_program(request.argv)
    if refusal is not None:
        return _deny(request.profile, refusal)
    blocked = _HOST_COMMANDS.intersection(classify_command(request.argv))
    if blocked:
        return _deny(request.profile, "profile does not allow this command")
    if CommandClass.MUTATING in classify_command(request.argv):
        return _deny(request.profile, "profile does not allow a mutating command")
    return BoundaryResult(
        decision=BoundaryDecision.ALLOW,
        reason="command fits the profile",
        profile=request.profile,
    )


def _process(request: BoundaryRequest) -> BoundaryResult:
    if request.pid is not None and request.pid <= 1:
        return _deny(request.profile, "refusing to signal pid 1 or below")
    if request.argv:
        reason = dangerous_command(request.argv)
        if reason is not None:
            return _deny(request.profile, reason)
        refusal = refused_program(request.argv)
        if refusal is not None:
            return _deny(request.profile, refusal)
        blocked = _HOST_COMMANDS.intersection(classify_command(request.argv))
        if blocked:
            return _deny(request.profile, "profile does not allow this command")
    return BoundaryResult(
        decision=BoundaryDecision.ALLOW,
        reason="process record stays inside the profile",
        profile=request.profile,
    )


def _network(request: BoundaryRequest) -> BoundaryResult:
    selected = profile_for(request.profile)
    if selected is None or selected.network == "none":
        return _deny(request.profile, "profile network is closed")
    target = request.bind or request.host
    if selected.network == "loopback" and target not in {"", "localhost", "127.0.0.1", "::1"}:
        return _deny(request.profile, "profile network is loopback only")
    return BoundaryResult(
        decision=BoundaryDecision.ALLOW,
        reason="network target fits the profile",
        profile=request.profile,
    )


def _resource(request: BoundaryRequest) -> BoundaryResult:
    selected = profile_for(request.profile)
    if selected is None:
        return _deny(request.profile, "security profile is unknown")
    ceiling = selected.ceiling
    checks = (
        (request.ram_mb, ceiling.ram_mb, "memory"),
        (request.vram_mb, ceiling.vram_mb, "video memory"),
        (request.cpu_threads, ceiling.cpu_threads, "cpu"),
        (request.pids, ceiling.pids, "process"),
        (request.file_mb, ceiling.file_mb, "file"),
    )
    for asked, limit, name in checks:
        if asked < 0:
            return _deny(request.profile, f"{name} claim is invalid")
        if asked > limit:
            return _deny(request.profile, f"{name} claim exceeds the profile ceiling")
    return BoundaryResult(
        decision=BoundaryDecision.ALLOW,
        reason="claim fits the profile ceiling",
        profile=request.profile,
    )


def _tool_request(
    profile: str,
    tool_id: str,
    arguments: dict[str, object],
    workspace: str,
) -> BoundaryRequest | None:
    if tool_id.startswith("filesystem."):
        raw = arguments.get("path", ".")
        return BoundaryRequest(
            profile=profile,
            kind="filesystem",
            workspace=workspace,
            path=raw if isinstance(raw, str) else "",
        )
    if tool_id == "terminal.execute":
        argv = arguments.get("argv")
        return BoundaryRequest(
            profile=profile,
            kind="command",
            workspace=workspace,
            argv=[str(item) for item in argv] if isinstance(argv, list) else [],
        )
    if tool_id in {"process.stop", "process.restart"}:
        pid = arguments.get("pid")
        return BoundaryRequest(
            profile=profile,
            kind="process",
            pid=pid if isinstance(pid, int) else None,
        )
    if tool_id == "process.start":
        argv = arguments.get("argv")
        return BoundaryRequest(
            profile=profile,
            kind="process",
            argv=[str(item) for item in argv] if isinstance(argv, list) else [],
        )
    if tool_id.startswith("network."):
        host = arguments.get("host", "")
        bind = arguments.get("bind", "")
        host_text = host if isinstance(host, str) else ""
        bind_text = bind if isinstance(bind, str) else ""
        if not host_text and not bind_text:
            return None
        return BoundaryRequest(
            profile=profile,
            kind="network",
            host=host_text,
            bind=bind_text,
        )
    return None


def _deny(profile: str, reason: str) -> BoundaryResult:
    return BoundaryResult(decision=BoundaryDecision.DENY, reason=reason, profile=profile)
