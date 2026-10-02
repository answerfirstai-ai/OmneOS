#!/usr/bin/env python3
"""Mount OMNE-STATE and report the boot gate.

The first boot finishes setup and asks the init to reboot. A later boot finds
the flag and the verifier and waits. The password is read from the keyboard on
/dev/tty0. The serial console is a write-only log, so it is not an input.
OMNE_GATE_PASSWORD is an injection for an automated test. The product init does
not set it, and this program does not submit the setup password on its own.
"""

from __future__ import annotations

import ctypes
import os
import select
import stat
import struct
import sys
import termios
import time
from pathlib import Path

_SITE = Path("/usr/lib/omne/python")
if _SITE.is_dir():
    sys.path.insert(0, str(_SITE))

from omne.firstboot import boot_gate, finish_setup, unlock  # noqa: E402

_MOUNT = Path("/var/lib/omne")
_DATA = _MOUNT / "memory"
_LABEL = b"OMNE-STATE"
_PASSWORD = "correct-horse"
_CONSOLE = Path("/dev/tty0")
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

# linux/kd.h — translated mode returns characters, not raw scancodes.
_KDSKBMODE = 0x4B45
_K_XLATE = 0x01


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


_EV_KEY = 1
_KEY_ENTER = 28
_KEY_BACKSPACE = 14
_KEY_MINUS = 12
_LETTERS = {
    16: "q",
    17: "w",
    18: "e",
    19: "r",
    20: "t",
    21: "y",
    22: "u",
    23: "i",
    24: "o",
    25: "p",
    30: "a",
    31: "s",
    32: "d",
    33: "f",
    34: "g",
    35: "h",
    36: "j",
    37: "k",
    38: "l",
    44: "z",
    45: "x",
    46: "c",
    47: "v",
    48: "b",
    49: "n",
    50: "m",
}
_DIGITS = {2: "1", 3: "2", 4: "3", 5: "4", 6: "5", 7: "6", 8: "7", 9: "8", 10: "9", 11: "0"}


def _event_size(blob: bytes) -> int:
    if blob and len(blob) % 24 == 0:
        return 24
    return 16


def _keyboard_fds() -> list[int]:
    """Open keyboard event nodes. Prefer the USB keyboard the test injects into."""

    root = Path("/dev/input")
    if not root.is_dir():
        return []
    ranked: list[tuple[int, int]] = []
    for node in sorted(root.glob("event*")):
        name = ""
        sys_name = Path("/sys/class/input") / node.name / "device" / "name"
        try:
            name = sys_name.read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            name = ""
        if name and "keyboard" not in name and "kbd" not in name:
            continue
        try:
            fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            continue
        rank = 0 if ("usb" in name or "hid" in name or "qemu" in name) else 1
        ranked.append((rank, fd))
    ranked.sort(key=lambda item: item[0])
    if any(rank == 0 for rank, _fd in ranked):
        chosen = [fd for rank, fd in ranked if rank == 0]
        for rank, fd in ranked:
            if rank != 0:
                os.close(fd)
        return chosen
    return [fd for _rank, fd in ranked]


def _read_evdev_password() -> str:
    """Block until Enter on the keyboard. The characters are not printed."""

    fds = _keyboard_fds()
    if not fds:
        raise OSError("no keyboard")
    try:
        entered: list[str] = []
        while True:
            readable, _unused, _errors = select.select(fds, [], [])
            for fd in readable:
                blob = os.read(fd, 4096)
                if not blob:
                    continue
                size = _event_size(blob)
                type_at = 16 if size == 24 else 8
                for offset in range(0, len(blob) - (size - 1), size):
                    kind, code, value = struct.unpack_from("HHi", blob, offset + type_at)
                    if kind != _EV_KEY or value != 1:
                        continue
                    if code == _KEY_ENTER:
                        return "".join(entered)[:128]
                    if code == _KEY_BACKSPACE:
                        if entered:
                            entered.pop()
                        continue
                    character = _LETTERS.get(code)
                    if character is None:
                        character = _DIGITS.get(code)
                    if code == _KEY_MINUS:
                        character = "-"
                    if character and len(entered) < 128:
                        entered.append(character)
    finally:
        for fd in fds:
            os.close(fd)


def _read_tty_password(path: Path) -> str:
    """Block until a line is typed on the virtual console. Nothing is echoed."""

    fd = os.open(path, os.O_RDWR | os.O_NOCTTY)
    try:
        import fcntl

        try:
            fcntl.ioctl(fd, _KDSKBMODE, _K_XLATE)
        except OSError:
            pass
        attrs = termios.tcgetattr(fd)
        quiet = termios.tcgetattr(fd)
        quiet[3] = (quiet[3] | termios.ICANON | termios.ISIG) & ~(termios.ECHO | termios.ECHONL)
        quiet[6][termios.VMIN] = 1
        quiet[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSAFLUSH, quiet)
        try:
            chunks = bytearray()
            while True:
                piece = os.read(fd, 64)
                if not piece:
                    raise OSError("keyboard closed")
                chunks.extend(piece)
                if 10 in chunks or 13 in chunks or len(chunks) > 128:
                    break
        finally:
            termios.tcsetattr(fd, termios.TCSANOW, attrs)
    finally:
        os.close(fd)
    decoded = chunks.decode("utf-8", "replace")
    for separator in ("\r", "\n"):
        if separator in decoded:
            decoded = decoded.split(separator, 1)[0]
            break
    return decoded[:128]


def _entered_password() -> str:
    """The product path blocks. A test may inject OMNE_GATE_PASSWORD."""

    injected = os.environ.get("OMNE_GATE_PASSWORD", "")
    if injected:
        return injected
    while True:
        try:
            return _read_evdev_password()
        except OSError as exc:
            # No event node yet. Do not fall through to the write-only serial line.
            print(f"OMNE GATE keyboard waiting: {exc}", flush=True)
            time.sleep(0.5)


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
    while True:
        print("Password", flush=True)
        entered = _entered_password()
        if unlock(_DATA, entered):
            print("OMNE GATE unlock ok", flush=True)
            os.sync()
            return 0
        print("OMNE GATE unlock failed", flush=True)
        os.sync()


if __name__ == "__main__":
    raise SystemExit(main())
