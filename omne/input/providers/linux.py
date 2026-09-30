"""Read published keyboards and mice without opening them.

labwc remains the compositor. This module reads the kernel's device list and
whether a global-shortcut portal file is installed. It does not open an event
node, read a key bitmap, or write a compositor binding.
"""

from __future__ import annotations

import re
from pathlib import Path

from omne.input.model import DeviceKind, DeviceReport, InputDevice, InputRequest

_NAME = re.compile(r'^N: Name="(.*)"\s*$')
_HANDLERS = re.compile(r"^H: Handlers=(.*)$")
_PORTALS = (
    Path("usr/share/dbus-1/interfaces/org.freedesktop.impl.portal.GlobalShortcuts.xml"),
    Path("usr/share/xdg-desktop-portal/interfaces/org.freedesktop.impl.portal.GlobalShortcuts.xml"),
)


class LinuxInputProvider:
    """Report keyboards, mice, and whether labwc or a portal is present."""

    def __init__(self, *, root: Path | None = None) -> None:
        self._root = root if root is not None else Path("/")

    def inspect(self) -> DeviceReport:
        if not self._root.is_dir():
            return DeviceReport(
                provider="linux",
                observed=False,
                compositor="unknown",
                portal="unknown",
                devices_known=False,
                gaps=["linux"],
            )
        devices, known, gap = _devices(self._root)
        gaps = [gap] if gap else []
        return DeviceReport(
            provider="linux",
            observed=True,
            compositor="labwc" if _labwc(self._root) else "unknown",
            portal="global-shortcuts" if _portal(self._root) else "unknown",
            devices=devices,
            devices_known=known,
            gaps=gaps,
        )

    def apply(self, request: InputRequest) -> None:
        del request
        return None


def _labwc(root: Path) -> bool:
    return (root / "usr/bin/labwc").is_file() or (root / "bin/labwc").is_file()


def _portal(root: Path) -> bool:
    return any((root / path).is_file() for path in _PORTALS)


def _devices(root: Path) -> tuple[list[InputDevice], bool, str | None]:
    path = root / "proc" / "bus" / "input" / "devices"
    if not path.exists():
        return [], True, None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [], False, "devices"
    found: list[InputDevice] = []
    seen: dict[str, int] = {}
    for record in text.split("\n\n"):
        name = ""
        handlers = ""
        for line in record.splitlines():
            name_match = _NAME.match(line)
            if name_match is not None:
                name = name_match.group(1).strip()
                continue
            handler_match = _HANDLERS.match(line)
            if handler_match is not None:
                handlers = handler_match.group(1)
        kind = _kind(handlers)
        if kind is None or not name:
            continue
        slug = _slug(name)
        seen[slug] = seen.get(slug, 0) + 1
        suffix = "" if seen[slug] == 1 else f"-{seen[slug]}"
        found.append(InputDevice(id=f"{kind}-{slug}{suffix}", name=name, kind=kind))
    return sorted(found, key=lambda item: item.id), True, None


def _kind(handlers: str) -> DeviceKind | None:
    tokens = set(handlers.split())
    if "kbd" in tokens:
        return "keyboard"
    if any(token.startswith("mouse") for token in tokens):
        return "mouse"
    return None


def _slug(name: str) -> str:
    cleaned = "".join(character.lower() if character.isalnum() else "-" for character in name)
    collapsed = "-".join(part for part in cleaned.split("-") if part)
    return collapsed or "device"
