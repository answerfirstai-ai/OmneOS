"""Capabilities advertised by tools, agents, and models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from core.agents.manifest import AgentManifest
from core.models.registry import ModelMetadata
from core.permissions.policies import TOOL_GRANTS


class Capability(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str
    description: str
    provider: str
    agent: str | None = None
    required_tools: list[str] = Field(default_factory=list)
    required_permissions: list[str] = Field(default_factory=list)
    risk: str = "low"
    latency_class: str = "unknown"
    privacy_class: str = "local"
    reliability: str = "unknown"
    cost: str = "unknown"


class CapabilityRegistry:
    """Collect capabilities. A duplicate id is rejected."""

    def __init__(self) -> None:
        self._items: dict[str, Capability] = {}

    def register(self, capability: Capability) -> Capability:
        if capability.id in self._items:
            raise ValueError(f"duplicate capability: {capability.id}")
        self._items[capability.id] = capability
        return capability

    def all(self) -> list[Capability]:
        return [self._items[key] for key in sorted(self._items)]

    def get(self, capability_id: str) -> Capability:
        try:
            return self._items[capability_id]
        except KeyError as exc:
            raise KeyError(f"unknown capability: {capability_id}") from exc


_HIGH_CAPABILITIES = frozenset(
    {
        "terminal.execute",
        "process.stop",
        "git.commit",
        "network.connect",
        "network.disconnect",
        "network.enable",
        "network.disable",
        "audio.set_default",
        "audio.set_volume",
        "audio.set_mute",
        "input.bind",
        "application.launch",
        "application.close",
        "browser.launch",
        "browser.screenshot",
        "browser.automate",
    }
)


def build_capability_registry(
    agents: list[AgentManifest],
    models: list[ModelMetadata],
) -> CapabilityRegistry:
    """Build the registry from manifests that are already loaded."""

    registry = CapabilityRegistry()
    for tool_id, grant in sorted(TOOL_GRANTS.items()):
        domain, value = grant
        risk = "high" if tool_id in _HIGH_CAPABILITIES else "low"
        registry.register(
            Capability(
                id=f"tool:{tool_id}",
                name=tool_id,
                description=f"{tool_id} through the tool gateway",
                provider="tool",
                required_tools=[tool_id],
                required_permissions=[f"{domain}:{value}"],
                risk=risk,
                privacy_class="local",
            )
        )
    for agent in agents:
        registry.register(
            Capability(
                id=f"agent:{agent.id}",
                name=agent.name,
                description=agent.description,
                provider="agent",
                agent=agent.id,
                required_tools=list(agent.tools),
                required_permissions=[
                    f"{domain}:{item}"
                    for domain, items in agent.permissions.items()
                    for item in items
                ],
                privacy_class="local",
            )
        )
    for model in models:
        registry.register(
            Capability(
                id=f"model:{model.id}",
                name=model.model_name,
                description=f"{model.provider} model {model.model_name}",
                provider="model",
                required_tools=[],
                privacy_class="local" if model.local or model.provider == "mock" else "cloud",
                cost=model.cost_input,
                latency_class=model.latency,
                reliability=model.reliability,
            )
        )
    return registry
