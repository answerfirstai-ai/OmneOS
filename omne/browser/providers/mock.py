"""In-memory browser sessions for tests and non-Linux hosts.

The mock records tabs, inspection, research fixtures, and screenshot requests.
It does not start a browser and it does not fetch a page.
"""

from __future__ import annotations

from urllib.parse import urlparse

from omne.browser.capabilities import ENGINE_DEPENDENCY, ENGINE_NOTE, LAYER_SPECS
from omne.browser.model import (
    BrowserActionRecord,
    BrowserEvent,
    BrowserEventType,
    BrowserOutcome,
    BrowserProcess,
    BrowserRequest,
    BrowserSession,
    BrowserState,
    BrowserTab,
    LayerStatus,
    PageInspection,
    ResearchReport,
    ResearchSource,
    ScreenshotRecord,
)
from omne.browser.urls import browser_query, browser_target, browser_url

_MISSING = "browser session was not found"
_NOT_A_BROWSER = "browser application was not found"
_USER = "the user controls this browser session"
_BAD_URL = "url must be an absolute http or https URL"
_BAD_QUERY = "research query is not a command"
_BAD_TARGET = "automation target is not allowed"
_LIMIT = "too many browser sessions"
_PAGES = {
    "about:blank": ("New Tab", ""),
    "https://example.com": ("Example Domain", "This domain is for use in documentation."),
}


class MockBrowserProvider:
    """A browser session that stays inside the record."""

    def __init__(self) -> None:
        self._sessions: dict[str, BrowserSession] = {}
        self._next_session = 0
        self._next_pid = 52000
        self._next_tab = 0

    def status(self) -> BrowserState:
        return BrowserState(
            provider="mock",
            observed=True,
            layers=_layers(simulated=True),
            capabilities=list(LAYER_SPECS),
            engine_dependency=ENGINE_DEPENDENCY,
            applications=["firefox"],
            processes=[],
            sessions=sorted(self._sessions.values(), key=lambda item: item.id),
            gaps=[ENGINE_NOTE],
        )

    def apply(self, request: BrowserRequest) -> BrowserOutcome:
        if request.action == "launch":
            return self._launch(request)
        if request.action == "navigate":
            return self._navigate(request)
        if request.action == "inspect":
            return self._inspect(request)
        if request.action == "research":
            return self._research(request)
        if request.action == "screenshot":
            return self._screenshot(request)
        if request.action == "interact":
            return self._interact(request)
        return self._automate(request)

    def _launch(self, request: BrowserRequest) -> BrowserOutcome:
        application_id = request.application_id or "firefox"
        if application_id != "firefox":
            return self._refuse(_NOT_A_BROWSER)
        if len(self._sessions) >= 8:
            return self._refuse(_LIMIT)
        self._next_session += 1
        self._next_pid += 1
        self._next_tab += 1
        session_id = f"session-{self._next_session}"
        session = BrowserSession(
            id=session_id,
            application_id="firefox",
            control="agent",
            authentication="none",
            process=BrowserProcess(
                pid=self._next_pid,
                executable="firefox",
                application_id="firefox",
                synthetic=True,
            ),
            tabs=[
                BrowserTab(
                    id=f"tab-{self._next_tab}",
                    url="about:blank",
                    title="New Tab",
                    active=True,
                )
            ],
            simulated=True,
        )
        self._sessions[session_id] = session
        return self._done(
            "recorded a simulated browser session",
            "browser.launched",
            {"session_id": session_id, "layer": "application"},
        )

    def _navigate(self, request: BrowserRequest) -> BrowserOutcome:
        session = self._session(request.session_id)
        if session is None:
            return self._refuse(_MISSING)
        url = browser_url(request.url or "")
        if url is None or url == "about:blank":
            return self._refuse(_BAD_URL)
        title, _excerpt = _PAGES.get(url, (urlparse_host(url), ""))
        tabs = [
            tab.model_copy(update={"url": url, "title": title, "active": True})
            if tab.active
            else tab
            for tab in session.tabs
        ]
        self._sessions[session.id] = session.model_copy(update={"tabs": tabs})
        return self._done(
            "recorded navigation in the simulated session",
            "browser.navigated",
            {"session_id": session.id, "layer": "application"},
        )

    def _inspect(self, request: BrowserRequest) -> BrowserOutcome:
        session = self._session(request.session_id)
        if session is None:
            return self._refuse(_MISSING)
        tab = _active(session)
        _title, excerpt = _PAGES.get(tab.url, (tab.title, ""))
        inspection = PageInspection(
            session_id=session.id,
            tab_id=tab.id,
            url=tab.url,
            title=tab.title,
            excerpt=excerpt[:500],
        )
        return self._done(
            "inspected the simulated page",
            "browser.inspected",
            {"session_id": session.id, "layer": "research"},
            inspection=inspection,
        )

    def _research(self, request: BrowserRequest) -> BrowserOutcome:
        query = browser_query(request.query or "")
        if query is None:
            return self._refuse(_BAD_QUERY)
        report = ResearchReport(
            query=query,
            sources=[
                ResearchSource(
                    title="Example Domain",
                    url="https://example.com",
                    excerpt="This domain is for use in documentation.",
                )
            ],
            simulated=True,
        )
        return self._done(
            "returned a fixture source without fetching a page",
            "browser.researched",
            {"layer": "research"},
            research=report,
        )

    def _screenshot(self, request: BrowserRequest) -> BrowserOutcome:
        session = self._session(request.session_id)
        if session is None:
            return self._refuse(_MISSING)
        updated = session.model_copy(update={"screenshots": session.screenshots + 1})
        self._sessions[session.id] = updated
        record = ScreenshotRecord(
            session_id=session.id,
            captured=True,
            simulated=True,
            reason="screenshot permission was recorded; no image bytes are stored",
        )
        return self._done(
            record.reason,
            "browser.rendered",
            {"session_id": session.id, "layer": "rendering"},
            screenshot=record,
        )

    def _interact(self, request: BrowserRequest) -> BrowserOutcome:
        session = self._session(request.session_id)
        if session is None:
            return self._refuse(_MISSING)
        self._sessions[session.id] = session.model_copy(
            update={"control": "user", "authentication": "user"}
        )
        return self._done(
            "the user controls this browser session",
            "browser.user_control",
            {"session_id": session.id, "layer": "application"},
        )

    def _automate(self, request: BrowserRequest) -> BrowserOutcome:
        session = self._session(request.session_id)
        if session is None:
            return self._refuse(_MISSING)
        if session.control == "user":
            return self._refuse(_USER)
        kind = request.kind
        if kind is None:
            return self._refuse(_BAD_TARGET)
        target = browser_target(request.target or "")
        if target is None:
            return self._refuse(_BAD_TARGET)
        action = BrowserActionRecord(kind=kind, target=target)
        self._sessions[session.id] = session.model_copy(
            update={"actions": [*session.actions, action]}
        )
        return self._done(
            "recorded a simulated automation step",
            "browser.automated",
            {"session_id": session.id, "layer": "automation"},
        )

    def _session(self, session_id: str | None) -> BrowserSession | None:
        if session_id is None:
            return None
        return self._sessions.get(session_id)

    def _refuse(self, reason: str) -> BrowserOutcome:
        return BrowserOutcome(applied=False, reason=reason, state=self.status())

    def _done(
        self,
        reason: str,
        event_type: BrowserEventType,
        payload: dict[str, str],
        *,
        inspection: PageInspection | None = None,
        research: ResearchReport | None = None,
        screenshot: ScreenshotRecord | None = None,
    ) -> BrowserOutcome:
        event = BrowserEvent(type=event_type, payload=payload)
        return BrowserOutcome(
            applied=True,
            reason=reason,
            state=self.status(),
            inspection=inspection,
            research=research,
            screenshot=screenshot,
            events=[event],
        )


def _layers(simulated: bool) -> list[LayerStatus]:
    reasons = {
        "application": "Firefox is a simulated browser application",
        "automation": ENGINE_NOTE,
        "research": "research uses a fixture and does not fetch a page",
        "rendering": "screenshots are recorded without image bytes",
    }
    available = {"application": True, "automation": False, "research": False, "rendering": False}
    return [
        LayerStatus(
            id=spec.id,
            capability=spec.capability,
            permission=spec.permission,
            available=available[spec.id],
            simulated=simulated,
            reason=reasons[spec.id],
        )
        for spec in LAYER_SPECS
    ]


def _active(session: BrowserSession) -> BrowserTab:
    for tab in session.tabs:
        if tab.active:
            return tab
    return session.tabs[0]


def urlparse_host(url: str) -> str:
    return urlparse(url).hostname or url
