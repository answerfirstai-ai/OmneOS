import copy
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from core.harnesses.engine import Engine, validate_plan
from core.harnesses.store import Store

PLAN = {
    "name": "Research constellation",
    "objective": "Compare two options",
    "world": {"theme": "observatory", "color": "#abcdef"},
    "agents": [
        {
            "id": "research",
            "name": "Researcher",
            "role": "researcher",
            "instructions": "Analyze",
            "avatar": "researcher",
        },
        {
            "id": "review",
            "name": "Reviewer",
            "role": "reviewer",
            "instructions": "Review",
            "avatar": "guardian",
        },
    ],
    "tasks": [
        {
            "id": "a",
            "agent_id": "research",
            "title": "Analyze",
            "instructions": "Compare",
            "depends_on": [],
        },
        {
            "id": "b",
            "agent_id": "review",
            "title": "Review",
            "instructions": "Review analysis",
            "depends_on": ["a"],
        },
    ],
    "interval_minutes": 0,
}


class FakeModels:
    def __init__(self):
        self.calls = []
        self.error = False
        self.gate = None

    def public(self):
        return [{"id": "test", "label": "Test", "ready": True}]

    def call(self, model, messages, settings, json_mode=False):
        self.calls.append(messages)
        if self.gate:
            self.gate.wait(3)
        if self.error:
            raise ValueError("Provider unavailable")
        return (
            json.dumps({"action": "create", "message": "Created", "harness": PLAN})
            if json_mode
            else "A verified test artifact"
        )


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "test.sqlite"
        self.store = Store(self.path)
        self.models = FakeModels()
        self.engine = Engine(self.store, self.models)

    def tearDown(self):
        self.engine.stop.set()
        self.engine.pool.shutdown(wait=True)
        self.engine.planners.shutdown(wait=True)
        self.store.db.close()
        self.tmp.cleanup()

    def harness(self):
        h = validate_plan(copy.deepcopy(PLAN), "test") | {
            "id": "h1",
            "revision": 1,
            "status": "active",
            "created_at": time.time(),
            "updated_at": time.time(),
            "cycle": 1,
            "next_run": 0,
        }
        self.store.put("harness", h)
        return h

    def idle(self):
        deadline = time.monotonic() + 3
        while self.engine.active and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(self.engine.active)

    def test_cycle_rejected(self):
        p = copy.deepcopy(PLAN)
        p["tasks"][0]["depends_on"] = ["b"]
        with self.assertRaisesRegex(ValueError, "cycle"):
            validate_plan(p, "test")

    def test_invalid_dependency_and_duplicate_agent_rejected(self):
        p = copy.deepcopy(PLAN)
        p["tasks"][0]["depends_on"] = ["missing"]
        with self.assertRaises(ValueError):
            validate_plan(p, "test")
        p = copy.deepcopy(PLAN)
        p["agents"][1]["id"] = "research"
        with self.assertRaises(ValueError):
            validate_plan(p, "test")

    def test_token_reservation_atomic(self):
        outcomes = []

        def reserve():
            try:
                self.store.reserve(60, 100)
                outcomes.append(True)
            except ValueError:
                outcomes.append(False)

        threads = [threading.Thread(target=reserve) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sum(outcomes), 1)
        self.assertEqual(self.store.used(), 60)

    def test_dependency_outputs_and_completion(self):
        self.harness()
        self.engine.tick()
        self.idle()
        h = self.store.get("harness", "h1")
        self.assertEqual([t["status"] for t in h["tasks"]], ["complete", "pending"])
        self.engine.tick()
        self.idle()
        self.assertIn("A verified test artifact", self.models.calls[1][1]["content"])
        self.engine.tick()
        self.assertEqual(self.store.get("harness", "h1")["status"], "complete")
        self.assertEqual(len(self.store.all("artifact")), 2)

    def test_pause_blocks_new_work(self):
        self.harness()
        self.engine.control("h1", "pause")
        self.engine.tick()
        self.assertEqual(len(self.models.calls), 0)

    def test_failure_requires_attention_then_retry(self):
        self.harness()
        self.models.error = True
        self.engine.tick()
        self.idle()
        self.assertEqual(self.store.get("harness", "h1")["status"], "attention")
        self.models.error = False
        self.engine.control("h1", "resume")
        self.engine.tick()
        self.idle()
        self.assertEqual(self.store.get("harness", "h1")["tasks"][0]["status"], "complete")

    def test_stale_revision_cannot_overwrite_new_graph(self):
        h = self.harness()
        self.models.gate = threading.Event()
        self.engine.tick()
        h["revision"] = 2
        h["name"] = "Replacement"
        self.store.put("harness", h)
        self.models.gate.set()
        self.idle()
        current = self.store.get("harness", "h1")
        self.assertEqual(current["name"], "Replacement")
        self.assertEqual(current["tasks"][0]["status"], "pending")
        self.assertEqual(len(self.store.all("artifact")), 1)

    def test_restart_recovers_running_tasks(self):
        h = self.harness()
        h["tasks"][0]["status"] = "running"
        self.store.put("harness", h)
        other = Engine(self.store, self.models)
        self.assertEqual(self.store.get("harness", "h1")["tasks"][0]["status"], "pending")
        other.pool.shutdown()
        other.planners.shutdown()

    def test_recurring_wait_and_next_cycle(self):
        h = self.harness()
        h["interval_minutes"] = 5
        for t in h["tasks"]:
            t["status"] = "complete"
        self.store.put("harness", h)
        self.engine.tick()
        h = self.store.get("harness", "h1")
        self.assertEqual(h["status"], "waiting")
        self.engine.tick()
        self.assertEqual(len(self.models.calls), 0)
        h["next_run"] = time.time() - 1
        self.store.put("harness", h)
        self.engine.tick()
        self.idle()
        self.assertEqual(self.store.get("harness", "h1")["cycle"], 2)

    def test_core_plan_creates_real_graph(self):
        job = self.engine.submit("Build an analysis harness", "test")
        deadline = time.monotonic() + 3
        while (
            self.store.get("job", job["id"])["status"] not in ("complete", "failed")
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        self.assertEqual(self.store.get("job", job["id"])["status"], "complete")
        self.assertEqual(len(self.store.all("harness")), 1)


if __name__ == "__main__":
    unittest.main()
