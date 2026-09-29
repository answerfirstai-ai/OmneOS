"""In-memory window provider for tests and non-Linux hosts.

The mock session starts with no windows. Its two workspaces are fixed names
for the record, not detected monitors.
"""

from __future__ import annotations

from omne.windowing.model import ApplyOutcome, WindowingState, WindowRequest, WorkspaceRecord
from omne.windowing.session import WindowSession


class MockWindowProvider:
    """A session OMNE can change without a compositor."""

    def __init__(self) -> None:
        self._session = WindowSession(
            provider="mock",
            compositor="none",
            known=True,
            detail=None,
            windows=[],
            workspaces=[
                WorkspaceRecord(id="default", name="Default", active=True),
                WorkspaceRecord(id="other", name="Other", active=False),
            ],
            monitors=[],
        )

    def state(self) -> WindowingState:
        return self._session.state()

    def apply(self, request: WindowRequest) -> ApplyOutcome:
        return self._session.apply(request)
