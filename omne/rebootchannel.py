"""Guest side of the virtual reboot channel.

The host writes the word reboot. A missing channel is a physical machine, and
this process exits without rebooting. An empty read is not a request: the
port stays open until the host connects.
"""

from __future__ import annotations

import os
import select
import time

PORT = "/dev/virtio-ports/omne-reboot"


def command_from(pending: bytes, chunk: bytes) -> tuple[bytes, str | None]:
    """Return leftover bytes and a command when one full line has arrived."""

    pending += chunk
    while b"\n" in pending:
        raw, pending = pending.split(b"\n", 1)
        word = raw.strip().decode("utf-8", "replace")
        if word == "reboot":
            return pending, "reboot"
    return pending, None


def main() -> int:
    """Block on the virtio port and reboot only after the word reboot."""

    deadline = time.monotonic() + 10
    while not os.path.exists(PORT) and time.monotonic() < deadline:
        time.sleep(0.2)
    if not os.path.exists(PORT):
        return 0
    while os.path.exists(PORT):
        try:
            fd = os.open(PORT, os.O_RDONLY)
        except OSError:
            time.sleep(0.2)
            continue
        pending = b""
        try:
            while os.path.exists(PORT):
                ready, _, _ = select.select([fd], [], [], 0.5)
                if not ready:
                    continue
                chunk = os.read(fd, 256)
                if not chunk:
                    time.sleep(0.2)
                    continue
                pending, command = command_from(pending, chunk)
                if command == "reboot":
                    print("reboot requested", flush=True)
                    os.execv("/usr/bin/systemctl", ["systemctl", "reboot"])
        finally:
            os.close(fd)
    return 0
