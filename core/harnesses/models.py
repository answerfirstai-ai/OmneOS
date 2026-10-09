"""Bridge to OMNE's model registry; no second provider or secret configuration."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import TYPE_CHECKING, Any

from core.harnesses.store import Store
from omne.secrets.redact import redact_text

if TYPE_CHECKING:
    from core.orchestrator.service import OMNE


class OMNEModels:
    def __init__(self, runtime: OMNE, store: Store) -> None:
        self.runtime = runtime
        self.store = store
        self._cached: list[dict[str, Any]] = []
        self._expires = 0.0
        self._lock = threading.Lock()
        self._inference_locks: dict[str, threading.Lock] = {}

    def public(self) -> list[dict[str, Any]]:
        # Native model health can probe adapters; do not repeat probes for every UI poll.
        with self._lock:
            if time.monotonic() >= self._expires:
                self._cached = [
                    {
                        "id": m["id"],
                        "label": f"{m['provider']} · {m['model_name']}",
                        "model": m["model_name"],
                        "local": m["local"],
                        "ready": m["availability"] == "available" and m["provider"] != "mock",
                    }
                    for m in self.runtime.model_views()
                ]
                self._expires = time.monotonic() + 10
            return [
                {
                    "id": "auto",
                    "label": "OMNE · adaptive routing",
                    "model": "auto",
                    "local": False,
                    "ready": any(m["ready"] for m in self._cached),
                },
                *self._cached,
            ]

    def call(
        self,
        model_id: str,
        messages: list[dict[str, str]],
        settings: dict[str, Any],
        json_mode: bool = False,
    ) -> str:
        del json_mode  # The planner's system prompt carries its schema for all native providers.
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        prompt = json.dumps([m for m in messages if m["role"] != "system"], ensure_ascii=False)
        system, prompt = redact_text(system), redact_text(prompt)
        # Native providers currently expose no common max-output-token parameter.
        # Retain this conservative reserve if usage is absent; this is a soft token guard.
        reserved = len((system + prompt).encode()) + 8192
        with self._lock:
            inference_lock = self._inference_locks.setdefault(model_id, threading.Lock())
        # Local engines own one active request; serialize by model rather than racing them.
        with inference_lock:
            day = self.store.reserve(reserved, int(settings["daily_tokens"]))
            response = asyncio.run(self.runtime.generate_harness(model_id, prompt, system))
            usage = response.usage
            if usage.input_tokens is not None and usage.output_tokens is not None:
                self.store.settle(day, reserved, usage.input_tokens + usage.output_tokens)
            return response.text
