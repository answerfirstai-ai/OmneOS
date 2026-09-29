"""Discover and look up agent manifests."""

from __future__ import annotations

from pathlib import Path

from core.agents.manifest import AgentManifest, load_manifest


class AgentRegistry:
    """In-memory registry of validated agents."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentManifest] = {}
        self._disabled: set[str] = set()

    def discover(self, directory: Path, *, known_tools: set[str]) -> list[AgentManifest]:
        if not directory.is_dir():
            return []
        loaded: list[AgentManifest] = []
        for path in sorted(directory.rglob("*.toml")):
            loaded.append(self.register(load_manifest(path, known_tools=known_tools)))
        return loaded

    def register(self, manifest: AgentManifest) -> AgentManifest:
        if manifest.id in self._agents:
            raise ValueError(f"duplicate agent identifier: {manifest.id}")
        self._agents[manifest.id] = manifest
        return manifest

    def get(self, agent_id: str) -> AgentManifest:
        try:
            return self._agents[agent_id]
        except KeyError as exc:
            raise KeyError(f"unknown agent: {agent_id}") from exc

    def enable(self, agent_id: str) -> None:
        self.get(agent_id)
        self._disabled.discard(agent_id)

    def disable(self, agent_id: str) -> None:
        self.get(agent_id)
        self._disabled.add(agent_id)

    def is_enabled(self, agent_id: str) -> bool:
        self.get(agent_id)
        return agent_id not in self._disabled

    def enabled(self) -> list[AgentManifest]:
        return [agent for agent in self._agents.values() if agent.id not in self._disabled]

    def by_capability(self, capability: str) -> list[AgentManifest]:
        matches = [agent for agent in self.enabled() if capability in agent.capabilities]
        return sorted(matches, key=lambda agent: agent.id)

    def all(self) -> list[AgentManifest]:
        return list(self._agents.values())
