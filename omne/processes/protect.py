"""Protected processes cannot be started, stopped, or restarted.

The classes are pid 1, kernel threads, system services, OMNE Core, security
services, and the active desktop session.
"""

from __future__ import annotations

from pathlib import Path

from omne.processes.model import Protection

SHELLS = frozenset({"sh", "bash", "dash", "zsh", "fish", "ksh"})
KERNEL_NAMES = frozenset(
    {
        "kthreadd",
        "ksoftirqd",
        "kworker",
        "migration",
        "rcu_sched",
        "rcu_preempt",
        "watchdog",
        "idle",
    }
)
SYSTEM_SERVICES = frozenset(
    {
        "systemd",
        "systemd-journald",
        "systemd-logind",
        "systemd-udevd",
        "systemd-networkd",
        "dbus-daemon",
        "cron",
        "crond",
        "atd",
        "rsyslogd",
    }
)
SECURITY_SERVICES = frozenset(
    {
        "sshd",
        "polkitd",
        "auditd",
        "firewalld",
        "fail2ban-server",
        "sudo",
        "pkexec",
    }
)
DESKTOP_SESSION = frozenset(
    {
        "labwc",
        "sway",
        "weston",
        "gnome-shell",
        "gnome-session",
        "Xorg",
        "Xwayland",
        "mutter",
        "kwin_wayland",
        "kwin_x11",
        "xfwm4",
        "gdm",
        "gdm3",
        "lightdm",
        "sddm",
        "plasmashell",
    }
)
_REASONS = {
    "pid1": "pid 1 is protected",
    "kernel": "kernel process is protected",
    "system_service": "system service is protected",
    "omne_core": "OMNE Core is protected",
    "security": "security service is protected",
    "desktop_session": "desktop session is protected",
}


def protection_for(
    *,
    pid: int,
    parent_pid: int | None,
    name: str,
    core_pid: int | None,
) -> Protection | None:
    """Return the protection class for one process, or none when it is ordinary."""

    base = _base(name)
    if pid == 1:
        return "pid1"
    if pid == 2 or parent_pid == 2 or _kernel_name(base):
        return "kernel"
    if (core_pid is not None and pid == core_pid) or base == "OMNE":
        return "omne_core"
    if base in SECURITY_SERVICES:
        return "security"
    if base in DESKTOP_SESSION:
        return "desktop_session"
    if base in SYSTEM_SERVICES:
        return "system_service"
    return None


def protection_reason(kind: Protection) -> str:
    """Return the denial reason for a protection class."""

    return _REASONS[kind]


def refused_program(argv: object) -> str | None:
    """Return a denial when argv would start a shell or a protected program."""

    if not isinstance(argv, list) or not argv or not isinstance(argv[0], str):
        return None
    name = _base(argv[0])
    if name in SHELLS:
        return "process start does not accept a shell"
    kind = protection_for(pid=0, parent_pid=None, name=name, core_pid=None)
    if name == "systemd" or name == "init":
        return "protected program cannot be started"
    if kind is not None and kind != "pid1":
        return "protected program cannot be started"
    return None


def _base(name: str) -> str:
    return Path(name).name


def _kernel_name(name: str) -> bool:
    if name in KERNEL_NAMES:
        return True
    return name.startswith(("kworker", "ksoftirqd", "migration", "rcu_"))
