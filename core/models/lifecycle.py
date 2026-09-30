"""Model lifecycle.

``ModelLifecycle.load`` does not map weights. ``ModelRuntime`` is the path that
moves a resident model through these states.
"""

from __future__ import annotations

from enum import StrEnum

from core.models.registry import ModelMetadata


class ModelLifecycleState(StrEnum):
    REGISTERED = "REGISTERED"
    AVAILABLE = "AVAILABLE"
    LOADING = "LOADING"
    LOADED = "LOADED"
    RUNNING = "RUNNING"
    BUSY = "BUSY"
    IDLE = "IDLE"
    UNLOADING = "UNLOADING"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"


SELECTABLE_STATES = frozenset(
    {
        ModelLifecycleState.AVAILABLE,
        ModelLifecycleState.LOADED,
        ModelLifecycleState.IDLE,
        ModelLifecycleState.RUNNING,
    }
)
LOADED_STATES = frozenset(
    {
        ModelLifecycleState.LOADED,
        ModelLifecycleState.IDLE,
        ModelLifecycleState.RUNNING,
    }
)

TRANSITIONS: dict[ModelLifecycleState, frozenset[ModelLifecycleState]] = {
    ModelLifecycleState.REGISTERED: frozenset(
        {ModelLifecycleState.AVAILABLE, ModelLifecycleState.UNAVAILABLE}
    ),
    ModelLifecycleState.AVAILABLE: frozenset({ModelLifecycleState.LOADING}),
    ModelLifecycleState.LOADING: frozenset(
        {ModelLifecycleState.LOADED, ModelLifecycleState.FAILED}
    ),
    ModelLifecycleState.LOADED: frozenset(
        {
            ModelLifecycleState.RUNNING,
            ModelLifecycleState.UNLOADING,
            ModelLifecycleState.FAILED,
        }
    ),
    ModelLifecycleState.RUNNING: frozenset(
        {
            ModelLifecycleState.IDLE,
            ModelLifecycleState.UNLOADING,
            ModelLifecycleState.FAILED,
        }
    ),
    ModelLifecycleState.BUSY: frozenset(
        {
            ModelLifecycleState.IDLE,
            ModelLifecycleState.UNLOADING,
            ModelLifecycleState.FAILED,
        }
    ),
    ModelLifecycleState.IDLE: frozenset(
        {
            ModelLifecycleState.RUNNING,
            ModelLifecycleState.UNLOADING,
            ModelLifecycleState.FAILED,
        }
    ),
    ModelLifecycleState.UNLOADING: frozenset(
        {ModelLifecycleState.AVAILABLE, ModelLifecycleState.FAILED}
    ),
    ModelLifecycleState.FAILED: frozenset(
        {ModelLifecycleState.LOADING, ModelLifecycleState.UNLOADING}
    ),
    ModelLifecycleState.UNAVAILABLE: frozenset(),
}


class InvalidModelTransition(Exception):
    """Raised when a model is asked to skip a lifecycle edge."""

    def __init__(
        self,
        model_id: str,
        current: ModelLifecycleState,
        proposed: ModelLifecycleState,
    ) -> None:
        super().__init__(f"{model_id} cannot move from {current.value} to {proposed.value}")
        self.model_id = model_id
        self.current = current
        self.proposed = proposed


class ModelLifecycle:
    """Track readiness. ``load`` does not download or map weights."""

    def __init__(self) -> None:
        self._states: dict[str, ModelLifecycleState] = {}

    def register(self, model: ModelMetadata, *, available: bool) -> ModelLifecycleState:
        state = ModelLifecycleState.AVAILABLE if available else ModelLifecycleState.UNAVAILABLE
        self._states[model.id] = state
        return state

    def state(self, model_id: str) -> ModelLifecycleState:
        return self._states.get(model_id, ModelLifecycleState.REGISTERED)

    def transition(self, model_id: str, proposed: ModelLifecycleState) -> ModelLifecycleState:
        current = self.state(model_id)
        if proposed not in TRANSITIONS.get(current, frozenset()):
            raise InvalidModelTransition(model_id, current, proposed)
        self._states[model_id] = proposed
        return proposed

    def load(self, model_id: str) -> dict[str, object]:
        """Report that this tracker does not load weights.

        ``ModelRuntime.load`` maps a model an engine already has. This method
        stays a no-op so a caller that has not asked the runtime does not see
        a state change or a ``model.loaded`` event.
        """

        current = self.state(model_id)
        return {
            "model_id": model_id,
            "performed": False,
            "state": current.value,
            "reason": "weight loading is not performed by this process",
        }

    def snapshot(self) -> dict[str, str]:
        return {model_id: state.value for model_id, state in self._states.items()}
