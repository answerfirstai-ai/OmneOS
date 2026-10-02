"""Live USB state under a volatile /var.

``systemd.volatile=state`` puts ``/var`` on a tmpfs, so a file written there
disappears on reboot. The ISO also carries an ext4 partition labeled
``OMNE-STATE`` and mounts it at ``/var/lib/omne`` after that tmpfs exists.
The setup flag and the password verifier live on that filesystem.

This module models that mount. It does not format a disk or open a block
device. A real boot still depends on the image, udev, and the firmware
exposing the appended partition.
"""

from __future__ import annotations

import shutil
from pathlib import Path

STATE_LABEL = "OMNE-STATE"
STATE_MOUNT = Path("/var/lib/omne")
VOLATILE_OPTION = "systemd.volatile=state"

_BLOCKED = (
    Path("/"),
    Path("/bin"),
    Path("/boot"),
    Path("/dev"),
    Path("/efi"),
    Path("/etc"),
    Path("/home"),
    Path("/lib"),
    Path("/lib64"),
    Path("/opt"),
    Path("/proc"),
    Path("/root"),
    Path("/run"),
    Path("/sbin"),
    Path("/sys"),
    Path("/usr"),
    Path("/var"),
)


class PersistPathError(Exception):
    """A simulated reboot was pointed at a real system directory."""

    def __init__(self) -> None:
        super().__init__("refusing to wipe a system path")


def volatile_discards(path: Path) -> bool:
    """True when ``systemd.volatile=state`` drops this path on reboot.

    ``/var/lib/omne`` is the persistent mount, so it is not discarded.
    """

    resolved = path if path.is_absolute() else Path("/var") / path
    if resolved == STATE_MOUNT or STATE_MOUNT in resolved.parents:
        return False
    return resolved == Path("/var") or Path("/var") in resolved.parents


def attach_state(volatile_var: Path, persistent: Path) -> Path:
    """Wipe a volatile ``/var`` and mount ``persistent`` at ``lib/omne``.

    ``persistent`` is the ``OMNE-STATE`` filesystem. The returned path is the
    mount the next boot reads. The persistent tree itself is not deleted.
    """

    volatile = _writable(volatile_var)
    store = _writable(persistent)
    if volatile.exists():
        shutil.rmtree(volatile)
    target = volatile / "lib" / "omne"
    target.parent.mkdir(parents=True)
    target.symlink_to(store, target_is_directory=True)
    (target / "memory").mkdir(exist_ok=True)
    (target / "workspace").mkdir(exist_ok=True)
    return target


def _writable(path: Path) -> Path:
    resolved = path.resolve()
    if resolved in _BLOCKED:
        raise PersistPathError()
    for root in _BLOCKED:
        if root == Path("/"):
            continue
        if root in resolved.parents:
            raise PersistPathError()
    return resolved
