"""Classify a path before a filesystem tool may use it.

Protected locations stay protected even when the workspace is the filesystem root.
The walk does not open a block device.
"""

from __future__ import annotations

import os
import stat
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

_SYSTEM_PREFIXES = (
    "/etc",
    "/proc",
    "/sys",
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
    "/lib64",
    "/opt",
    "/run",
)
_BOOT_PREFIXES = ("/boot", "/efi")
_HOP_LIMIT = 8


class PathClass(StrEnum):
    """Where a path sits on the machine."""

    USER = "USER"
    OMNE = "OMNE"
    SYSTEM = "SYSTEM"
    BOOT = "BOOT"
    DEVICE = "DEVICE"


class PathVerdict(BaseModel):
    """The class of one path and whether a filesystem tool may use it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    classification: PathClass
    allowed: bool
    reason: str
    resolved: str = Field(min_length=1)


def classify_path(
    raw: str,
    *,
    workspace: Path,
    omne_roots: tuple[Path, ...] = (),
) -> PathVerdict:
    """Resolve ``raw`` against ``workspace`` and classify the result.

    OMNE roots default to the workspace. A root that is itself a protected
    location does not grant access to that location.
    """

    if not raw or "\x00" in raw:
        return _verdict(PathClass.SYSTEM, False, "path must be a non-empty string", raw or "/")
    roots = tuple(path.resolve() for path in (workspace, *omne_roots))
    workspace_root = roots[0]
    usable = tuple(path for path in roots if _protected(path) is None)
    candidate = Path(raw)
    start = candidate if candidate.is_absolute() else workspace_root / candidate
    resolved, problem = _walk(start)
    if problem == "inaccessible":
        lexical = _lexical(start)
        return _verdict(
            _class_of(lexical, usable), False, "path is inaccessible", lexical.as_posix()
        )
    if problem == "loop":
        return _verdict(PathClass.SYSTEM, False, "path is inaccessible", start.as_posix())
    if resolved is None:
        return _verdict(PathClass.SYSTEM, False, "path is inaccessible", start.as_posix())
    kind = _class_of(resolved, usable)
    if kind is PathClass.DEVICE:
        return _verdict(kind, False, "raw device access is denied", resolved.as_posix())
    if kind is PathClass.BOOT:
        return _verdict(kind, False, "boot location is protected", resolved.as_posix())
    if kind is PathClass.SYSTEM:
        return _verdict(kind, False, "protected system location", resolved.as_posix())
    if kind is not PathClass.OMNE:
        if _inside(resolved, workspace_root) and _protected(workspace_root) is not None:
            return _verdict(kind, False, "protected system location", resolved.as_posix())
        return _verdict(kind, False, "path is outside the approved workspace", resolved.as_posix())
    if not _can_stat(resolved):
        return _verdict(kind, False, "path is inaccessible", resolved.as_posix())
    return _verdict(kind, True, "omne workspace", resolved.as_posix())


def _walk(start: Path) -> tuple[Path | None, str | None]:
    current = Path(start.anchor) if start.is_absolute() else Path.cwd()
    hops = 0
    pending = list(start.parts[1:] if start.is_absolute() else start.parts)
    while pending:
        part = pending.pop(0)
        if part in ("", "."):
            continue
        if part == "..":
            current = current.parent if current.parent != current else current
            continue
        nxt = current / part
        try:
            is_link = nxt.is_symlink()
        except OSError:
            return None, "inaccessible"
        if is_link:
            hops += 1
            if hops > _HOP_LIMIT:
                return None, "loop"
            try:
                target = Path(os.readlink(nxt))
            except OSError:
                return None, "inaccessible"
            if not target.is_absolute():
                target = current / target
            pending = list(target.parts[1:] if target.is_absolute() else target.parts) + pending
            current = Path(target.anchor) if target.is_absolute() else current
            continue
        current = nxt
    return current, None


def _class_of(path: Path, omne_roots: tuple[Path, ...]) -> PathClass:
    protected = _protected(path)
    if protected is not None:
        return protected
    for root in omne_roots:
        if path == root or root in path.parents:
            return PathClass.OMNE
    return PathClass.USER


def _protected(path: Path) -> PathClass | None:
    text = path.as_posix() or "/"
    if _is_device(path, text):
        return PathClass.DEVICE
    if text == "/boot" or text.startswith("/boot/") or text == "/efi" or text.startswith("/efi/"):
        return PathClass.BOOT
    if text == "/":
        return PathClass.SYSTEM
    for prefix in _SYSTEM_PREFIXES:
        if text == prefix or text.startswith(prefix + "/"):
            return PathClass.SYSTEM
    for prefix in _BOOT_PREFIXES:
        if text == prefix or text.startswith(prefix + "/"):
            return PathClass.BOOT
    return None


def _is_device(path: Path, text: str) -> bool:
    if text == "/dev" or text.startswith("/dev/"):
        return True
    try:
        mode = path.lstat().st_mode
    except OSError:
        return False
    return stat.S_ISBLK(mode)


def _can_stat(path: Path) -> bool:
    current = path
    while True:
        try:
            current.lstat()
        except FileNotFoundError:
            if current.parent == current:
                return False
            current = current.parent
            continue
        except OSError:
            return False
        return True


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _lexical(path: Path) -> Path:
    return Path(os.path.normpath(path.as_posix()))


def _verdict(kind: PathClass, allowed: bool, reason: str, resolved: str) -> PathVerdict:
    text = resolved if resolved.startswith("/") else "/" + resolved
    return PathVerdict(classification=kind, allowed=allowed, reason=reason, resolved=text)
