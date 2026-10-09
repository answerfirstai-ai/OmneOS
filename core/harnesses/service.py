"""Authenticated command-center API mounted inside the existing OMNE server."""

from __future__ import annotations

import os
import secrets
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.harnesses.engine import Engine, validate_plan
from core.harnesses.models import OMNEModels
from core.harnesses.store import Store, new_id

if TYPE_CHECKING:
    from core.orchestrator.service import OMNE


class HubService:
    def __init__(self, runtime: OMNE, data_dir: Path) -> None:
        self.runtime = runtime
        self.token = access_token(data_dir)
        self.store = Store(data_dir / "harnesses.sqlite", emit=runtime.publish_harness_event)
        self.engine = Engine(self.store, OMNEModels(runtime, self.store))
        self._telemetry: dict[str, Any] = {}
        self._telemetry_until = 0.0
        self._telemetry_lock = threading.Lock()
        self.engine.start()

    def close(self) -> None:
        self.engine.close()

    def get(self, path: str, after: int = 0) -> dict[str, Any]:
        if path == "state":
            harnesses = self.store.all("harness")
            for h in harnesses:
                for task in h["tasks"]:
                    task.pop("output", None)
                    task.pop("instructions", None)
                for agent in h["agents"]:
                    agent.pop("instructions", None)
            with self._telemetry_lock:
                if time.monotonic() >= self._telemetry_until:
                    self._telemetry = self.runtime.compute_status().model_dump(mode="json")
                    self._telemetry_until = time.monotonic() + 10
                telemetry = self._telemetry
            return {
                "harnesses": harnesses,
                "models": self.engine.models.public(),
                "settings": self.engine.settings,
                "events": self.store.events(after),
                "jobs": self.store.recent("job"),
                "usage": {"tokens": self.store.used(), "active_agents": len(self.engine.active)},
                "hardware": telemetry,
                "integration": "OMNE OS",
                "capabilities": ["planning", "agent_graphs", "artifacts", "recurring_runs"],
            }
        if path.startswith("artifacts/"):
            id = path.split("/", 1)[1]
            return {"artifacts": self.store.artifacts(id)}
        if path.startswith("export/"):
            exported = self.store.get("harness", path.split("/", 1)[1])
            if exported is not None:
                return exported
        raise KeyError("Not found")

    def post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        if path == "prompt":
            prompt, context = data.get("prompt", ""), data.get("context", "")
            history = data.get("history", [])
            if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 16000:
                raise ValueError("Prompt must contain 1-16000 characters")
            if (
                not isinstance(context, str)
                or len(context) > 40000
                or not isinstance(history, list)
            ):
                raise ValueError("Invalid attached context or history")
            return self.engine.submit(prompt, str(data.get("model_id", "")), context, history)
        if path == "settings":
            daily, concurrency = int(data["daily_tokens"]), int(data["concurrency"])
            if not 1000 <= daily <= 100000000 or not 1 <= concurrency <= 16:
                raise ValueError("Invalid resource limits")
            if not isinstance(data.get("eco_mode"), bool):
                raise ValueError("Eco mode must be a boolean")
            self.engine.settings = {
                "id": "global",
                "daily_tokens": daily,
                "concurrency": concurrency,
                "eco_mode": data["eco_mode"],
            }
            return self.store.put("settings", self.engine.settings)
        if path == "control":
            return self.engine.control(
                str(data.get("id", "")), str(data.get("action", "")), data.get("model_id")
            )
        if path == "import":
            model = str(data.get("model_id", ""))
            if model not in {m["id"] for m in self.engine.models.public()}:
                raise ValueError("Choose a configured OMNE model")
            spec = validate_plan(data.get("harness"), model)
            h = spec | {
                "id": new_id("h"),
                "revision": 1,
                "status": "paused",
                "created_at": time.time(),
                "updated_at": time.time(),
                "cycle": 1,
                "next_run": 0,
            }
            self.store.put("harness", h)
            self.store.event("Imported " + h["name"] + " in paused state.", h["id"])
            return h
        raise KeyError("Not found")


def access_token(data_dir: Path) -> str:
    value = os.environ.get("OMNE_HUB_TOKEN", "")
    path = data_dir / "hub-token"
    if not value:
        data_dir.mkdir(parents=True, exist_ok=True)
        if path.exists():
            value = path.read_text().strip()
        else:
            value = secrets.token_urlsafe(32)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as output:
                output.write(value)
    if len(value) < 24:
        raise ValueError("OMNE_HUB_TOKEN must contain at least 24 characters")
    return value
