"""Agent manifests and lifecycle."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.conftest import ROOT

from core.agents.lifecycle import AgentLifecycle, AgentState, InvalidAgentTransition
from core.agents.manifest import load_manifest
from core.agents.registry import AgentRegistry
from core.events.bus import EventBus
from core.tools import build_registry


def test_shipped_agents_load() -> None:
    registry = AgentRegistry()
    loaded = registry.discover(ROOT / "agents", known_tools=build_registry().ids())

    assert {agent.id for agent in loaded} >= {"system", "coding", "research", "browser"}


def test_duplicate_agent_is_rejected(tmp_path: Path) -> None:
    source = ROOT / "agents" / "research" / "agent.toml"
    first = tmp_path / "one"
    second = tmp_path / "two"
    first.mkdir()
    second.mkdir()
    (first / "agent.toml").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    (second / "agent.toml").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    registry = AgentRegistry()
    registry.discover(first, known_tools={"filesystem.read", "filesystem.search"})

    with pytest.raises(ValueError, match="duplicate"):
        registry.discover(second, known_tools={"filesystem.read", "filesystem.search"})


def test_unknown_tool_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "agent.toml"
    path.write_text(
        "\n".join(
            [
                'id = "custom"',
                'name = "Custom"',
                'version = "0.1.0"',
                'description = "Invalid tool list."',
                'capabilities = ["research"]',
                'tools = ["not.a.tool"]',
                "[permissions]",
                "[lifecycle]",
                "persistent = false",
                'startup = "on_demand"',
                'shutdown = "after_task"',
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown tools"):
        load_manifest(path, known_tools=set())


def test_lifecycle_rejects_an_illegal_edge() -> None:
    lifecycle = AgentLifecycle(EventBus())
    lifecycle.register("research")

    with pytest.raises(InvalidAgentTransition):
        lifecycle.transition("research", AgentState.RUNNING)
