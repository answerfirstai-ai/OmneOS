"""In-memory applications for tests and non-Linux hosts.

The mock starts with a small catalog. Launch records a process and a window.
It does not start a program.
"""

from __future__ import annotations

from omne.applications.model import (
    Application,
    ApplicationCatalog,
    ApplicationEvent,
    ApplicationRequest,
    ApplyOutcome,
    AppProcess,
    AppWindow,
)

_NOT_LAUNCHABLE = "application is not launchable"
_MISSING = "application was not found"
_NO_WINDOW = "application has no window"


class MockApplicationProvider:
    """A catalog whose launch state stays inside the record."""

    def __init__(self) -> None:
        self._apps = {item.id: item for item in _seed()}
        self._next_pid = 41000

    def catalog(self) -> ApplicationCatalog:
        return ApplicationCatalog(
            provider="mock",
            observed=True,
            applications=sorted(self._apps.values(), key=lambda item: item.id),
        )

    def apply(self, request: ApplicationRequest) -> ApplyOutcome:
        current = self.catalog()
        app = self._apps.get(request.application_id)
        if app is None:
            return ApplyOutcome(applied=False, reason=_MISSING, catalog=current)
        if request.action == "launch":
            return self._launch(app)
        if request.action == "focus":
            return self._focus(app)
        return self._close(app)

    def _launch(self, app: Application) -> ApplyOutcome:
        if not app.launchable or app.executable is None:
            return ApplyOutcome(applied=False, reason=_NOT_LAUNCHABLE, catalog=self.catalog())
        self._next_pid += 1
        updated = app.model_copy(
            update={
                "processes": [AppProcess(pid=self._next_pid, executable=app.executable)],
                "windows": [
                    AppWindow(
                        id=f"window-{app.id}",
                        title=app.name,
                        app_id=app.id,
                        focused=True,
                    )
                ],
                "state": "focused",
            }
        )
        self._apps[app.id] = updated
        event = ApplicationEvent(
            type="application.launched",
            payload={"id": app.id, "name": app.name},
        )
        return ApplyOutcome(applied=True, reason="launched", catalog=self.catalog(), events=[event])

    def _focus(self, app: Application) -> ApplyOutcome:
        if not app.windows:
            return ApplyOutcome(applied=False, reason=_NO_WINDOW, catalog=self.catalog())
        windows = [item.model_copy(update={"focused": True}) for item in app.windows]
        self._apps[app.id] = app.model_copy(update={"windows": windows, "state": "focused"})
        event = ApplicationEvent(type="application.focused", payload={"id": app.id})
        return ApplyOutcome(applied=True, reason="focused", catalog=self.catalog(), events=[event])

    def _close(self, app: Application) -> ApplyOutcome:
        state = "hidden" if app.state == "hidden" else "installed"
        self._apps[app.id] = app.model_copy(update={"processes": [], "windows": [], "state": state})
        event = ApplicationEvent(type="application.closed", payload={"id": app.id})
        return ApplyOutcome(applied=True, reason="closed", catalog=self.catalog(), events=[event])


def _seed() -> list[Application]:
    return [
        Application(
            id="firefox",
            name="Firefox",
            desktop_entry="firefox.desktop",
            executable="/usr/bin/firefox",
            icon="firefox",
            categories=["Network", "WebBrowser"],
            permissions=["application:launch"],
            state="installed",
            launchable=True,
        ),
        Application(
            id="org.gnome.Files",
            name="Files",
            desktop_entry="org.gnome.Files.desktop",
            executable="/usr/bin/nautilus",
            icon="org.gnome.Files",
            categories=["System", "FileManager"],
            permissions=["application:launch"],
            state="installed",
            launchable=True,
        ),
    ]
