"""Capability classes for host commands.

Classification does not replace the deny list. Callers still deny dangerous
commands before they look at the class.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path


class CommandClass(StrEnum):
    READ_ONLY = "READ_ONLY"
    MUTATING = "MUTATING"
    PRIVILEGED = "PRIVILEGED"
    DESTRUCTIVE = "DESTRUCTIVE"
    NETWORK = "NETWORK"
    PACKAGE_INSTALL = "PACKAGE_INSTALL"
    PROCESS_CONTROL = "PROCESS_CONTROL"
    SYSTEM_CONFIGURATION = "SYSTEM_CONFIGURATION"


_READ_ONLY = frozenset(
    {
        "ls",
        "cat",
        "pwd",
        "echo",
        "rg",
        "grep",
        "find",
        "stat",
        "wc",
        "head",
        "tail",
        "git",
    }
)
_PACKAGE = frozenset({"apt", "apt-get", "dnf", "yum", "pacman", "apk", "npm", "pip", "pip3"})
_NETWORK = frozenset({"curl", "wget", "ssh", "scp", "ping", "dig", "nslookup"})
_PROCESS = frozenset({"kill", "pkill", "killall", "systemctl", "service"})
_CONFIG = frozenset({"systemctl", "service", "sysctl", "hostnamectl"})
_DESTRUCTIVE = frozenset({"rm", "rmdir", "mkfs", "dd", "shred"})


def classify_command(argv: object) -> frozenset[CommandClass]:
    """Return the capability classes for one argv list."""

    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
        return frozenset({CommandClass.MUTATING})
    base = Path(argv[0]).name.lower()
    words = [str(item).lower() for item in argv]
    classes: set[CommandClass] = set()
    if base in _PACKAGE or (len(words) >= 2 and words[1] in {"install", "remove", "uninstall"}):
        classes.update({CommandClass.PACKAGE_INSTALL, CommandClass.NETWORK, CommandClass.MUTATING})
    if base in _NETWORK:
        classes.add(CommandClass.NETWORK)
        classes.add(CommandClass.MUTATING)
    if base in _PROCESS:
        classes.add(CommandClass.PROCESS_CONTROL)
    if base in _CONFIG:
        classes.add(CommandClass.SYSTEM_CONFIGURATION)
    if base in _DESTRUCTIVE or any(flag in words for flag in ("-rf", "-fr")):
        classes.add(CommandClass.DESTRUCTIVE)
        classes.add(CommandClass.MUTATING)
    if base in {"sudo", "su", "doas", "pkexec"}:
        classes.add(CommandClass.PRIVILEGED)
        classes.add(CommandClass.MUTATING)
    if base == "git" and len(words) > 1 and words[1] in {"status", "diff", "branch", "log", "show"}:
        return frozenset({CommandClass.READ_ONLY})
    if base == "git":
        classes.add(CommandClass.MUTATING)
    if not classes and base in _READ_ONLY:
        return frozenset({CommandClass.READ_ONLY})
    if not classes:
        classes.add(CommandClass.MUTATING)
    return frozenset(classes)


def is_destructive(argv: object) -> bool:
    classes = classify_command(argv)
    return CommandClass.DESTRUCTIVE in classes or CommandClass.PRIVILEGED in classes
