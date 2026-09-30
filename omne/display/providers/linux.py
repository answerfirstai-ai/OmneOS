"""Linux display diagnostics for the labwc Wayland compositor.

labwc is the selected compositor. This module reads DRM, render nodes, and
input devices. It does not execute labwc and it does not open a session.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import sys
from collections.abc import Mapping
from pathlib import Path

from omne.display.model import Display, FullscreenState, Monitor, Presence, SessionState, Surface
from omne.display.providers.mock import DESKTOP_URI

_MODE = re.compile(r"^(\d+)x(\d+)(?:@(\d+(?:\.\d+)?))?$")
_CARD = re.compile(r"^card\d+$")
_RENDER = re.compile(r"^renderD\d+$")


class LinuxDisplayProvider:
    """Read the local Linux graphics stack and report labwc readiness."""

    def __init__(
        self,
        *,
        root: Path | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._root = root or Path("/")
        if environ is None and self._root == Path("/"):
            self._environ = dict(os.environ)
        else:
            self._environ = dict(environ or {})

    def diagnose(self) -> Display:
        linux = sys.platform.startswith("linux")
        drm, gpu = self._devices()
        monitors = self._monitors()
        compositor_present = self._labwc_present()
        wayland, session = self._session()
        entry = self._input()
        missing = _missing(
            linux=linux,
            drm=drm,
            gpu=gpu,
            compositor_present=compositor_present,
            monitors=monitors,
            entry=entry,
        )
        # labwc launches on a DRM card with pixman when the device has no render node.
        launch = [item for item in missing if item != "render node"]
        return Display(
            provider="labwc",
            platform=sys.platform,
            linux=linux,
            wayland=wayland,
            session=session,
            drm=drm,
            gpu_acceleration=gpu,
            compositor="labwc" if compositor_present else "none",
            compositor_present=compositor_present,
            input=entry,
            monitors=monitors,
            windows=[],
            windows_known=False,
            workspaces=[],
            fullscreen=FullscreenState(known=False, active=False),
            surface=Surface(
                id="omne-desktop",
                role="desktop",
                active=False,
                fullscreen=False,
                uri=DESKTOP_URI,
            ),
            can_launch=not launch,
            missing=missing,
        )

    def _devices(self) -> tuple[Presence, Presence]:
        dri = self._root / "dev" / "dri"
        if not dri.exists():
            drm: Presence = "present" if self._sysfs_cards() else "absent"
            return drm, "absent"
        try:
            names = [path.name for path in dri.iterdir()]
        except OSError:
            return "unavailable", "unavailable"
        has_card = any(_CARD.match(name) for name in names) or bool(self._sysfs_cards())
        has_render = any(_RENDER.match(name) for name in names)
        card: Presence = "present" if has_card else "absent"
        gpu: Presence = "present" if has_render else "absent"
        return card, gpu

    def _sysfs_cards(self) -> list[str]:
        drm = self._root / "sys" / "class" / "drm"
        if not drm.is_dir():
            return []
        try:
            names = [path.name for path in drm.iterdir()]
        except OSError:
            return []
        return [name for name in names if _CARD.match(name)]

    def _monitors(self) -> list[Monitor]:
        drm = self._root / "sys" / "class" / "drm"
        if not drm.is_dir():
            return []
        try:
            connectors = sorted(
                path for path in drm.iterdir() if path.name.startswith("card") and "-" in path.name
            )
        except OSError:
            return []
        found: list[Monitor] = []
        enabled: list[str] = []
        for path in connectors:
            status = _read(path / "status")
            if status != "connected":
                continue
            width, height, refresh = _preferred_mode(path / "modes")
            found.append(
                Monitor(
                    id=path.name,
                    name=path.name.split("-", 1)[1],
                    connected=True,
                    width=width,
                    height=height,
                    refresh_hz=refresh,
                    primary=False,
                )
            )
            if _read(path / "enabled") == "enabled":
                enabled.append(path.name)
        if len(enabled) == 1:
            found = [item.model_copy(update={"primary": item.id == enabled[0]}) for item in found]
        return found

    def _labwc_present(self) -> bool:
        candidate = self._root / "usr" / "bin" / "labwc"
        if candidate.is_file():
            return True
        if self._root == Path("/"):
            return shutil.which("labwc") is not None
        return False

    def _session(self) -> tuple[bool, SessionState]:
        runtime = self._environ.get("XDG_RUNTIME_DIR", "").strip()
        display = self._environ.get("WAYLAND_DISPLAY", "").strip()
        if not runtime or not display:
            return False, "not_running"
        socket_path = Path(runtime) / display
        try:
            mode = socket_path.lstat().st_mode
        except OSError:
            return False, "not_running"
        if stat.S_ISSOCK(mode):
            return True, "running"
        return False, "not_running"

    def _input(self) -> Presence:
        directory = self._root / "dev" / "input"
        if not directory.exists():
            return "absent"
        try:
            names = [path.name for path in directory.iterdir()]
        except OSError:
            return "unavailable"
        if any(name.startswith("event") for name in names):
            return "present"
        return "absent"


def _missing(
    *,
    linux: bool,
    drm: str,
    gpu: str,
    compositor_present: bool,
    monitors: list[Monitor],
    entry: Presence,
) -> list[str]:
    missing: list[str] = []
    if not linux:
        missing.append("linux")
    if drm != "present":
        missing.append("drm card")
    if gpu != "present":
        missing.append("render node")
    if not compositor_present:
        missing.append("labwc")
    if not monitors:
        missing.append("connected monitor")
    elif any(item.width is None or item.height is None for item in monitors):
        missing.append("display mode")
    if entry != "present":
        missing.append("input device")
    return missing


def _preferred_mode(path: Path) -> tuple[int | None, int | None, float | None]:
    text = _read(path)
    if text is None:
        return None, None, None
    for line in text.splitlines():
        match = _MODE.match(line.strip())
        if match is None:
            continue
        refresh = float(match.group(3)) if match.group(3) is not None else None
        return int(match.group(1)), int(match.group(2)), refresh
    return None, None, None


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
