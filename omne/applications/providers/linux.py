"""Read desktop applications without starting them.

Desktop files come from the standard application directories. Processes are
matched by the program name in ``cmdline``. Windows come from an explicit
snapshot when one is present. This module does not spawn a process.
"""

from __future__ import annotations

import json
from pathlib import Path

from omne.applications.desktop import parse_desktop_file
from omne.applications.model import (
    Application,
    ApplicationCatalog,
    ApplicationRequest,
    ApplyOutcome,
    AppProcess,
    AppWindow,
)

HOST_NOT_LAUNCHED = "host application launch is not installed"
_APP_DIRS = (
    Path("usr/share/applications"),
    Path("usr/local/share/applications"),
)


class LinuxApplicationProvider:
    """Report installed desktop applications from one filesystem root."""

    def __init__(self, *, root: Path | None = None) -> None:
        self._root = root if root is not None else Path("/")

    def catalog(self) -> ApplicationCatalog:
        if not self._root.is_dir():
            return ApplicationCatalog(provider="linux", observed=False, gaps=["linux"])
        apps, gap = _applications(self._root)
        processes = _processes(self._root)
        windows, window_gap = _windows(self._root)
        gaps = [item for item in (gap, window_gap) if item]
        joined = [_observe(app, processes, windows) for app in apps]
        return ApplicationCatalog(
            provider="linux",
            observed=True,
            applications=sorted(joined, key=lambda item: item.id),
            gaps=gaps,
        )

    def apply(self, request: ApplicationRequest) -> ApplyOutcome:
        del request
        return ApplyOutcome(applied=False, reason=HOST_NOT_LAUNCHED, catalog=self.catalog())


def _applications(root: Path) -> tuple[list[Application], str | None]:
    found: list[Application] = []
    seen: set[str] = set()
    readable = False
    for relative in _APP_DIRS:
        directory = root / relative
        if not directory.is_dir():
            continue
        readable = True
        try:
            paths = sorted(directory.glob("*.desktop"))
        except OSError:
            return [], "applications"
        for path in paths:
            if path.name in seen:
                continue
            app = parse_desktop_file(path)
            if app is None:
                continue
            seen.add(path.name)
            found.append(app)
    if not readable and not any((root / relative).exists() for relative in _APP_DIRS):
        return [], None
    return found, None


def _processes(root: Path) -> dict[str, list[AppProcess]]:
    proc = root / "proc"
    grouped: dict[str, list[AppProcess]] = {}
    if not proc.is_dir():
        return grouped
    try:
        entries = list(proc.iterdir())
    except OSError:
        return grouped
    for entry in entries:
        if not entry.name.isdecimal():
            continue
        program = _program_name(entry / "cmdline")
        if program is None:
            continue
        grouped.setdefault(program, [])
        if len(grouped[program]) >= 20:
            continue
        grouped[program].append(AppProcess(pid=int(entry.name), executable=program))
    return grouped


def _program_name(path: Path) -> str | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if not raw:
        return None
    token = raw.split(b"\0", 1)[0]
    try:
        text = token.decode("utf-8", errors="replace").strip()
    except UnicodeError:
        return None
    name = Path(text).name
    if not name or name in {".", ".."}:
        return None
    return name


def _windows(root: Path) -> tuple[list[AppWindow], str | None]:
    if root == Path("/"):
        return [], None
    path = root / "run" / "omne" / "windows.json"
    if not path.exists():
        return [], None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [], "windows"
    rows = loaded.get("windows") if isinstance(loaded, dict) else None
    if not isinstance(rows, list):
        return [], "windows"
    found: list[AppWindow] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        identity = item.get("id")
        title = item.get("title")
        app_id = item.get("app_id")
        if not all(isinstance(value, str) and value for value in (identity, title, app_id)):
            continue
        found.append(
            AppWindow(
                id=str(identity),
                title=str(title),
                app_id=str(app_id),
                focused=item.get("focused") is True,
            )
        )
    return found, None


def _observe(
    app: Application,
    processes: dict[str, list[AppProcess]],
    windows: list[AppWindow],
) -> Application:
    program = Path(app.executable).name if app.executable else ""
    matched = list(processes.get(program, []))
    own_windows = [
        item for item in windows if item.app_id == app.id or (program and item.app_id == program)
    ]
    state = app.state
    if own_windows and any(item.focused for item in own_windows):
        state = "focused"
    elif matched or own_windows:
        state = "running"
    return app.model_copy(update={"processes": matched, "windows": own_windows, "state": state})
