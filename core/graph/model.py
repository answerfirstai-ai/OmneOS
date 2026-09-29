"""Nodes and edges for a future galaxy view.

The graph is derived from missions, tasks, workers, agents, and models that
exist. It does not invent relationships.
"""

from __future__ import annotations

from typing import Any


def build_graph(
    *,
    missions: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    workers: list[dict[str, Any]],
    agents: list[dict[str, Any]],
    models: list[dict[str, Any]],
    tools: list[str],
) -> dict[str, Any]:
    nodes: list[dict[str, str]] = [{"id": "core", "type": "core", "label": "OMNE Core"}]
    edges: list[dict[str, str]] = []
    for mission in missions:
        mission_id = str(mission["id"])
        nodes.append(
            {
                "id": mission_id,
                "type": "mission",
                "label": str(mission.get("objective", mission_id)),
            }
        )
        edges.append({"from": "core", "to": mission_id, "type": "owns"})
        task_id = mission.get("task_id")
        if isinstance(task_id, str):
            edges.append({"from": mission_id, "to": task_id, "type": "mission_task"})
    for task in tasks:
        task_id = str(task["id"])
        nodes.append({"id": task_id, "type": "task", "label": str(task.get("objective", task_id))})
        parent = task.get("parent_task")
        if isinstance(parent, str):
            edges.append({"from": parent, "to": task_id, "type": "parent"})
        for dependency in task.get("dependencies") or []:
            if isinstance(dependency, str):
                edges.append({"from": dependency, "to": task_id, "type": "dependency"})
        agent_id = task.get("assigned_agent")
        if isinstance(agent_id, str):
            edges.append({"from": task_id, "to": f"agent:{agent_id}", "type": "assigned_agent"})
        model_id = task.get("assigned_model")
        if isinstance(model_id, str):
            edges.append({"from": task_id, "to": f"model:{model_id}", "type": "assigned_model"})
    for agent in agents:
        agent_id = str(agent["id"])
        nodes.append({"id": f"agent:{agent_id}", "type": "agent", "label": agent_id})
    for model in models:
        model_id = str(model["id"])
        nodes.append({"id": f"model:{model_id}", "type": "model", "label": model_id})
    for worker in workers:
        worker_id = str(worker["worker_id"])
        nodes.append({"id": worker_id, "type": "worker", "label": str(worker["agent_id"])})
        edges.append(
            {"from": worker_id, "to": f"agent:{worker['agent_id']}", "type": "worker_agent"}
        )
        if worker.get("model"):
            edges.append(
                {"from": worker_id, "to": f"model:{worker['model']}", "type": "worker_model"}
            )
        if worker.get("current_task"):
            edges.append(
                {"from": str(worker["current_task"]), "to": worker_id, "type": "task_worker"}
            )
    for tool_id in tools:
        nodes.append({"id": f"tool:{tool_id}", "type": "tool", "label": tool_id})
    return {"nodes": nodes, "edges": edges}
