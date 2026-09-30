"""JSON routes for the local core API."""

from __future__ import annotations

from collections.abc import Mapping
from http import HTTPStatus

from core.memory.retrieval import MemoryAccessError
from core.mission.model import InvalidMissionTransition
from core.orchestrator.service import OMNE, mission_document, task_document

Payload = dict[str, object]


def route_get(
    runtime: OMNE | None, path: str, query: Mapping[str, list[str]]
) -> tuple[HTTPStatus, Payload]:
    if runtime is None:
        return HTTPStatus.SERVICE_UNAVAILABLE, {"error": "runtime_unavailable"}
    if path == "/desktop":
        return HTTPStatus.OK, runtime.desktop_view()
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
    if path == "/display":
        return HTTPStatus.OK, {"display": runtime.display_view()}
    if path == "/windowing":
        return HTTPStatus.OK, {"windowing": runtime.windowing_view()}
    if path == "/hardware":
        return HTTPStatus.OK, {"hardware": runtime.hardware_view()}
    if path == "/network":
        return HTTPStatus.OK, {"network": runtime.network_view()}
    if path == "/audio":
        return HTTPStatus.OK, {"audio": runtime.audio_view()}
    if path == "/input":
        return HTTPStatus.OK, {"input": runtime.input_view()}
    if path == "/storage":
        return HTTPStatus.OK, {"storage": runtime.storage_view()}
    if path == "/applications":
        return HTTPStatus.OK, {"applications": runtime.applications_view()}
    if path == "/voice":
        return HTTPStatus.OK, {"voice": runtime.voice_status()}
    if path == "/missions":
        missions = [mission_document(mission) for mission in runtime.list_missions()]
        return HTTPStatus.OK, {"missions": missions}
    if path == "/world":
        return HTTPStatus.OK, {"world": runtime.world_view()}
    if path == "/capabilities":
        return HTTPStatus.OK, {"capabilities": runtime.capability_views()}
    if path == "/workers":
        return HTTPStatus.OK, {"workers": runtime.worker_views()}
    if path == "/graph":
        return HTTPStatus.OK, runtime.graph_view()
    if path == "/questions":
        return HTTPStatus.OK, {"questions": runtime.questions()}
    if path == "/memory":
        return _memory(runtime, query)
    worker_id = _resource_id(path, "workers")
    if worker_id is not None and path.count("/") == 2:
        try:
            return HTTPStatus.OK, {"worker": runtime.get_worker(worker_id)}
        except KeyError:
            return HTTPStatus.NOT_FOUND, {"error": "not_found"}
    mission_id = _resource_id(path, "missions")
    if mission_id is not None and path.count("/") == 2:
        try:
            mission = runtime.get_mission(mission_id)
        except KeyError:
            return HTTPStatus.NOT_FOUND, {"error": "not_found"}
        return HTTPStatus.OK, {"mission": mission_document(mission)}
    trace_id = _resource_id(path, "traces")
    if trace_id is not None and path.count("/") == 2:
        try:
            return HTTPStatus.OK, runtime.trace_view(trace_id)
        except KeyError:
            return HTTPStatus.NOT_FOUND, {"error": "not_found"}
    verification_id = _resource_id(path, "verification")
    if verification_id is not None and path.count("/") == 2:
        try:
            return HTTPStatus.OK, {"verification": runtime.verification_view(verification_id)}
        except KeyError:
            return HTTPStatus.NOT_FOUND, {"error": "not_found"}
    task_id = _task_id(path)
    if task_id is not None and path.count("/") == 2:
        try:
            task = runtime.get_task(task_id)
        except KeyError:
            return HTTPStatus.NOT_FOUND, {"error": "not_found"}
        return HTTPStatus.OK, {"task": task_document(task)}
    return HTTPStatus.NOT_FOUND, {"error": "not_found"}


def route_post(
    runtime: OMNE | None, path: str, body: dict[str, object]
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
    if path == "/missions":
        objective = body.get("objective")
        if not isinstance(objective, str) or not objective.strip():
            return HTTPStatus.BAD_REQUEST, {"error": "objective must be a non-empty string"}
        dry_run = body.get("dry_run", False)
        if not isinstance(dry_run, bool):
            return HTTPStatus.BAD_REQUEST, {"error": "dry_run must be a boolean"}
        task = runtime.execute_sync(objective, dry_run=dry_run)
        return HTTPStatus.OK, {"task": task_document(task)}
    mission_id = _resource_id(path, "missions")
    if mission_id is not None:
        try:
            if path.endswith("/cancel"):
                mission = runtime.cancel_mission(mission_id)
            elif path.endswith("/pause"):
                mission = runtime.pause_mission(mission_id)
            elif path.endswith("/resume"):
                mission = runtime.resume_mission(mission_id)
            else:
                return HTTPStatus.NOT_FOUND, {"error": "not_found"}
        except KeyError:
            return HTTPStatus.NOT_FOUND, {"error": "not_found"}
        except (ValueError, InvalidMissionTransition) as exc:
            return HTTPStatus.BAD_REQUEST, {"error": str(exc)}
        return HTTPStatus.OK, {"mission": mission_document(mission)}
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


def _memory(runtime: OMNE, query: Mapping[str, list[str]]) -> tuple[HTTPStatus, Payload]:
    scope = _query_value(query, "scope")
    if not scope:
        return HTTPStatus.BAD_REQUEST, {"error": "scope is required"}
    scope_key = _query_value(query, "scope_key") or ""
    if not scope_key:
        return HTTPStatus.BAD_REQUEST, {"error": "scope_key is required"}
    raw_limit = _query_value(query, "limit") or "20"
    try:
        limit = int(raw_limit)
    except ValueError:
        return HTTPStatus.BAD_REQUEST, {"error": "limit must be an integer"}
    try:
        records = runtime.list_memory(scope=scope, scope_key=scope_key, limit=limit)
    except (MemoryAccessError, ValueError) as exc:
        return HTTPStatus.BAD_REQUEST, {"error": str(exc)}
    return HTTPStatus.OK, {"records": records}


def _resource_id(path: str, name: str) -> str | None:
    parts = [part for part in path.split("/") if part]
    if len(parts) >= 2 and parts[0] == name:
        return parts[1]
    return None


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
