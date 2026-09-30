"""Launcher sentences become real plans. They do not call NVIDIA."""

from __future__ import annotations

from core.orchestrator.planner.planner import plan_objective


def test_research_models_searches_for_nvidia() -> None:
    plan = plan_objective("Research NVIDIA's latest AI models")

    assert plan[0].key == "research"
    assert plan[0].capability == "source_collection"
    assert plan[0].calls[0].arguments["query"] == "NVIDIA"
    assert plan[0].calls[1].kind == "research_note"


def test_open_chrome_launches_the_application() -> None:
    plan = plan_objective("Open Chrome")

    assert plan[0].calls[0].tool_id == "application.launch"
    assert plan[0].calls[0].arguments["name"] == "Chrome"


def test_system_resources_read_cpu_memory_and_disk() -> None:
    plan = plan_objective("Check system resources")

    assert [call.tool_id for call in plan[0].calls] == [
        "system.cpu",
        "system.memory",
        "system.disk",
    ]


def test_coding_requests_use_the_coding_agent_capability() -> None:
    assert plan_objective("Start coding agent")[0].capability == "software_development"
    assert plan_objective("Build my project")[0].capability == "software_development"


def test_find_files_searches_the_workspace() -> None:
    plan = plan_objective("Find my files")

    assert plan[0].calls[0].tool_id == "filesystem.search"
    assert plan[0].calls[0].arguments == {"query": ".", "path": "."}


def test_a_website_still_researches_local_sources() -> None:
    plan = plan_objective("build a small website")

    assert plan[0].calls[0].arguments["query"] == "website"
