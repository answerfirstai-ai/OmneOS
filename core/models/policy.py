"""Choose a model class from the work, not from a fixed provider order.

The choice is local. It does not call a provider and it does not treat an
unknown network or an unknown GPU load as a measured fact.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core.compute.monitor import ResourceSnapshot
from core.intent.engine import Intent, request_is_private

Complexity = Literal["simple", "complex"]
NetworkFact = Literal["down", "unknown"]
PolicyName = Literal[
    "private_local",
    "offline_local",
    "gpu_cloud",
    "simple_local",
    "complex_cloud",
    "fallback",
]

_GPU_BUSY = 90.0
_COMPLEX_INTENTS = frozenset({"create_website", "diagnose_and_fix_network"})
_COMPLEX_WORDS = (
    "explain",
    "why",
    "design",
    "compare",
    "analyze",
    "analyse",
    "reason",
    "debug",
    "architect",
)


class RouteSituation(BaseModel):
    """Facts the router is allowed to use."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    complexity: Complexity
    private: bool
    network: NetworkFact
    gpu_overloaded: bool
    local_available: bool
    cloud_available: bool
    mock_available: bool


class RoutePolicy(BaseModel):
    """The ordered providers for one situation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: PolicyName
    providers: list[str] = Field(default_factory=list)
    reason: str
    prefer_strong: bool = False


def is_private_request(text: str) -> bool:
    return request_is_private(text)


def complexity_of(intent: Intent, text: str) -> Complexity:
    """Known host commands stay simple. Reasoning and coding do not.

    Workspace research is a local file search. Wording such as "why" or
    "design" does not send that plan to a cloud model.
    """

    if intent.intent == "research.workspace":
        return "simple"
    lowered = " ".join(text.lower().split())
    if intent.intent in _COMPLEX_INTENTS:
        return "complex"
    if "coding" in lowered or ("build" in lowered and "project" in lowered):
        return "complex"
    if any(re.search(rf"\b{word}\b", lowered) for word in _COMPLEX_WORDS):
        return "complex"
    return "simple"


def gpu_is_overloaded(snapshot: ResourceSnapshot) -> bool:
    """True only when a measured GPU reading is at least 90 percent."""

    usage = snapshot.gpu.usage_percent
    if usage is not None and usage >= _GPU_BUSY:
        return True
    total = snapshot.gpu.vram_total_mb
    used = snapshot.gpu.vram_used_mb
    if total is None or used is None or total <= 0:
        return False
    return (used / total) * 100 >= _GPU_BUSY


def choose_route(situation: RouteSituation) -> RoutePolicy:
    """Map a situation onto local, cloud, or the mock fallback."""

    local_chain = _with_mock(["local"], situation.mock_available)
    if situation.private:
        return RoutePolicy(
            name="private_local",
            providers=local_chain,
            reason="private work stays on a local model",
        )
    if situation.network == "down":
        return RoutePolicy(
            name="offline_local",
            providers=local_chain,
            reason="no network route is available, so the request stays local",
        )
    if situation.gpu_overloaded and situation.cloud_available:
        return RoutePolicy(
            name="gpu_cloud",
            providers=_with_mock(["nvidia"], situation.mock_available),
            reason="the measured GPU load is high, so the request uses a cloud model",
            prefer_strong=situation.complexity == "complex",
        )
    if situation.complexity == "simple":
        return RoutePolicy(
            name="simple_local",
            providers=local_chain,
            reason="a simple task uses a small local model",
        )
    if situation.cloud_available:
        return RoutePolicy(
            name="complex_cloud",
            providers=_with_mock(["nvidia", "local"], situation.mock_available),
            reason="complex reasoning uses the strong NVIDIA model",
            prefer_strong=True,
        )
    return RoutePolicy(
        name="fallback",
        providers=_with_mock(["local"], situation.mock_available) or ["mock"],
        reason="no cloud model is available, so the request uses the remaining route",
    )


def _with_mock(providers: list[str], mock_available: bool) -> list[str]:
    if mock_available and "mock" not in providers:
        return [*providers, "mock"]
    return list(providers)
