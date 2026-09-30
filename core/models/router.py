"""Deterministic model routing."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from core.compute.allocation import AllocationDecision, AllocationRequest, allocate
from core.compute.monitor import ResourceSnapshot
from core.models.policy import RoutePolicy
from core.models.registry import ModelMetadata, ModelRegistry


class Route(BaseModel):
    """The model selected for a request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: ModelMetadata
    decision: AllocationDecision
    reason: str


class RouteChoice(BaseModel):
    """A capability-aware route, including the models that were not selected."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: ModelMetadata | None = None
    reason: str
    fallbacks: list[str] = []
    estimated_resources: dict[str, str] = {}
    estimated_cost: str = "unknown"
    decision: str


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

    def choose(
        self,
        capabilities: list[str],
        snapshot: ResourceSnapshot,
        *,
        mode: str,
        available: set[str] | None = None,
    ) -> RouteChoice:
        """Select a model for ``mode``.

        ``select`` stays priority-first so existing callers keep the mock route.
        This method applies the execution mode and skips models that are not
        actually available. Mock does not win in production. A missing local
        model is not reported as loaded.
        """

        required = set(capabilities)
        candidates = [
            model for model in self._registry.enabled() if required <= set(model.capabilities)
        ]
        if available is not None:
            candidates = [model for model in candidates if model.id in available]
        if mode == "production":
            candidates = [model for model in candidates if model.provider != "mock"]
        if mode in {"offline", "local"}:
            candidates = [model for model in candidates if model.local]
        candidates.sort(key=lambda model: (0 if model.local else 1, model.priority, model.id))
        if mode == "local":
            candidates.sort(key=lambda model: (model.priority, model.id))
        if not candidates:
            return RouteChoice(
                reason=f"no available model satisfies {mode}",
                decision="DEFER",
            )
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
            fallbacks = [item.id for item in candidates if item.id != model.id]
            if decision is AllocationDecision.ALLOW:
                return _choice(model, decision.value, reason, fallbacks)
            if decision is AllocationDecision.USE_CLOUD:
                cloud = _first_cloud(candidates)
                if cloud is not None and mode not in {"offline", "local"}:
                    others = [item.id for item in candidates if item.id != cloud.id]
                    return _choice(cloud, decision.value, reason, others)
            notes.append(f"{model.id}: {decision.value}")
        return RouteChoice(
            reason="; ".join(notes) if notes else "no model can be allocated",
            fallbacks=[model.id for model in candidates],
            decision="WAIT" if notes and all("WAIT" in note for note in notes) else "DENY",
        )

    def order(
        self,
        capabilities: list[str],
        snapshot: ResourceSnapshot,
        *,
        route: str,
        available: set[str] | None = None,
        allow_mock: bool = True,
        preferred_model: str | None = None,
        policy: RoutePolicy | None = None,
    ) -> list[ModelMetadata]:
        """Return models for ``route`` that fit the snapshot.

        ``auto`` without a policy prefers NVIDIA, then a local model, then
        mock. A cortex policy reorders that list. An explicit route does not
        substitute a different provider.
        """

        if route not in {"auto", "mock", "local", "nvidia"}:
            raise RoutingError(f"unknown model route {route}")
        required = set(capabilities)
        candidates = [
            model for model in self._registry.enabled() if required <= set(model.capabilities)
        ]
        if available is not None:
            candidates = [model for model in candidates if model.id in available]
        if route == "mock":
            candidates = [model for model in candidates if model.provider == "mock"]
        elif route == "local":
            candidates = [model for model in candidates if model.provider == "local"]
        elif route == "nvidia":
            candidates = [model for model in candidates if model.provider == "nvidia"]
        else:
            if policy is not None:
                allowed = set(policy.providers)
            else:
                allowed = {"nvidia", "local", "mock"} if allow_mock else {"nvidia", "local"}
            candidates = [model for model in candidates if model.provider in allowed]
        preferred_known = bool(
            preferred_model
            and any(
                model.provider == "nvidia" and model.model_name == preferred_model
                for model in candidates
            )
        )
        if policy is not None and route == "auto":
            ranked = sorted(
                candidates,
                key=lambda model: _policy_key(
                    model,
                    policy,
                    preferred_model=preferred_model,
                    preferred_known=preferred_known,
                ),
            )
        else:
            ranked = sorted(
                candidates,
                key=lambda model: _route_key(
                    model,
                    route=route,
                    preferred_model=preferred_model,
                    preferred_known=preferred_known,
                ),
            )
        fitted: list[ModelMetadata] = []
        for model in ranked:
            decision, _reason = allocate(
                snapshot,
                AllocationRequest(
                    requirements=model.requirements,
                    local=model.local,
                    cloud_available=any(not item.local for item in ranked),
                ),
            )
            if decision is AllocationDecision.ALLOW:
                fitted.append(model)
        return fitted


def _choice(
    model: ModelMetadata,
    decision: str,
    reason: str,
    fallbacks: list[str],
) -> RouteChoice:
    ram = str(model.requirements.ram_mb) if model.requirements.ram_known else "unknown"
    vram = str(model.requirements.vram_mb) if model.requirements.vram_known else "unknown"
    return RouteChoice(
        model=model,
        reason=reason,
        fallbacks=fallbacks,
        estimated_resources={"ram_mb": ram, "vram_mb": vram},
        estimated_cost=model.cost_input,
        decision=decision,
    )


def _policy_key(
    model: ModelMetadata,
    policy: RoutePolicy,
    *,
    preferred_model: str | None,
    preferred_known: bool,
) -> tuple[int, int, int, str]:
    provider_rank = policy.providers.index(model.provider)
    name_rank = 1
    if policy.prefer_strong and model.provider == "nvidia":
        named = bool(preferred_model) and model.model_name == preferred_model
        fallback = (not preferred_known) and model.id == "nvidia-reasoning"
        plain = preferred_model is None and model.id == "nvidia-reasoning"
        name_rank = 0 if named or fallback or plain else 1
    return (provider_rank, name_rank, model.priority, model.id)


def _route_key(
    model: ModelMetadata,
    *,
    route: str,
    preferred_model: str | None,
    preferred_known: bool,
) -> tuple[int, int, int, str]:
    provider_rank = {"nvidia": 0, "local": 1, "mock": 2}.get(model.provider, 9)
    if route != "auto":
        provider_rank = 0
    preferred = bool(preferred_model) and model.provider == "nvidia"
    named = model.model_name == preferred_model
    fallback = not preferred_known and model.id == "nvidia-reasoning"
    name_rank = 0 if preferred and (named or fallback) else 1
    return (provider_rank, name_rank, model.priority, model.id)


def _first_cloud(candidates: list[ModelMetadata]) -> ModelMetadata | None:
    clouds = [model for model in candidates if not model.local]
    if not clouds:
        return None
    return sorted(clouds, key=lambda model: (model.priority, model.id))[0]
