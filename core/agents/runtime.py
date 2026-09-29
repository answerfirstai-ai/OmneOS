"""Start an agent for one task and unload it afterward."""

from __future__ import annotations

from core.agents.lifecycle import AgentLifecycle, AgentState
from core.agents.manifest import AgentManifest


class AgentRuntime:
    """Drive the lifecycle around a single piece of work."""

    def __init__(self, lifecycle: AgentLifecycle) -> None:
        self._lifecycle = lifecycle

    def begin(self, manifest: AgentManifest) -> None:
        state = self._lifecycle.state(manifest.id)
        if state is AgentState.UNLOADED:
            self._lifecycle.transition(manifest.id, AgentState.AVAILABLE)
        self._lifecycle.transition(manifest.id, AgentState.RESERVED)
        self._lifecycle.transition(manifest.id, AgentState.INITIALIZING)
        self._lifecycle.transition(manifest.id, AgentState.RUNNING)

    def succeed(self, manifest: AgentManifest) -> None:
        self._lifecycle.transition(manifest.id, AgentState.VERIFYING)
        self._lifecycle.transition(manifest.id, AgentState.COMPLETED)
        self._finish(manifest)

    def release(self, manifest: AgentManifest) -> None:
        """Return a running agent to the pool while a person confirms an action."""

        if self._lifecycle.state(manifest.id) is AgentState.RUNNING:
            self._lifecycle.transition(manifest.id, AgentState.RECOVERING)
            self._lifecycle.transition(manifest.id, AgentState.AVAILABLE)

    def fail(self, manifest: AgentManifest, *, retry: bool) -> None:
        current = self._lifecycle.state(manifest.id)
        if current is AgentState.RUNNING:
            self._lifecycle.transition(manifest.id, AgentState.FAILED)
        if retry:
            self._lifecycle.transition(manifest.id, AgentState.RECOVERING)
            self._lifecycle.transition(manifest.id, AgentState.INITIALIZING)
            self._lifecycle.transition(manifest.id, AgentState.RUNNING)
            return
        if self._lifecycle.state(manifest.id) is AgentState.FAILED:
            self._lifecycle.transition(manifest.id, AgentState.UNLOADED)
            self._lifecycle.transition(manifest.id, AgentState.AVAILABLE)

    def _finish(self, manifest: AgentManifest) -> None:
        if manifest.lifecycle.persistent:
            self._lifecycle.transition(manifest.id, AgentState.AVAILABLE)
            return
        self._lifecycle.transition(manifest.id, AgentState.UNLOADED)
        self._lifecycle.transition(manifest.id, AgentState.AVAILABLE)
