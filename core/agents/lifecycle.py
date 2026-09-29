"""Enforced agent lifecycle transitions."""

from __future__ import annotations

from enum import StrEnum

from core.events.bus import EventBus


class AgentState(StrEnum):
    REGISTERED = "REGISTERED"
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    INITIALIZING = "INITIALIZING"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    UNLOADED = "UNLOADED"
    FAILED = "FAILED"
    RECOVERING = "RECOVERING"


TRANSITIONS: dict[AgentState, frozenset[AgentState]] = {
    AgentState.REGISTERED: frozenset({AgentState.AVAILABLE, AgentState.FAILED}),
    AgentState.AVAILABLE: frozenset({AgentState.RESERVED, AgentState.UNLOADED, AgentState.FAILED}),
    AgentState.RESERVED: frozenset(
        {AgentState.INITIALIZING, AgentState.AVAILABLE, AgentState.FAILED}
    ),
    AgentState.INITIALIZING: frozenset(
        {AgentState.RUNNING, AgentState.FAILED, AgentState.RECOVERING}
    ),
    AgentState.RUNNING: frozenset({AgentState.VERIFYING, AgentState.FAILED, AgentState.RECOVERING}),
    AgentState.VERIFYING: frozenset(
        {AgentState.COMPLETED, AgentState.FAILED, AgentState.RECOVERING}
    ),
    AgentState.COMPLETED: frozenset({AgentState.UNLOADED, AgentState.AVAILABLE}),
    AgentState.UNLOADED: frozenset({AgentState.AVAILABLE}),
    AgentState.FAILED: frozenset({AgentState.RECOVERING, AgentState.UNLOADED}),
    AgentState.RECOVERING: frozenset(
        {AgentState.INITIALIZING, AgentState.FAILED, AgentState.AVAILABLE}
    ),
}

_EVENTS = {
    AgentState.REGISTERED: "agent.registered",
    AgentState.RUNNING: "agent.started",
    AgentState.COMPLETED: "agent.completed",
    AgentState.FAILED: "agent.failed",
    AgentState.UNLOADED: "agent.unloaded",
}


class InvalidAgentTransition(Exception):
    """Raised when an agent lifecycle edge is not allowed."""

    def __init__(self, agent_id: str, current: AgentState, proposed: AgentState) -> None:
        super().__init__(f"{agent_id} cannot move from {current} to {proposed}")
        self.agent_id = agent_id
        self.current = current
        self.proposed = proposed


class AgentLifecycle:
    """Track lifecycle state for registered agents."""

    def __init__(self, events: EventBus) -> None:
        self._events = events
        self._states: dict[str, AgentState] = {}

    def register(self, agent_id: str) -> AgentState:
        if agent_id in self._states:
            raise ValueError(f"agent already tracked: {agent_id}")
        self._states[agent_id] = AgentState.REGISTERED
        self._emit(agent_id, AgentState.REGISTERED)
        return self.transition(agent_id, AgentState.AVAILABLE)

    def state(self, agent_id: str) -> AgentState:
        try:
            return self._states[agent_id]
        except KeyError as exc:
            raise KeyError(f"agent is not tracked: {agent_id}") from exc

    def transition(self, agent_id: str, proposed: AgentState) -> AgentState:
        current = self.state(agent_id)
        if proposed not in TRANSITIONS[current]:
            raise InvalidAgentTransition(agent_id, current, proposed)
        self._states[agent_id] = proposed
        self._emit(agent_id, proposed)
        return proposed

    def _emit(self, agent_id: str, state: AgentState) -> None:
        event_type = _EVENTS.get(state)
        if event_type is not None:
            self._events.publish(event_type, agent_id=agent_id, payload={"state": state.value})
