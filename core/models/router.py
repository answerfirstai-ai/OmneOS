"""Deterministic model routing."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from core.compute.allocation import AllocationDecision, AllocationRequest, allocate
from core.compute.monitor import ResourceSnapshot
from core.models.registry import ModelMetadata, ModelRegistry


class Route(BaseModel):
    """The model selected for a request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: ModelMetadata
    decision: AllocationDecision
    reason: str


class RoutingError(Exception):
    """No registered model can serve the request."""


class ModelRouter:
    """Choose a model from declared capabilities and a resource snapshot."""

    def __init__(self, registry: ModelRegistry) -> None:
        self._registry = registry

    def select(self, capabilities: list[str], snapshot: ResourceSnapshot) -> Route:
        required = set(capabilities)
        candidates = [
            model for model in self._registry.enabled() if required <= set(model.capabilities)
        ]
        candidates.sort(key=lambda model: (model.priority, model.id))
        cloud_available = any(not model.local for model in candidates)
        notes: list[str] = []
        for model in candidates:
            decision, reason = allocate(
                snapshot,
                AllocationRequest(
                    requirements=model.requirements,
                    local=model.local,
                    cloud_available=cloud_available and model.local,
                ),
            )
            if decision is AllocationDecision.ALLOW:
                return Route(model=model, decision=decision, reason=reason)
            if decision is AllocationDecision.USE_CLOUD:
                cloud = _first_cloud(candidates)
                if cloud is not None:
                    return Route(
                        model=cloud,
                        decision=AllocationDecision.USE_CLOUD,
                        reason=reason,
                    )
            notes.append(f"{model.id}: {decision.value} {reason}")
        if candidates and all(note.split(":", 1)[1].strip().startswith("WAIT") for note in notes):
            raise RoutingError("models are waiting for resources: " + "; ".join(notes))
        if not candidates:
            raise RoutingError(
                "no model provides the required capabilities: " + ", ".join(capabilities)
            )
        raise RoutingError("no model can be allocated: " + "; ".join(notes))


def _first_cloud(candidates: list[ModelMetadata]) -> ModelMetadata | None:
    clouds = [model for model in candidates if not model.local]
    if not clouds:
        return None
    return sorted(clouds, key=lambda model: (model.priority, model.id))[0]
