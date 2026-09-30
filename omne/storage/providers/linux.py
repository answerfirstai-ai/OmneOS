"""Read disks, partitions, and mounts without opening a raw device.

Sizes come from sysfs. Mounts come from ``proc/mounts``. Free and used space
come from ``statvfs`` on the mount directory. This module does not format,
partition, or write a bootloader.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from omne.storage.model import Disk, FilesystemMount, Partition, PartitionRole, StorageState

_DISK = re.compile(r"^(?:sd[a-z]+|vd[a-z]+|hd[a-z]+|nvme\d+n\d+|mmcblk\d+|sr\d+|dm-\d+)$")
_SYSTEM_MOUNTS = {"/", "/usr", "/usr/local", "/var", "/opt"}
_BOOT_MOUNTS = {"/boot", "/boot/efi", "/efi"}
_DEVICE_TYPES = {"devtmpfs", "devpts"}
_BOOT_TYPES = {"efivarfs"}
_ESCAPES = {"040": " ", "011": "\t", "012": "\n", "134": "\\"}


class LinuxStorageProvider:
    """Report the storage layout from one filesystem root."""

    def __init__(self, *, root: Path | None = None) -> None:
        self._root = root if root is not None else Path("/")

    def inspect(self) -> StorageState:
        if not self._root.is_dir():
            return StorageState(provider="linux", observed=False, gaps=["linux"])
        gaps: list[str] = []
        mounts, mount_gap = _mounts(self._root)
        if mount_gap:
            gaps.append(mount_gap)
        disks, partitions, disk_gap = _block(self._root, mounts)
        if disk_gap:
            gaps.append(disk_gap)
        filesystems: list[FilesystemMount] = []
        seen_mounts: set[str] = set()
        for item in mounts:
            if item[1] in seen_mounts:
                continue
            seen_mounts.add(item[1])
            filesystems.append(_filesystem(self._root, item, disks))
        return StorageState(
            provider="linux",
            observed=True,
            disks=disks,
            partitions=partitions,
            filesystems=filesystems,
            gaps=gaps,
        )


def _mounts(root: Path) -> tuple[list[tuple[str, str, str, str]], str | None]:
    path = root / "proc" / "mounts"
    if not path.exists():
        return [], None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [], "mounts"
    found: list[tuple[str, str, str, str]] = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = _unescape(line).split()
        if len(parts) < 4:
            continue
        found.append((parts[0], parts[1], parts[2], parts[3]))
    return found, None


def _block(
    root: Path,
    mounts: list[tuple[str, str, str, str]],
) -> tuple[list[Disk], list[Partition], str | None]:
    directory = root / "sys" / "block"
    if not directory.exists():
        return [], [], None
    try:
        names = sorted(path.name for path in directory.iterdir())
    except OSError:
        return [], [], "disks"
    protected_devices = {
        device for device, mount, fstype, _options in mounts if _protected_mount(mount, fstype)
    }
    disks: list[Disk] = []
    partitions: list[Partition] = []
    for name in names:
        if _DISK.fullmatch(name) is None:
            continue
        path = directory / name
        removable = _flag(path / "removable")
        read_only = _flag(path / "ro")
        children = _partitions(path, name)
        roles = {child: _partition_role(f"/dev/{child}", removable, mounts) for child in children}
        disk_protected = f"/dev/{name}" in protected_devices or any(
            role in {"system", "boot", "device"} for role in roles.values()
        )
        disks.append(
            Disk(
                id=f"disk-{name}",
                name=name,
                device=f"/dev/{name}",
                size_bytes=_size(path / "size"),
                removable=removable,
                read_only=read_only,
                protected=disk_protected or not removable,
                rotational=_rotational(path),
            )
        )
        for child in children:
            role = roles[child]
            partitions.append(
                Partition(
                    id=f"partition-{child}",
                    name=child,
                    disk=name,
                    device=f"/dev/{child}",
                    size_bytes=_size(path / child / "size"),
                    removable=removable,
                    read_only=_flag(path / child / "ro") or read_only,
                    protected=role in {"system", "boot", "device"},
                    role=role,
                )
            )
    return disks, partitions, None


def _filesystem(
    root: Path,
    mount: tuple[str, str, str, str],
    disks: list[Disk],
) -> FilesystemMount:
    device, point, fstype, options = mount
    removable = _device_removable(device, disks)
    role, protected = _mount_role(point, fstype, removable)
    used, free = _space(root, point)
    return FilesystemMount(
        id=point,
        device=device,
        mount=point,
        type=fstype,
        read_only=_read_only(options),
        removable=removable,
        used_bytes=used,
        free_bytes=free,
        role=role,
        protected=protected,
    )


def _partitions(path: Path, name: str) -> list[str]:
    try:
        children = list(path.iterdir())
    except OSError:
        return []
    found = [
        child.name
        for child in children
        if child.name.startswith(name) and child.name != name and child.is_dir()
    ]
    return sorted(found)


def _partition_role(
    device: str,
    removable: bool,
    mounts: list[tuple[str, str, str, str]],
) -> PartitionRole:
    for source, point, fstype, _options in mounts:
        if source != device:
            continue
        role, _protected = _mount_role(point, fstype, removable)
        return role
    if removable:
        return "user"
    return "unknown"


def _mount_role(point: str, fstype: str, removable: bool) -> tuple[PartitionRole, bool]:
    if point in _BOOT_MOUNTS or point.startswith("/boot/") or fstype in _BOOT_TYPES:
        return "boot", True
    if fstype in _DEVICE_TYPES or point == "/dev" or point.startswith("/dev/"):
        return "device", True
    if point in _SYSTEM_MOUNTS or fstype in {"proc", "sysfs"}:
        return "system", True
    if point == "/home" or point.startswith(("/home/", "/mnt/", "/media/", "/run/media/")):
        return "user", False
    if removable:
        return "user", False
    return "unknown", False


def _protected_mount(point: str, fstype: str) -> bool:
    _role, protected = _mount_role(point, fstype, False)
    return protected


def _device_removable(device: str, disks: list[Disk]) -> bool:
    ordered = sorted(disks, key=lambda item: len(item.device), reverse=True)
    for disk in ordered:
        if device == disk.device:
            return disk.removable
        suffix = device[len(disk.device) :] if device.startswith(disk.device) else ""
        numeric = suffix[1:] if suffix.startswith("p") else suffix
        if suffix and numeric.isdecimal():
            return disk.removable
    return False


def _space(root: Path, point: str) -> tuple[int | None, int | None]:
    target = Path(point) if root == Path("/") else root / point.lstrip("/")
    try:
        usage = os.statvfs(target)
    except OSError:
        return None, None
    used = (usage.f_blocks - usage.f_bfree) * usage.f_frsize
    free = usage.f_bavail * usage.f_frsize
    if used < 0 or free < 0:
        return None, None
    return used, free


def _size(path: Path) -> int | None:
    raw = _text(path)
    if raw is None or not raw.isdecimal():
        return None
    return int(raw) * 512


def _flag(path: Path) -> bool:
    return _text(path) == "1"


def _rotational(path: Path) -> bool | None:
    raw = _text(path / "queue" / "rotational")
    if raw == "1":
        return True
    if raw == "0":
        return False
    return None


def _read_only(options: str) -> bool:
    return "ro" in options.split(",")


def _text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip() or None
    except OSError:
        return None


def _unescape(value: str) -> str:
    pieces: list[str] = []
    index = 0
    while index < len(value):
        if value[index] == "\\" and index + 3 < len(value):
            code = value[index + 1 : index + 4]
            if code in _ESCAPES:
                pieces.append(_ESCAPES[code])
                index += 4
                continue
        pieces.append(value[index])
        index += 1
    return "".join(pieces)
