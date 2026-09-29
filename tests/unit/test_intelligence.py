"""Mission, world state, intent, routing, and the new API."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from tests.support import runtime_settings

from core.api.routes import route_get, route_post
from core.api.runtime import build_OMNE
from core.capabilities.registry import Capability, CapabilityRegistry
from core.context.builder import build_context
from core.decision.engine import DecisionEngine
from core.events.bus import EventBus
from core.events.replay import replay_events
from core.intent.engine import IntentEngine
from core.memory.database import MemoryDatabase
from core.memory.retrieval import AccessGrant
from core.memory.store import MemoryStore
from core.models.cache import CacheContext, ResponseCache
from core.models.providers.mock.provider import MockProvider
from core.models.types import GenerateRequest
from core.orchestrator.task import TaskStatus
from core.permissions.policies import PermissionRequest, decide
from core.recovery.policy import FailureClass, RecoveryAction, classify_failure, decide_recovery
from core.security.commands import CommandClass, classify_command
from core.verify.verifier import verify_observations
from core.workers.pool import WorkerPool, admit_worker
from core.world.state import WorldStateService


def test_mission_persists_through_completion_cancel_pause_and_failure(tmp_path: Path) -> None:
    omne = build_OMNE(runtime_settings(tmp_path))

    completed = omne.execute_sync("write file notes.txt with content hello from OMNE")
    mission = next(item for item in omne.list_missions() if item.objective == completed.objective)
    assert completed.status is TaskStatus.COMPLETED
    assert mission.status.value == "COMPLETED"
    assert mission.trace_id
    assert omne.get_mission(mission.id).objective.startswith("write file")

    waiting = omne.execute_sync("delete the project")
    asked = next(item for item in omne.list_missions() if item.objective == "delete the project")
    assert waiting.status is TaskStatus.WAITING
    assert asked.status.value == "WAITING"
    assert omne.questions()
    paused = omne.pause_mission(asked.id)
    assert paused.status.value == "PAUSED"
    resumed = omne.resume_mission(paused.id)
    assert resumed.status.value == "WAITING"
    cancelled = omne.cancel_mission(resumed.id)
    assert cancelled.status.value == "CANCELLED"

    denied = omne.execute_sync("run terminal command sudo reboot")
    failed = next(mission for mission in omne.list_missions() if "sudo reboot" in mission.objective)
    assert denied.status is TaskStatus.FAILED
    assert failed.status.value == "FAILED"
    assert not (tmp_path / "workspace" / "proof.txt").exists()


def test_world_revision_advances_when_the_cache_is_invalidated() -> None:
    builds = {"count": 0}

    def builder(revision: int) -> dict[str, object]:
        builds["count"] += 1
        return {"revision": revision, "missions": [{"id": "m", "status": "RUNNING"}]}

    world = WorldStateService(ttl_seconds=60)
    world.bind(builder)
    first = world.current()
    second = world.current()
    world.invalidate()
    third = world.current()

    assert first.revision == second.revision
    assert third.revision == first.revision + 1
    assert builds["count"] == 2


def test_intent_parses_known_text_and_asks_when_ambiguous() -> None:
    engine = IntentEngine()

    write = engine.interpret("write file notes.txt with content hello")
    assert write.intent == "filesystem.write"
    assert write.source == "deterministic"
    assert write.ambiguous is False

    question = engine.interpret("delete the project")
    assert question.ambiguous is True
    assert question.question

    modeled = engine.interpret(
        "please interpret this outage",
        allow_model=True,
        model_text="diagnose_and_fix_network",
    )
    assert modeled.intent == "diagnose_and_fix_network"
    assert modeled.source == "model"

    fallback = engine.interpret("remember this sentence")
    assert fallback.source == "fallback"
    assert engine.interpret("   ") is not None


def test_decision_engine_covers_the_execution_paths() -> None:
    engine = DecisionEngine()
    intent = IntentEngine()

    direct = engine.decide(
        intent.interpret("write file a.txt with content x"),
        mode="testing",
        local_available=False,
        cloud_available=True,
        cpu_wait=False,
        trace_id="t",
    )
    assert direct.decision == "DIRECT_TOOL"

    local = engine.decide(
        intent.interpret("remember this sentence"),
        mode="local",
        local_available=True,
        cloud_available=True,
        cpu_wait=False,
        trace_id="t",
    )
    assert local.decision == "LOCAL_MODEL"

    cloud = engine.decide(
        intent.interpret("remember this sentence"),
        mode="online",
        local_available=False,
        cloud_available=True,
        cpu_wait=False,
        trace_id="t",
    )
    assert cloud.decision == "CLOUD_MODEL"

    hybrid = engine.decide(
        intent.interpret("build a small website"),
        mode="hybrid",
        local_available=True,
        cloud_available=True,
        cpu_wait=False,
        trace_id="t",
    )
    assert hybrid.decision == "HYBRID"

    waiting = engine.decide(
        intent.interpret("remember this sentence"),
        mode="online",
        local_available=True,
        cloud_available=True,
        cpu_wait=True,
        trace_id="t",
    )
    assert waiting.decision == "WAIT"

    denied = engine.decide(
        intent.interpret("run terminal command sudo reboot"),
        mode="production",
        local_available=True,
        cloud_available=True,
        cpu_wait=False,
        trace_id="t",
    )
    assert denied.decision == "DENY"
    assert denied.trace_id == "t"


def test_capability_registry_rejects_duplicates_and_malformed_manifests(tmp_path: Path) -> None:
    registry = CapabilityRegistry()
    registry.register(
        Capability(id="tool:filesystem.read", name="read", description="read", provider="tool")
    )
    try:
        registry.register(
            Capability(id="tool:filesystem.read", name="read", description="again", provider="tool")
        )
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("duplicate capability was accepted")

    from core.agents.registry import AgentRegistry

    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "agent.toml").write_text("this is not toml = [\n", encoding="utf-8")
    (broken / "tools.toml").write_text("tools = []\n", encoding="utf-8")
    try:
        AgentRegistry().discover(broken, known_tools=set())
    except ValueError as exc:
        assert "invalid" in str(exc).lower() or "toml" in str(exc).lower()
    else:
        raise AssertionError("malformed agent manifest was accepted")

    omne = build_OMNE(runtime_settings(tmp_path))
    identifiers = {item["id"] for item in omne.capability_views()}
    assert "tool:filesystem.read" in identifiers
    assert "agent:coding" in identifiers


def test_worker_pool_honors_max_workers_and_cpu_wait() -> None:
    pool = WorkerPool()
    first = pool.start(
        agent_id="coding",
        max_workers=2,
        task_id="t1",
        mission_id="m",
        model_id=None,
        trace_id="trace",
    )
    second = pool.start(
        agent_id="coding",
        max_workers=2,
        task_id="t2",
        mission_id="m",
        model_id=None,
        trace_id="trace",
    )
    assert first.status == "RUNNING"
    assert second.status == "RUNNING"
    assert admit_worker(active=2, max_workers=2, cpu_percent=None) == "DENY"
    assert admit_worker(active=0, max_workers=2, cpu_percent=99) == "WAIT"
    assert admit_worker(active=0, max_workers=2, cpu_percent=None) == "ALLOW"
    closed = pool.complete("coding")
    assert closed is not None
    assert closed.status == "IDLE"
    assert pool.active("coding") == 1


def test_context_is_ranked_bounded_and_scope_limited(tmp_path: Path) -> None:
    store = MemoryStore(MemoryDatabase(tmp_path / "memory.sqlite"))
    grant = AccessGrant({"task"})
    store.add(grant, scope="task", scope_key="one", content="scheduler wire", source="mission")
    store.add(grant, scope="task", scope_key="one", content="unrelated note", source="mission")
    records = store.retrieve(grant, scope="task", scope_key="one", query="scheduler")
    built = build_context(
        request="scheduler",
        memories=[
            {"content": record.content, "scope": record.scope, "source": record.source}
            for record in records
        ],
        project_name="OMNE",
        world_revision=3,
        item_limit=2,
        char_limit=80,
    )
    rendered = built.render(char_limit=80)
    assert "scheduler" in rendered
    assert "unrelated" not in rendered
    assert len(rendered) <= 80
    assert built.revision == 3


def test_verification_pass_fail_and_inconclusive(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")
    passed = verify_observations(
        "ok",
        [{"kind": "tool", "tool_id": "filesystem.write", "output": {"path": "notes.txt"}}],
        workspace=tmp_path,
    )
    failed = verify_observations(
        "bad",
        [{"kind": "tool", "tool_id": "filesystem.write", "output": {"path": "missing.txt"}}],
        workspace=tmp_path,
    )
    unknown = verify_observations("none", [{"kind": "model", "text": "done"}], workspace=tmp_path)

    assert passed.status == "PASS"
    assert passed.evidence
    assert failed.status == "FAIL"
    assert unknown.status == "INCONCLUSIVE"


def test_trace_is_present_on_mission_events(tmp_path: Path) -> None:
    omne = build_OMNE(runtime_settings(tmp_path))
    omne.execute_sync("write file traced.txt with content traced")
    mission = omne.list_missions()[0]
    traced = [event for event in omne.list_events() if event.trace_id == mission.trace_id]
    assert traced
    assert any(event.type == "mission.created" for event in traced)
    view = omne.trace_view(mission.trace_id)
    assert view["missions"]
    folded = replay_events(omne.list_events())
    assert folded["side_effects"] is False
    assert mission.id in folded["missions"]


def test_command_classes_do_not_weaken_denies() -> None:
    assert CommandClass.READ_ONLY in classify_command(["ls"])
    assert CommandClass.PACKAGE_INSTALL in classify_command(["npm", "install", "leftpad"])
    result = decide(
        PermissionRequest(
            tool_id="terminal.execute",
            arguments={"argv": ["sudo", "reboot"]},
            grants={"terminal": ["workspace"]},
            environment="development",
            workspace_root="/tmp",
        )
    )
    assert result.decision.value == "DENY"
    assert "PRIVILEGED" in result.capability_classes


def test_dry_run_plans_without_side_effects(tmp_path: Path) -> None:
    omne = build_OMNE(runtime_settings(tmp_path))
    task = omne.execute_sync("write file dry.txt with content no", dry_run=True)
    assert task.status is TaskStatus.COMPLETED
    assert task.result is not None
    assert task.result["dry_run"] is True
    assert task.result["side_effects"] is False
    assert not (tmp_path / "workspace" / "dry.txt").exists()


def test_response_cache_hits_and_can_be_bypassed() -> None:
    import asyncio

    cache = ResponseCache()
    request = GenerateRequest(model="mock", prompt="same")
    response = asyncio.run(MockProvider().generate(request))
    context = CacheContext(world_revision=1, context_revision=4)
    assert cache.get("mock", request, context=context) is None
    cache.put("mock", request, response, context=context)
    assert cache.get("mock", request, context=context) is not None
    assert cache.get("mock", request, context=CacheContext(world_revision=2)) is None
    cache.bypass(reason="fresh")
    cache.invalidate()
    assert cache.get("mock", request, context=context) is None
    kinds = [str(item["type"]) for item in cache.events]
    assert "cache.hit" in kinds
    assert "cache.miss" in kinds
    assert "cache.bypass" in kinds
    assert "cache.invalidation" in kinds


def test_recovery_is_bounded_and_names_an_alternate() -> None:
    assert (
        decide_recovery(FailureClass.TOOL, retry_count=1, retry_limit=1, destructive=False)
        is RecoveryAction.ABORT
    )
    assert (
        decide_recovery(FailureClass.TOOL, retry_count=0, retry_limit=1, destructive=True)
        is RecoveryAction.ASK_USER
    )
    assert classify_failure("model_unavailable") is FailureClass.MODEL
    assert (
        decide_recovery(FailureClass.MODEL, retry_count=0, retry_limit=1, destructive=False)
        is RecoveryAction.DIFFERENT_MODEL
    )
    assert (
        decide_recovery(
            classify_failure("agent_failed"), retry_count=0, retry_limit=1, destructive=False
        )
        is RecoveryAction.DIFFERENT_AGENT
    )


def test_memory_migration_keeps_existing_rows(tmp_path: Path) -> None:
    path = tmp_path / "memory.sqlite"
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE records (
            id TEXT PRIMARY KEY,
            scope TEXT NOT NULL,
            scope_key TEXT NOT NULL,
            content TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        INSERT INTO records
        VALUES ('row', 'task', 'alpha', 'kept', '{}', '2020-01-01T00:00:00+00:00')
        """
    )
    connection.commit()
    connection.close()

    store = MemoryStore(MemoryDatabase(path))
    found = store.retrieve(AccessGrant({"task"}), scope="task", scope_key="alpha")
    assert [record.content for record in found] == ["kept"]
    assert found[0].trace_id == ""


def test_new_api_routes_and_rejects_malformed_input(tmp_path: Path) -> None:
    omne = build_OMNE(runtime_settings(tmp_path))
    omne.execute_sync("write file api.txt with content api")
    mission = omne.list_missions()[0]

    status, body = route_get(omne, "/missions", {})
    assert status.value == 200
    assert body["missions"]

    status, body = route_get(omne, f"/missions/{mission.id}", {})
    assert status.value == 200
    status, body = route_get(omne, "/world", {})
    assert status.value == 200
    assert body["world"]["revision"] >= 1
    status, body = route_get(omne, "/capabilities", {})
    assert status.value == 200
    status, body = route_get(omne, "/workers", {})
    assert status.value == 200
    status, body = route_get(omne, f"/traces/{mission.trace_id}", {})
    assert status.value == 200
    status, body = route_get(omne, "/memory", {})
    assert status.value == 400
    status, body = route_get(omne, "/memory", {"scope": ["nope"], "scope_key": ["x"]})
    assert status.value == 400
    status, body = route_get(omne, "/graph", {})
    assert "nodes" in body

    status, body = route_post(omne, "/missions", {"objective": ""})
    assert status.value == 400
    status, body = route_post(
        omne, "/missions", {"objective": "delete the project", "dry_run": "yes"}
    )
    assert status.value == 400
    assert route_get(None, "/world", {})[0].value == 503


def test_event_replay_does_not_execute_tools() -> None:
    bus = EventBus()
    bus.publish("mission.created", mission_id="m1", payload={"objective": "write file secret.txt"})
    folded = replay_events(bus.list_events())
    assert folded["missions"]["m1"] == "created"
    assert folded["side_effects"] is False
