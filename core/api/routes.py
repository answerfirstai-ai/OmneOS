"""JSON routes for the local core API."""

from __future__ import annotations

from collections.abc import Mapping
from http import HTTPStatus

from core.orchestrator.service import Jarvis, task_document

Payload = dict[str, object]


def route_get(
    runtime: Jarvis | None, path: str, query: Mapping[str, list[str]]
) -> tuple[HTTPStatus, Payload]:
    if runtime is None:
        return HTTPStatus.SERVICE_UNAVAILABLE, {"error": "runtime_unavailable"}
    if path == "/tasks":
        return HTTPStatus.OK, {"tasks": [task_document(task) for task in runtime.list_tasks()]}
    if path == "/events":
        after = _query_value(query, "after")
        events = [event.model_dump(mode="json") for event in runtime.list_events(after=after)]
        return HTTPStatus.OK, {"events": events}
    if path == "/agents":
        return HTTPStatus.OK, {"agents": runtime.agent_views()}
    if path == "/models":
        return HTTPStatus.OK, {"models": runtime.model_views()}
    if path == "/compute":
        return HTTPStatus.OK, {"compute": runtime.compute_status().model_dump()}
    if path == "/voice":
        return HTTPStatus.OK, {"voice": runtime.voice_status()}
    task_id = _task_id(path)
    if task_id is not None and path.count("/") == 2:
        try:
            task = runtime.get_task(task_id)
        except KeyError:
            return HTTPStatus.NOT_FOUND, {"error": "not_found"}
        return HTTPStatus.OK, {"task": task_document(task)}
    return HTTPStatus.NOT_FOUND, {"error": "not_found"}


def route_post(
    runtime: Jarvis | None, path: str, body: dict[str, object]
) -> tuple[HTTPStatus, Payload]:
    if path == "/health":
        return HTTPStatus.METHOD_NOT_ALLOWED, {"error": "method_not_allowed"}
    if runtime is None:
        return HTTPStatus.SERVICE_UNAVAILABLE, {"error": "runtime_unavailable"}
    if path == "/tasks":
        objective = body.get("objective")
        if not isinstance(objective, str) or not objective.strip():
            return HTTPStatus.BAD_REQUEST, {"error": "objective must be a non-empty string"}
        task = runtime.execute_sync(objective)
        return HTTPStatus.OK, {"task": task_document(task)}
    task_id = _task_id(path)
    if task_id is None:
        return HTTPStatus.NOT_FOUND, {"error": "not_found"}
    try:
        if path.endswith("/confirm"):
            approved = body.get("approved")
            if not isinstance(approved, bool):
                return HTTPStatus.BAD_REQUEST, {"error": "approved must be a boolean"}
            task = runtime.confirm_sync(task_id, approved=approved)
            return HTTPStatus.OK, {"task": task_document(task)}
        if path.endswith("/cancel"):
            task = runtime.cancel(task_id)
            return HTTPStatus.OK, {"task": task_document(task)}
    except KeyError:
        return HTTPStatus.NOT_FOUND, {"error": "not_found"}
    except ValueError as exc:
        return HTTPStatus.BAD_REQUEST, {"error": str(exc)}
    return HTTPStatus.NOT_FOUND, {"error": "not_found"}


def _task_id(path: str) -> str | None:
    parts = [part for part in path.split("/") if part]
    if len(parts) >= 2 and parts[0] == "tasks":
        return parts[1]
    return None


def _query_value(query: Mapping[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    return values[0]
