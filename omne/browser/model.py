"""Browser records. A session is not a shell command and not a live page fetch.

The application, automation, research, and rendering layers stay separate.
Automation does not start a host browser in this revision.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ProviderName = Literal["mock", "linux"]
LayerName = Literal["application", "automation", "research", "rendering"]
BrowserAction = Literal[
    "launch",
    "navigate",
    "inspect",
    "research",
    "screenshot",
    "interact",
    "automate",
]
BrowserControl = Literal["agent", "user"]
AutomationKind = Literal["click", "wait"]
BrowserEventType = Literal[
    "browser.launched",
    "browser.navigated",
    "browser.inspected",
    "browser.researched",
    "browser.rendered",
    "browser.user_control",
    "browser.automated",
]


class LayerSpec(BaseModel):
    """One browser layer and the permission that guards it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: LayerName
    capability: str = Field(min_length=1)
    permission: str = Field(min_length=1)
    summary: str = Field(min_length=1)


class LayerStatus(BaseModel):
    """Whether one layer can be used in this provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: LayerName
    capability: str = Field(min_length=1)
    permission: str = Field(min_length=1)
    available: bool
    simulated: bool
    reason: str


class BrowserProcess(BaseModel):
    """A browser process OMNE has named. OMNE did not start it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    pid: int = Field(ge=1)
    executable: str = Field(min_length=1)
    application_id: str = Field(min_length=1)
    synthetic: bool
    started_by_omne: bool = False

    @field_validator("started_by_omne")
    @classmethod
    def _not_started(cls, value: bool) -> bool:
        if value:
            raise ValueError("OMNE does not start a host browser process")
        return value


class BrowserTab(BaseModel):
    """One tab in a session OMNE recorded."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    url: str = Field(min_length=1)
    title: str
    active: bool


class BrowserActionRecord(BaseModel):
    """An automation step. The record has no typed text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: AutomationKind
    target: str = Field(min_length=1)


class BrowserSession(BaseModel):
    """A recorded browser session. It is not attached to the host browser."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    application_id: str = Field(min_length=1)
    control: BrowserControl
    authentication: Literal["none", "user"]
    process: BrowserProcess | None = None
    tabs: list[BrowserTab] = Field(default_factory=list)
    actions: list[BrowserActionRecord] = Field(default_factory=list)
    screenshots: int = Field(default=0, ge=0)
    simulated: bool
    attached: bool = False

    @field_validator("attached")
    @classmethod
    def _not_attached(cls, value: bool) -> bool:
        if value:
            raise ValueError("OMNE does not attach to a host browser session")
        return value


class PageInspection(BaseModel):
    """Visible page fields. Credentials are not part of the record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str = Field(min_length=1)
    tab_id: str = Field(min_length=1)
    url: str = Field(min_length=1)
    title: str
    excerpt: str
    credentials: bool = False

    @field_validator("credentials")
    @classmethod
    def _no_credentials(cls, value: bool) -> bool:
        if value:
            raise ValueError("page inspection must not carry credentials")
        return value


class ResearchSource(BaseModel):
    """One research source. This revision does not fetch it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    excerpt: str


class ResearchReport(BaseModel):
    """A research result. ``network`` stays false because no page is fetched."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str = Field(min_length=1)
    sources: list[ResearchSource] = Field(default_factory=list)
    retrieved: bool = False
    simulated: bool
    network: bool = False

    @field_validator("retrieved")
    @classmethod
    def _not_retrieved(cls, value: bool) -> bool:
        if value:
            raise ValueError("live page retrieval is not installed")
        return value

    @field_validator("network")
    @classmethod
    def _offline(cls, value: bool) -> bool:
        if value:
            raise ValueError("browser research must not fetch the network")
        return value


class ScreenshotRecord(BaseModel):
    """A permitted screenshot request. This revision stores no image bytes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str = Field(min_length=1)
    captured: bool
    simulated: bool
    byte_length: int = Field(default=0, ge=0, le=0)
    reason: str


class BrowserState(BaseModel):
    """Availability of the four browser layers and any recorded sessions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: ProviderName
    observed: bool
    layers: list[LayerStatus] = Field(default_factory=list)
    capabilities: list[LayerSpec] = Field(default_factory=list)
    engine_dependency: str = "playwright"
    engine_installed: bool = False
    engine_imported: bool = False
    dependency_present: bool = False
    applications: list[str] = Field(default_factory=list)
    processes: list[BrowserProcess] = Field(default_factory=list)
    sessions: list[BrowserSession] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    commanded: bool = False
    attached: bool = False

    @field_validator("engine_imported")
    @classmethod
    def _not_imported(cls, value: bool) -> bool:
        if value:
            raise ValueError("OMNE does not import a browser automation engine")
        return value

    @field_validator("commanded")
    @classmethod
    def _not_commanded(cls, value: bool) -> bool:
        if value:
            raise ValueError("browser integration must not command a shell")
        return value

    @field_validator("attached")
    @classmethod
    def _not_attached(cls, value: bool) -> bool:
        if value:
            raise ValueError("OMNE does not attach to a host browser session")
        return value


class BrowserRequest(BaseModel):
    """One browser action. The request has no command string and no typed secret."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: BrowserAction
    agent_id: str = Field(min_length=1)
    session_id: str | None = None
    application_id: str | None = None
    url: str | None = None
    query: str | None = None
    target: str | None = None
    kind: AutomationKind | None = None

    def public_arguments(self) -> dict[str, object]:
        """Arguments safe to hand to the permission policy."""

        arguments: dict[str, object] = {"action": self.action}
        if self.session_id:
            arguments["session_id"] = self.session_id
        if self.application_id:
            arguments["application_id"] = self.application_id
        if self.url:
            arguments["url"] = self.url
        if self.query:
            arguments["query"] = self.query
        if self.target:
            arguments["target"] = self.target
        if self.kind:
            arguments["kind"] = self.kind
        return arguments


class BrowserEvent(BaseModel):
    """One browser event. The payload names a session, not a page body."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: BrowserEventType
    payload: dict[str, Any] = Field(default_factory=dict)


class BrowserOutcome(BaseModel):
    """The result of one browser action."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    applied: bool
    reason: str
    state: BrowserState
    inspection: PageInspection | None = None
    research: ResearchReport | None = None
    screenshot: ScreenshotRecord | None = None
    events: list[BrowserEvent] = Field(default_factory=list)
