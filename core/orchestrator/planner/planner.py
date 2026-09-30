"""Deterministic planning rules.

The planner does not call a model and does not touch the host. It only
describes the graph the scheduler will run.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

from core.compute.requirements import ResourceRequirements
from core.orchestrator.task import PlannedCall

_RESOURCES = ResourceRequirements(ram_mb=64, vram_mb=0, cpu_threads=1, disk_mb=0, ram_known=True)
_WRITE_FILE = re.compile(r"^write file (?P<path>\S+) with content (?P<content>.+)$", re.IGNORECASE)
_TERMINAL = re.compile(r"^run terminal command (?P<command>.+)$", re.IGNORECASE)
_METRICS = {
    "cpu": "system.cpu",
    "memory": "system.memory",
    "gpu": "system.gpu",
    "disk": "system.disk",
    "network": "system.network",
    "processes": "process.list",
}


class PlanNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    objective: str
    capability: str
    calls: list[PlannedCall]
    depends_on: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    resources: ResourceRequirements = _RESOURCES
    exclusive: bool = False


def plan_objective(objective: str) -> list[PlanNode]:
    """Build a dependency graph for a user objective."""

    text = " ".join(objective.strip().split())
    lowered = text.lower()
    write = _WRITE_FILE.match(text)
    if write:
        return [_write_node(write.group("path"), write.group("content"))]
    terminal = _TERMINAL.match(text)
    if terminal:
        argv = terminal.group("command").split()
        return [
            PlanNode(
                key="terminal",
                objective=text,
                capability="software_development",
                calls=[
                    PlannedCall(kind="tool", tool_id="terminal.execute", arguments={"argv": argv})
                ],
                required_tools=["terminal.execute"],
                exclusive=True,
            )
        ]
    if "website" in lowered:
        return _website(text)
    if "git status" in lowered:
        return [_tool_node("git-status", text, "software_development", "git.status", {})]
    if lowered.startswith("research") or " research " in f" {lowered} ":
        return [_research_node(text, query=_search_query(text))]
    if "system resource" in lowered:
        return [_resource_node(text)]
    if "coding agent" in lowered or ("build" in lowered and "project" in lowered):
        return [_coding_node(text)]
    if "find" in lowered and "file" in lowered:
        return [
            _tool_node(
                "files",
                text,
                "software_development",
                "filesystem.search",
                {"query": ".", "path": "."},
            )
        ]
    if lowered.startswith("open http") or "browser" in lowered:
        url = _url(text) or "https://example.com"
        return [_tool_node("browser", text, "browser_navigation", "browser.open", {"url": url})]
    opened = re.match(r"^open (?P<name>.+)$", text, re.IGNORECASE)
    if opened is not None:
        name = opened.group("name").strip()
        if name and not any(character in name for character in "|&;<>`$()"):
            return [
                _tool_node(
                    "application",
                    text,
                    "application_launch",
                    "application.launch",
                    {"name": name},
                )
            ]
    metrics = [name for name in _METRICS if name in lowered]
    if metrics and ("independently" in lowered or "in parallel" in lowered) and len(metrics) >= 2:
        return [
            _tool_node(name, f"inspect {name}", _capability(name), _METRICS[name], {})
            for name in metrics
        ]
    if metrics:
        calls = [PlannedCall(kind="tool", tool_id=_METRICS[name], arguments={}) for name in metrics]
        return [
            PlanNode(
                key="inspect",
                objective=text,
                capability=_capability(metrics[0]),
                calls=calls,
                required_tools=[call.tool_id for call in calls],
            )
        ]
    return [
        PlanNode(
            key="respond",
            objective=text,
            capability="conversation",
            calls=[PlannedCall(kind="decide", prompt=text)],
        )
    ]


def _website(objective: str) -> list[PlanNode]:
    return [
        _research_node("Collect local sources for the website", query="website"),
        PlanNode(
            key="design",
            objective="Design the website",
            capability="software_development",
            calls=[PlannedCall(kind="model", prompt=f"design an html website for: {objective}")],
            depends_on=["research"],
        ),
        PlanNode(
            key="coding",
            objective="Write the website",
            capability="software_development",
            calls=[
                PlannedCall(
                    kind="model_then_write",
                    prompt=f"write html for: {objective}",
                    output_path="site/index.html",
                    tool_id="filesystem.write",
                )
            ],
            depends_on=["design"],
            required_tools=["filesystem.write"],
            exclusive=True,
        ),
        PlanNode(
            key="testing",
            objective="Verify the website file",
            capability="testing",
            calls=[
                PlannedCall(
                    kind="verify_file",
                    tool_id="filesystem.read",
                    arguments={"path": "site/index.html"},
                )
            ],
            depends_on=["coding"],
            required_tools=["filesystem.read"],
        ),
        PlanNode(
            key="review",
            objective="Review the website",
            capability="code_analysis",
            calls=[PlannedCall(kind="model", prompt="review the generated website html")],
            depends_on=["testing"],
        ),
    ]


def _research_node(objective: str, *, query: str) -> PlanNode:
    return PlanNode(
        key="research",
        objective=objective,
        capability="source_collection",
        calls=[
            PlannedCall(kind="tool", tool_id="filesystem.search", arguments={"query": query}),
            PlannedCall(kind="research_note"),
        ],
        required_tools=["filesystem.search"],
    )


def _resource_node(objective: str) -> PlanNode:
    names = ("cpu", "memory", "disk")
    calls = [PlannedCall(kind="tool", tool_id=_METRICS[name], arguments={}) for name in names]
    return PlanNode(
        key="resources",
        objective=objective,
        capability="system_inspection",
        calls=calls,
        required_tools=[call.tool_id for call in calls],
    )


def _coding_node(objective: str) -> PlanNode:
    return PlanNode(
        key="coding",
        objective=objective,
        capability="software_development",
        calls=[PlannedCall(kind="model", prompt=objective)],
    )


def _search_query(objective: str) -> str:
    skip = {"research", "the", "latest", "my", "a", "an", "for", "and", "of", "s"}
    words = [word for word in re.findall(r"[A-Za-z0-9]+", objective) if word.lower() not in skip]
    return words[0] if words else "notes"


def _write_node(path: str, content: str) -> PlanNode:
    return PlanNode(
        key="write",
        objective=f"write {path}",
        capability="software_development",
        calls=[
            PlannedCall(
                kind="tool",
                tool_id="filesystem.write",
                arguments={"path": path, "content": content},
            )
        ],
        required_tools=["filesystem.write"],
        exclusive=True,
    )


def _tool_node(
    key: str, objective: str, capability: str, tool_id: str, arguments: dict[str, object]
) -> PlanNode:
    return PlanNode(
        key=key,
        objective=objective,
        capability=capability,
        calls=[PlannedCall(kind="tool", tool_id=tool_id, arguments=arguments)],
        required_tools=[tool_id],
    )


def _capability(metric: str) -> str:
    if metric == "processes":
        return "process_inspection"
    return "system_inspection"


def _url(text: str) -> str | None:
    for token in text.split():
        if token.startswith("http://") or token.startswith("https://"):
            return token
    return None
