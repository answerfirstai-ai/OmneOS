#!/usr/bin/env python3
"""Mount OMNE-STATE and report the boot gate.

The first boot finishes setup and asks the init to reboot. A later boot finds
the flag and the verifier and stays on the password gate. This does not format
a disk and does not print the password.
"""

from __future__ import annotations

import ctypes
import os
import stat
import sys
from pathlib import Path

_SITE = Path("/usr/lib/omne/python")
if _SITE.is_dir():
    sys.path.insert(0, str(_SITE))

from omne.firstboot import boot_gate, finish_setup, unlock  # noqa: E402

_MOUNT = Path("/var/lib/omne")
_DATA = _MOUNT / "memory"
_LABEL = b"OMNE-STATE"
_PASSWORD = "correct-horse"
_PAYLOAD = {
    "name": "Ada",
    "password": _PASSWORD,
    "confirm": _PASSWORD,
    "theme": {
        "colors": {
            "accent": "#7eb6d6",
            "desktop": "#10202c",
            "glass": "#101820",
            "ink": "#e7f1f6",
            "muted": "#b7c7d1",
        },
        "type": '"Segoe UI", ui-sans-serif, system-ui, sans-serif',
        "wallpaper": "linear-gradient(180deg, #0c1218 0%, #1a2430 55%, #101418 100%)",
    },
}


def _label(path: Path) -> bytes:
    try:
        with path.open("rb") as handle:
            handle.seek(1144)
            raw = handle.read(16)
    except OSError:
        return b""
    return raw.split(b"\x00", 1)[0]


def _find_state() -> Path | None:
    devices: list[Path] = []
    for pattern in ("vda*", "sda*", "nvme*"):
        devices.extend(Path("/dev").glob(pattern))
    for device in sorted(devices):
        try:
            mode = device.stat().st_mode
        except OSError:
            continue
        if not stat.S_ISBLK(mode):
            continue
        if _label(device) == _LABEL:
            return device
    return None


def _mount(source: Path) -> bool:
    _MOUNT.mkdir(parents=True, exist_ok=True)
    libc = ctypes.CDLL(None, use_errno=True)
    # MS_NOATIME
    result = libc.mount(
        os.fsencode(source),
        os.fsencode(_MOUNT),
        b"ext4",
        ctypes.c_ulong(1024),
        None,
    )
    if result != 0:
        error = ctypes.get_errno()
        print(f"OMNE-STATE did not mount: {os.strerror(error)}", flush=True)
        return False
    return True


def main() -> int:
    device = _find_state()
    if device is None:
        print("OMNE-STATE missing", flush=True)
        return 1
    print(f"OMNE-STATE visible on {device}", flush=True)
    if not _mount(device):
        return 1
    gate = boot_gate(_DATA)
    print(f"OMNE GATE {gate}", flush=True)
    if gate == "setup":
        finish_setup(_DATA, _PAYLOAD)
        os.sync()
        print("OMNE GATE setup stored", flush=True)
        return 10
    print("Password", flush=True)
    if unlock(_DATA, _PASSWORD):
        print("OMNE GATE unlock ok", flush=True)
        os.sync()
        return 0
    print("OMNE GATE unlock failed", flush=True)
    os.sync()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
