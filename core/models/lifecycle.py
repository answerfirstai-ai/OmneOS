"""Model lifecycle that does not claim weights were loaded."""

from __future__ import annotations

from enum import StrEnum

from core.models.registry import ModelMetadata


class ModelLifecycleState(StrEnum):
    REGISTERED = "REGISTERED"
    AVAILABLE = "AVAILABLE"
    LOADING = "LOADING"
    LOADED = "LOADED"
    BUSY = "BUSY"
    IDLE = "IDLE"
    UNLOADING = "UNLOADING"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"


class ModelLifecycle:
    """Track provider readiness. ``load`` does not download or map weights."""

    def __init__(self) -> None:
        self._states: dict[str, ModelLifecycleState] = {}

    def register(self, model: ModelMetadata, *, available: bool) -> ModelLifecycleState:
        state = ModelLifecycleState.AVAILABLE if available else ModelLifecycleState.UNAVAILABLE
        self._states[model.id] = state
        return state

    def state(self, model_id: str) -> ModelLifecycleState:
        return self._states.get(model_id, ModelLifecycleState.REGISTERED)

    def load(self, model_id: str) -> dict[str, object]:
        """Record that a load was requested. This process does not load weights."""

        current = self.state(model_id)
        return {
            "model_id": model_id,
            "performed": False,
            "state": current.value,
            "reason": "weight loading is not performed by this process",
        }

    def snapshot(self) -> dict[str, str]:
        return {model_id: state.value for model_id, state in self._states.items()}
