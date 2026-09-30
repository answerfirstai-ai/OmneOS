"""Read installed browsers without starting them and without importing Playwright.

Desktop entries identify browser applications. Processes are matched by program
name. Automation, research retrieval, and rendering stay unavailable.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from omne.applications.desktop import parse_desktop_file
from omne.browser.capabilities import (
    ENGINE_DEPENDENCY,
    ENGINE_NOTE,
    HOST_NOT_CONTROLLED,
    LAYER_SPECS,
    RENDER_NOT_INSTALLED,
    RESEARCH_NOT_INSTALLED,
)
from omne.browser.model import (
    BrowserOutcome,
    BrowserProcess,
    BrowserRequest,
    BrowserState,
    LayerStatus,
)

_APP_DIRS = (
    Path("usr/share/applications"),
    Path("usr/local/share/applications"),
)
_KNOWN = frozenset(
    {
        "brave",
        "brave-browser",
        "chrome",
        "chromium",
        "chromium-browser",
        "firefox",
        "firefox-esr",
        "google-chrome",
        "google-chrome-stable",
        "microsoft-edge",
        "microsoft-edge-stable",
    }
)


class LinuxBrowserProvider:
    """Report browser applications from one filesystem root."""

    def __init__(self, *, root: Path | None = None) -> None:
        self._root = root if root is not None else Path("/")

    def status(self) -> BrowserState:
        if not self._root.is_dir():
            return BrowserState(
                provider="linux",
                observed=False,
                layers=_layers(application=False, present=False),
                capabilities=list(LAYER_SPECS),
                gaps=["browser", ENGINE_NOTE],
            )
        applications = _applications(self._root)
        present = _dependency_present()
        processes = _processes(self._root, set(applications) | _KNOWN)
        gaps = [ENGINE_NOTE]
        if not applications:
            gaps.append("browser-application")
        return BrowserState(
            provider="linux",
            observed=True,
            layers=_layers(application=bool(applications), present=present),
            capabilities=list(LAYER_SPECS),
            engine_dependency=ENGINE_DEPENDENCY,
            dependency_present=present,
            applications=applications,
            processes=processes,
            gaps=gaps,
        )

    def apply(self, request: BrowserRequest) -> BrowserOutcome:
        reason = HOST_NOT_CONTROLLED
        if request.action == "research":
            reason = RESEARCH_NOT_INSTALLED
        elif request.action == "screenshot":
            reason = RENDER_NOT_INSTALLED
        return BrowserOutcome(applied=False, reason=reason, state=self.status())


def _applications(root: Path) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for relative in _APP_DIRS:
        directory = root / relative
        if not directory.is_dir():
            continue
        try:
            paths = sorted(directory.glob("*.desktop"))
        except OSError:
            return []
        for path in paths:
            if path.name in seen:
                continue
            seen.add(path.name)
            app = parse_desktop_file(path)
            if app is None or not app.launchable or app.executable is None:
                continue
            categories = {item.casefold() for item in app.categories}
            program = Path(app.executable).name
            if "webbrowser" not in categories and program not in _KNOWN and app.id not in _KNOWN:
                continue
            found.append(app.id)
    return sorted(set(found))


def _processes(root: Path, names: set[str]) -> list[BrowserProcess]:
    proc = root / "proc"
    found: list[BrowserProcess] = []
    if not proc.is_dir():
        return found
    try:
        entries = list(proc.iterdir())
    except OSError:
        return found
    for entry in entries:
        if not entry.name.isdecimal():
            continue
        program = _program_name(entry / "cmdline")
        if program is None or program not in names:
            continue
        if len(found) >= 20:
            break
        found.append(
            BrowserProcess(
                pid=int(entry.name),
                executable=program,
                application_id=program,
                synthetic=False,
            )
        )
    return sorted(found, key=lambda item: item.pid)


def _program_name(path: Path) -> str | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if not raw:
        return None
    token = raw.split(b"\0", 1)[0]
    text = token.decode("utf-8", errors="replace").strip()
    name = Path(text).name
    if not name or name in {".", ".."}:
        return None
    return name


def _dependency_present() -> bool:
    return importlib.util.find_spec(ENGINE_DEPENDENCY) is not None


def _layers(*, application: bool, present: bool) -> list[LayerStatus]:
    if present:
        automation = "Playwright is present but the OMNE automation adapter is not installed"
    else:
        automation = "Playwright is not installed"
    reasons = {
        "application": "installed browser application" if application else "no browser application",
        "automation": automation,
        "research": RESEARCH_NOT_INSTALLED,
        "rendering": RENDER_NOT_INSTALLED,
    }
    return [
        LayerStatus(
            id=spec.id,
            capability=spec.capability,
            permission=spec.permission,
            available=application if spec.id == "application" else False,
            simulated=False,
            reason=reasons[spec.id],
        )
        for spec in LAYER_SPECS
    ]
