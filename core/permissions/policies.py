"""Default permission policy.

Dangerous host operations are denied. Other high-risk operations require
confirmation in development and testing, and are denied in production.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

TOOL_GRANTS: dict[str, tuple[str, str]] = {
    "filesystem.read": ("filesystem", "workspace"),
    "filesystem.write": ("filesystem", "workspace"),
    "filesystem.search": ("filesystem", "workspace"),
    "filesystem.create_directory": ("filesystem", "workspace"),
    "terminal.execute": ("terminal", "workspace"),
    "process.list": ("process", "list"),
    "process.start": ("process", "start"),
    "process.stop": ("process", "signal"),
    "system.cpu": ("system", "read"),
    "system.memory": ("system", "read"),
    "system.gpu": ("system", "read"),
    "system.disk": ("system", "read"),
    "system.network": ("system", "read"),
    "git.status": ("git", "read"),
    "git.diff": ("git", "read"),
    "git.branch": ("git", "read"),
    "git.commit": ("git", "commit"),
    "browser.open": ("browser", "navigate"),
    "browser.search": ("browser", "navigate"),
    "voice.transmit": ("voice", "transmit"),
}

HIGH_RISK_TOOLS = frozenset({"terminal.execute", "process.start", "process.stop", "git.commit"})
FILESYSTEM_TOOLS = frozenset(
    {
        "filesystem.read",
        "filesystem.write",
        "filesystem.search",
        "filesystem.create_directory",
    }
)
_ALWAYS_DENY_COMMANDS = frozenset(
    {
        "sudo",
        "su",
        "doas",
        "pkexec",
        "shutdown",
        "reboot",
        "poweroff",
        "halt",
        "mkfs",
        "mkfs.ext4",
        "fdisk",
        "parted",
        "dd",
        "iptables",
        "nft",
        "ufw",
        "efibootmgr",
        "grub-install",
        "update-grub",
    }
)
_PACKAGE_MANAGERS = frozenset({"apt", "apt-get", "dnf", "yum", "pacman", "apk"})


class PermissionDecision(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    CONFIRM = "CONFIRM"


class PermissionRequest(BaseModel):
    """A request to run one tool call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_id: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    grants: dict[str, list[str]] = Field(default_factory=dict)
    environment: str
    workspace_root: str
    task_id: str | None = None
    agent_id: str | None = None
    user: str = "local"


class PermissionResult(BaseModel):
    """A deterministic allow, deny, or confirm decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: PermissionDecision
    reason: str
    policy_id: str


def decide(request: PermissionRequest) -> PermissionResult:
    """Evaluate one request. Callers should use the evaluator, which fails closed."""

    grant = TOOL_GRANTS.get(request.tool_id)
    if grant is None:
        return _deny(f"tool is not registered for permissions: {request.tool_id}")
    domain, value = grant
    if value not in request.grants.get(domain, []):
        return _deny(f"agent grant {domain}:{value} is missing")

    if request.tool_id in FILESYSTEM_TOOLS:
        path_decision = _filesystem_decision(request)
        if path_decision is not None:
            return path_decision
    if request.tool_id == "terminal.execute":
        danger = dangerous_command(request.arguments.get("argv"))
        if danger is not None:
            return _deny(danger)
    if request.tool_id == "process.start":
        danger = dangerous_command(request.arguments.get("argv"))
        if danger is not None:
            return _deny(danger)
    if request.tool_id == "process.stop":
        pid = request.arguments.get("pid")
        if isinstance(pid, int) and pid <= 1:
            return _deny("refusing to signal pid 1 or below")
    if request.tool_id == "voice.transmit":
        return _deny("audio transmission is denied unless a later policy explicitly allows it")
    if request.tool_id in HIGH_RISK_TOOLS or _is_package_install(request):
        if request.environment == "production":
            return _deny("high-risk operation is denied in production")
        return PermissionResult(
            decision=PermissionDecision.CONFIRM,
            reason="high-risk operation requires confirmation",
            policy_id="default",
        )
    return PermissionResult(
        decision=PermissionDecision.ALLOW, reason="granted by policy", policy_id="default"
    )


def dangerous_command(argv: object) -> str | None:
    """Return a denial reason for commands that must not run."""

    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
        return "command must be a non-empty list of strings"
    words = [str(item) for item in argv]
    if any("\x00" in word for word in words):
        return "command contains a null byte"
    base = Path(words[0]).name.lower()
    joined = " ".join(words).lower()
    if base in _ALWAYS_DENY_COMMANDS:
        return f"command {base} is denied"
    if base in {"rm", "rmdir"} and _recursive_removal(words):
        return "recursive deletion is denied"
    if "rm -rf" in joined or "rm -fr" in joined:
        return "recursive deletion is denied"
    if any(token in joined for token in ("/boot", "/etc/sudoers", "/etc/shadow")):
        return "boot or security configuration changes are denied"
    return None


def _filesystem_decision(request: PermissionRequest) -> PermissionResult | None:
    raw = request.arguments.get("path", ".")
    if not isinstance(raw, str) or not raw:
        return _deny("filesystem path must be a non-empty string")
    try:
        resolved = resolve_inside_workspace(Path(request.workspace_root), raw)
    except ValueError as exc:
        return _deny(str(exc))
    if ".git" in resolved.parts:
        return _deny("filesystem access inside .git is denied")
    return None


def resolve_inside_workspace(workspace: Path, raw: str) -> Path:
    """Resolve ``raw`` and require it to stay inside ``workspace``."""

    root = workspace.resolve()
    candidate = Path(raw)
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("path is outside the approved workspace")
    return resolved


def _recursive_removal(argv: list[str]) -> bool:
    flags = {item for item in argv[1:] if item.startswith("-")}
    recursive = any(set(flag[1:]) & {"r", "R"} for flag in flags if not flag.startswith("--"))
    recursive = recursive or "--recursive" in argv
    return recursive


def _is_package_install(request: PermissionRequest) -> bool:
    if request.tool_id not in {"terminal.execute", "process.start"}:
        return False
    argv = request.arguments.get("argv")
    if not isinstance(argv, list) or not argv or not isinstance(argv[0], str):
        return False
    base = Path(argv[0]).name.lower()
    if base in _PACKAGE_MANAGERS:
        return True
    return base in {"pip", "pip3"} and "install" in argv


def _deny(reason: str) -> PermissionResult:
    return PermissionResult(decision=PermissionDecision.DENY, reason=reason, policy_id="default")
