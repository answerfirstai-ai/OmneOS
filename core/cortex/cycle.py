"""One pass from the user's words through memory.

The cycle records the route. It does not call a model and it does not run a tool.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from core.models.policy import RoutePolicy

STAGES: tuple[str, ...] = (
    "user",
    "intent",
    "context",
    "world",
    "memory",
    "planning",
    "decision",
    "model_router",
    "execution",
    "observation",
    "verification",
    "memory_write",
)


class CortexCycle(BaseModel):
    """The stages OMNE recorded for one objective."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stages: list[str] = Field(default_factory=lambda: list(STAGES))
    completed: list[str] = Field(default_factory=list)
    intent: str
    intent_source: str
    complexity: str
    private: bool
    network: str
    gpu_overloaded: bool
    context_chars: int
    world_revision: int
    memory_notes: int
    plan: list[str] = Field(default_factory=list)
    decision: str
    policy: str
    policy_reason: str
    providers: list[str] = Field(default_factory=list)
    selected_model: str | None = None
    selected_provider: str | None = None


def make_cycle(
    *,
    intent: str,
    intent_source: str,
    complexity: str,
    private: bool,
    network: str,
    gpu_overloaded: bool,
    context_chars: int,
    world_revision: int,
    memory_notes: int,
    plan: list[str],
    decision: str,
    policy: RoutePolicy,
    selected_model: str | None,
    selected_provider: str | None,
    completed: list[str],
) -> CortexCycle:
    return CortexCycle(
        intent=intent,
        intent_source=intent_source,
        complexity=complexity,
        private=private,
        network=network,
        gpu_overloaded=gpu_overloaded,
        context_chars=context_chars,
        world_revision=world_revision,
        memory_notes=memory_notes,
        plan=plan,
        decision=decision,
        policy=policy.name,
        policy_reason=policy.reason,
        providers=list(policy.providers),
        selected_model=selected_model,
        selected_provider=selected_provider,
        completed=completed,
    )
