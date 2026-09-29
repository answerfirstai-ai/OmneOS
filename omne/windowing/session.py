"""In-memory record of window state.

Labwc owns placement, focus policy, and workspace layout. This session stores
what a provider has observed and what a permitted request changed. It does not
tile windows and it does not speak Wayland.
"""

from __future__ import annotations

from typing import assert_never
from uuid import uuid4

from omne.windowing.model import (
    ApplyOutcome,
    ManagedWindow,
    MonitorRecord,
    ProviderName,
    WindowEventType,
    WindowingEvent,
    WindowingState,
    WindowRequest,
    WorkspaceRecord,
)

NOT_OBSERVED = "window list is not observed"
UNKNOWN_WINDOW = "window is unknown"
UNKNOWN_MONITOR = "monitor is unknown"
UNKNOWN_WORKSPACE = "workspace is unknown"
INCOMPLETE = "request is incomplete"
INVALID_SIZE = "size is invalid"


class WindowSession:
    """One recorded session shared by the mock and Linux providers."""

    def __init__(
        self,
        *,
        provider: ProviderName,
        compositor: str,
        known: bool,
        detail: str | None,
        windows: list[ManagedWindow],
        workspaces: list[WorkspaceRecord],
        monitors: list[MonitorRecord],
    ) -> None:
        self._provider: ProviderName = provider
        self._compositor = compositor
        self._known = known
        self._detail = detail
        self._windows = list(windows)
        self._workspaces = _one_active(workspaces)
        self._monitors = list(monitors)
        self._normalize_focus()

    def state(self) -> WindowingState:
        focused = next((window.id for window in self._windows if window.focused), None)
        active = next((workspace.id for workspace in self._workspaces if workspace.active), None)
        workspaces = [
            workspace.model_copy(
                update={
                    "window_ids": [
                        window.id for window in self._windows if window.workspace_id == workspace.id
                    ]
                }
            )
            for workspace in self._workspaces
        ]
        return WindowingState(
            provider=self._provider,
            known=self._known,
            compositor=self._compositor,
            compositor_commanded=False,
            focused_window_id=focused,
            active_workspace_id=active,
            windows=list(self._windows),
            workspaces=workspaces,
            monitors=list(self._monitors),
            fullscreen_window_id=_fullscreen_id(self._windows),
            detail=self._detail,
        )

    def apply(self, request: WindowRequest) -> ApplyOutcome:
        if not self._known:
            return self._refuse(NOT_OBSERVED)
        if request.action == "launch":
            return self._launch(request)
        if request.action == "focus":
            return self._focus(request)
        if request.action == "close":
            return self._close(request)
        if request.action == "move":
            return self._move(request)
        if request.action == "resize":
            return self._resize(request)
        if request.action == "minimize":
            return self._minimize(request)
        if request.action == "maximize":
            return self._maximize(request)
        if request.action == "fullscreen":
            return self._fullscreen(request)
        if request.action == "workspace":
            return self._workspace(request)
        assert_never(request.action)

    def _launch(self, request: WindowRequest) -> ApplyOutcome:
        app_id = (request.app_id or "").strip()
        if not app_id:
            return self._refuse(INCOMPLETE)
        if _invalid_size(request.width, request.height):
            return self._refuse(INVALID_SIZE)
        active = next((workspace for workspace in self._workspaces if workspace.active), None)
        if active is None:
            return self._refuse(UNKNOWN_WORKSPACE)
        if request.monitor_id is not None and not self._has_monitor(request.monitor_id):
            return self._refuse(UNKNOWN_MONITOR)
        title = (request.title or "").strip() or app_id
        window = ManagedWindow(
            id=str(uuid4()),
            title=title,
            app_id=app_id,
            workspace_id=active.id,
            monitor_id=request.monitor_id,
            x=request.x,
            y=request.y,
            width=request.width,
            height=request.height,
            focused=True,
            mapped=True,
            owner=request.agent_id,
        )
        self._clear_focus()
        self._windows.append(window)
        return self._ok(
            [
                _event("window.created", {"id": window.id, "app_id": window.app_id}),
                _event("window.focused", {"id": window.id, "app_id": window.app_id}),
            ]
        )

    def _focus(self, request: WindowRequest) -> ApplyOutcome:
        window, reason = self._window(request.window_id)
        if window is None:
            return self._refuse(reason or UNKNOWN_WINDOW)
        if window.minimized:
            return self._refuse("window is minimized")
        if not window.mapped:
            return self._refuse("window is not mapped")
        if window.focused:
            return self._ok([])
        self._clear_focus()
        self._replace(window.model_copy(update={"focused": True}))
        return self._ok([_event("window.focused", {"id": window.id, "app_id": window.app_id})])

    def _close(self, request: WindowRequest) -> ApplyOutcome:
        window, reason = self._window(request.window_id)
        if window is None:
            return self._refuse(reason or UNKNOWN_WINDOW)
        was_focused = window.focused
        self._windows = [item for item in self._windows if item.id != window.id]
        events = [_event("window.closed", {"id": window.id, "app_id": window.app_id})]
        if was_focused:
            nxt = self._next_focus()
            if nxt is not None:
                self._replace(nxt.model_copy(update={"focused": True}))
                events.append(_event("window.focused", {"id": nxt.id, "app_id": nxt.app_id}))
        return self._ok(events)

    def _move(self, request: WindowRequest) -> ApplyOutcome:
        window, reason = self._window(request.window_id)
        if window is None:
            return self._refuse(reason or UNKNOWN_WINDOW)
        if request.x is None or request.y is None:
            return self._refuse(INCOMPLETE)
        monitor_id = window.monitor_id
        fields = ["x", "y"]
        if request.monitor_id is not None:
            if not self._has_monitor(request.monitor_id):
                return self._refuse(UNKNOWN_MONITOR)
            if request.monitor_id != window.monitor_id:
                fields.append("monitor_id")
            monitor_id = request.monitor_id
        if request.x == window.x and request.y == window.y and monitor_id == window.monitor_id:
            return self._ok([])
        self._replace(
            window.model_copy(update={"x": request.x, "y": request.y, "monitor_id": monitor_id})
        )
        return self._ok([_changed(window, fields)])

    def _resize(self, request: WindowRequest) -> ApplyOutcome:
        window, reason = self._window(request.window_id)
        if window is None:
            return self._refuse(reason or UNKNOWN_WINDOW)
        if request.width is None or request.height is None:
            return self._refuse(INCOMPLETE)
        if request.width <= 0 or request.height <= 0:
            return self._refuse(INVALID_SIZE)
        if request.width == window.width and request.height == window.height:
            return self._ok([])
        self._replace(window.model_copy(update={"width": request.width, "height": request.height}))
        return self._ok([_changed(window, ["width", "height"])])

    def _minimize(self, request: WindowRequest) -> ApplyOutcome:
        window, reason = self._window(request.window_id)
        if window is None:
            return self._refuse(reason or UNKNOWN_WINDOW)
        if window.minimized and not window.focused:
            return self._ok([])
        was_focused = window.focused
        fields = ["minimized"]
        if was_focused:
            fields.append("focused")
        self._replace(window.model_copy(update={"minimized": True, "focused": False}))
        events = [_changed(window, fields)]
        if was_focused:
            nxt = self._next_focus()
            if nxt is not None:
                self._replace(nxt.model_copy(update={"focused": True}))
                events.append(_event("window.focused", {"id": nxt.id, "app_id": nxt.app_id}))
        return self._ok(events)

    def _maximize(self, request: WindowRequest) -> ApplyOutcome:
        window, reason = self._window(request.window_id)
        if window is None:
            return self._refuse(reason or UNKNOWN_WINDOW)
        if window.maximized and not window.minimized and window.focused:
            return self._ok([])
        fields: list[str] = []
        if not window.maximized:
            fields.append("maximized")
        if window.minimized:
            fields.append("minimized")
        update: dict[str, bool] = {"maximized": True, "minimized": False}
        events: list[WindowingEvent] = []
        if not window.focused:
            self._clear_focus()
            update["focused"] = True
            fields.append("focused")
        self._replace(window.model_copy(update=update))
        if fields:
            events.append(_changed(window, fields))
        if not window.focused:
            events.append(_event("window.focused", {"id": window.id, "app_id": window.app_id}))
        return self._ok(events)

    def _fullscreen(self, request: WindowRequest) -> ApplyOutcome:
        window, reason = self._window(request.window_id)
        if window is None:
            return self._refuse(reason or UNKNOWN_WINDOW)
        if request.fullscreen is None:
            return self._refuse(INCOMPLETE)
        if request.fullscreen == window.fullscreen and (window.focused or not request.fullscreen):
            return self._ok([])
        events: list[WindowingEvent] = []
        if request.fullscreen:
            for other in self._windows:
                if (
                    other.id != window.id
                    and other.fullscreen
                    and other.monitor_id == window.monitor_id
                ):
                    self._replace(other.model_copy(update={"fullscreen": False}))
                    events.append(_changed(other, ["fullscreen"]))
        update: dict[str, bool] = {"fullscreen": request.fullscreen}
        fields = ["fullscreen"]
        if request.fullscreen and not window.focused:
            self._clear_focus()
            update["focused"] = True
            fields.append("focused")
        self._replace(window.model_copy(update=update))
        events.append(_changed(window, fields))
        if request.fullscreen and not window.focused:
            events.append(_event("window.focused", {"id": window.id, "app_id": window.app_id}))
        return self._ok(events)

    def _workspace(self, request: WindowRequest) -> ApplyOutcome:
        workspace_id = (request.workspace_id or "").strip()
        if not workspace_id:
            return self._refuse(INCOMPLETE)
        if not any(workspace.id == workspace_id for workspace in self._workspaces):
            return self._refuse(UNKNOWN_WORKSPACE)
        if request.window_id is None:
            return self._activate(workspace_id)
        window, reason = self._window(request.window_id)
        if window is None:
            return self._refuse(reason or UNKNOWN_WINDOW)
        if window.workspace_id == workspace_id:
            return self._ok([])
        self._replace(window.model_copy(update={"workspace_id": workspace_id}))
        return self._ok(
            [
                _changed(window, ["workspace_id"]),
                _event(
                    "workspace.changed",
                    {"workspace_id": workspace_id, "window_id": window.id},
                ),
            ]
        )

    def _activate(self, workspace_id: str) -> ApplyOutcome:
        if any(workspace.id == workspace_id and workspace.active for workspace in self._workspaces):
            return self._ok([])
        self._workspaces = [
            workspace.model_copy(update={"active": workspace.id == workspace_id})
            for workspace in self._workspaces
        ]
        return self._ok([_event("workspace.changed", {"workspace_id": workspace_id})])

    def _window(self, window_id: str | None) -> tuple[ManagedWindow | None, str | None]:
        if not window_id:
            return None, INCOMPLETE
        for window in self._windows:
            if window.id == window_id:
                return window, None
        return None, UNKNOWN_WINDOW

    def _has_monitor(self, monitor_id: str) -> bool:
        return any(monitor.id == monitor_id for monitor in self._monitors)

    def _replace(self, window: ManagedWindow) -> None:
        self._windows = [window if item.id == window.id else item for item in self._windows]

    def _clear_focus(self) -> None:
        self._windows = [
            item.model_copy(update={"focused": False}) if item.focused else item
            for item in self._windows
        ]

    def _next_focus(self) -> ManagedWindow | None:
        for window in self._windows:
            if window.mapped and not window.minimized and not window.focused:
                return window
        return None

    def _normalize_focus(self) -> None:
        chosen = next(
            (
                window.id
                for window in reversed(self._windows)
                if window.focused and window.mapped and not window.minimized
            ),
            None,
        )
        self._windows = [
            window.model_copy(update={"focused": window.id == chosen})
            if window.focused != (window.id == chosen)
            else window
            for window in self._windows
        ]

    def _ok(self, events: list[WindowingEvent]) -> ApplyOutcome:
        return ApplyOutcome(applied=True, reason="applied", state=self.state(), events=events)

    def _refuse(self, reason: str) -> ApplyOutcome:
        return ApplyOutcome(applied=False, reason=reason, state=self.state(), events=[])


def _one_active(workspaces: list[WorkspaceRecord]) -> list[WorkspaceRecord]:
    chosen = next(
        (workspace.id for workspace in reversed(workspaces) if workspace.active),
        None,
    )
    if chosen is None:
        return list(workspaces)
    return [
        workspace.model_copy(update={"active": workspace.id == chosen})
        if workspace.active != (workspace.id == chosen)
        else workspace
        for workspace in workspaces
    ]


def _fullscreen_id(windows: list[ManagedWindow]) -> str | None:
    focused = next((window for window in windows if window.focused and window.fullscreen), None)
    if focused is not None:
        return focused.id
    return next((window.id for window in windows if window.fullscreen), None)


def _invalid_size(width: int | None, height: int | None) -> bool:
    if width is not None and width <= 0:
        return True
    return height is not None and height <= 0


def _changed(window: ManagedWindow, fields: list[str]) -> WindowingEvent:
    return _event("window.changed", {"id": window.id, "fields": list(fields)})


def _event(event_type: WindowEventType, payload: dict[str, object]) -> WindowingEvent:
    return WindowingEvent(type=event_type, payload=payload)
