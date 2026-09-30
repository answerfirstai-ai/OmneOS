"""Run local models as system resources.

Load asks the compute allocator whether a resident model fits, records the
worker that requested the load, and publishes lifecycle events. The router
reads ``available_ids``. Engines are adapters, so Core is not tied to one
model server. Nothing here downloads weights or assumes a GPU vendor.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from core.compute.allocation import AllocationDecision, AllocationRequest, allocate
from core.compute.monitor import ResourceSnapshot
from core.events.bus import EventBus
from core.models.engines.base import ModelEngine
from core.models.lifecycle import (
    LOADED_STATES,
    SELECTABLE_STATES,
    ModelLifecycle,
    ModelLifecycleState,
)
from core.models.registry import ModelMetadata, ModelRegistry
from core.models.types import GenerateChunk, GenerateRequest, ProviderError

WorkerLookup = Callable[[str], bool]
Availability = Callable[[ModelMetadata], bool]


class SnapshotSource(Protocol):
    """The compute monitor, or a test double with the same read."""

    def snapshot(self) -> ResourceSnapshot:
        """Return one resource sample."""


class InferenceResult(BaseModel):
    """One inference attempt, including a refusal before any token is produced."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str
    request_id: str = ""
    text: str = ""
    performed: bool
    cancelled: bool = False
    state: str
    reason: str
    code: str


@dataclass
class _Session:
    model_id: str
    engine: str | None
    resident: bool
    gpu: str
    worker_id: str | None = None
    request_id: str | None = None
    failure: str | None = None


@dataclass
class _Running:
    engine: ModelEngine
    request: GenerateRequest
    request_id: str
    model_id: str


class ModelRuntime:
    """Load, run, and unload models through a selected engine."""

    def __init__(
        self,
        *,
        registry: ModelRegistry,
        lifecycle: ModelLifecycle,
        monitor: SnapshotSource,
        events: EventBus,
        engines: Mapping[str, ModelEngine],
        workers: WorkerLookup | None = None,
    ) -> None:
        self._registry = registry
        self._lifecycle = lifecycle
        self._monitor = monitor
        self._events = events
        self._engines = dict(engines)
        self._workers = workers
        self._sessions: dict[str, _Session] = {}
        self._requests: dict[str, str] = {}
        self._cancel_ids: set[str] = set()
        self._lock = threading.Lock()

    def prepare(self, *, available: Availability) -> None:
        """Register each enabled model from configuration and engine residency."""

        for model in self._registry.enabled():
            configured = available(model)
            engine_name = self._engine_name(model)
            resident = False
            gpu = "unknown"
            failure: str | None = None
            if engine_name is None:
                usable = configured
                if not configured:
                    failure = "model provider is not configured"
            else:
                usable, resident, gpu, failure = self._probe(engine_name, model, configured)
            self._lifecycle.register(model, available=usable)
            self._sessions[model.id] = _Session(
                model_id=model.id,
                engine=engine_name,
                resident=resident,
                gpu=gpu,
                failure=failure,
            )

    def load(self, model_id: str, *, worker_id: str | None = None) -> dict[str, object]:
        """Map a resident model. A refusal does not emit ``model.loaded``."""

        model = self._registry.get(model_id)
        snapshot = self._monitor.snapshot()
        with self._lock:
            session = self._require(model_id)
            refusal = self._load_refusal(model, session, worker_id, snapshot)
            if refusal is not None:
                return refusal
            self._lifecycle.transition(model_id, ModelLifecycleState.LOADING)
            engine_name = session.engine
        engine = self._engines[engine_name] if engine_name is not None else None
        self._emit(
            "model.loading",
            model_id,
            worker_id,
            {"lifecycle": "LOADING", "engine": engine_name},
        )
        if engine is None:
            return self._fail_load(model_id, session, "model engine is missing", "unavailable")
        try:
            engine.load(model.model_name)
        except ProviderError as exc:
            return self._fail_load(model_id, session, str(exc), exc.code)
        with self._lock:
            self._lifecycle.transition(model_id, ModelLifecycleState.LOADED)
            session.failure = None
            session.worker_id = worker_id
        self._emit(
            "model.loaded",
            model_id,
            worker_id,
            {
                "lifecycle": "LOADED",
                "engine": engine_name,
                "context_window": model.context_window,
                "ram_mb": _known(model.requirements.ram_mb, model.requirements.ram_known),
                "vram_mb": _known(model.requirements.vram_mb, model.requirements.vram_known),
                "gpu": session.gpu,
            },
        )
        return _status(
            model_id,
            performed=True,
            state=ModelLifecycleState.LOADED.value,
            reason="model is resident",
            code="ok",
            engine=engine_name,
        )

    def unload(self, model_id: str) -> dict[str, object]:
        """Release a mapping. Installed files stay where the engine left them."""

        model = self._registry.get(model_id)
        with self._lock:
            session = self._require(model_id)
            state = self._lifecycle.state(model_id)
            if session.engine is None:
                return _status(
                    model_id,
                    performed=False,
                    state=state.value,
                    reason="cloud models are not loaded as local weights",
                    code="cloud",
                    engine=None,
                )
            request_id = session.request_id if state is ModelLifecycleState.RUNNING else None
            if request_id is None and state not in {
                ModelLifecycleState.LOADED,
                ModelLifecycleState.IDLE,
                ModelLifecycleState.FAILED,
            }:
                return _status(
                    model_id,
                    performed=False,
                    state=state.value,
                    reason=f"model is {state.value.lower()}",
                    code="not_loaded",
                    engine=session.engine,
                )
            engine = self._engines[session.engine]
            worker_id = session.worker_id
            engine_name = session.engine
        if request_id is not None:
            self.cancel(request_id)
        with self._lock:
            state = self._lifecycle.state(model_id)
            if state not in {
                ModelLifecycleState.LOADED,
                ModelLifecycleState.IDLE,
                ModelLifecycleState.FAILED,
                ModelLifecycleState.RUNNING,
            }:
                return _status(
                    model_id,
                    performed=False,
                    state=state.value,
                    reason=f"model is {state.value.lower()}",
                    code="not_loaded",
                    engine=engine_name,
                )
            self._lifecycle.transition(model_id, ModelLifecycleState.UNLOADING)
        self._emit(
            "model.unloading",
            model_id,
            worker_id,
            {"lifecycle": "UNLOADING", "engine": engine_name},
        )
        try:
            engine.unload(model.model_name)
        except ProviderError as exc:
            with self._lock:
                self._lifecycle.transition(model_id, ModelLifecycleState.FAILED)
                session.failure = str(exc)
            self._emit(
                "model.failed",
                model_id,
                worker_id,
                {"lifecycle": "FAILED", "engine": engine_name, "reason": str(exc)},
            )
            return _status(
                model_id,
                performed=False,
                state=ModelLifecycleState.FAILED.value,
                reason=str(exc),
                code=exc.code,
                engine=engine_name,
            )
        with self._lock:
            self._lifecycle.transition(model_id, ModelLifecycleState.AVAILABLE)
            session.worker_id = None
            session.request_id = None
            session.failure = None
        self._emit(
            "model.unloaded",
            model_id,
            None,
            {"lifecycle": "AVAILABLE", "engine": engine_name},
        )
        return _status(
            model_id,
            performed=True,
            state=ModelLifecycleState.AVAILABLE.value,
            reason="model mapping was released",
            code="ok",
            engine=engine_name,
        )

    async def generate(
        self,
        model_id: str,
        prompt: str,
        *,
        system: str | None = None,
        worker_id: str | None = None,
        request_id: str | None = None,
    ) -> InferenceResult:
        """Run one request. The model must already be loaded."""

        self._registry.get(model_id)
        started = self._begin(
            model_id,
            prompt,
            system=system,
            worker_id=worker_id,
            request_id=request_id,
        )
        if isinstance(started, InferenceResult):
            return started
        try:
            response = await started.engine.generate(started.request, started.request_id)
        except asyncio.CancelledError:
            self._finish(
                started.model_id,
                started.request_id,
                outcome="cancelled",
                text="",
                reason="inference was cancelled",
            )
            raise
        except ProviderError as exc:
            outcome = "cancelled" if exc.code == "cancelled" else "failed"
            return self._finish(
                started.model_id,
                started.request_id,
                outcome=outcome,
                text="",
                reason=str(exc),
            )
        if started.request_id in self._cancel_ids:
            return self._finish(
                started.model_id,
                started.request_id,
                outcome="cancelled",
                text="",
                reason="inference was cancelled",
            )
        return self._finish(
            started.model_id,
            started.request_id,
            outcome="ok",
            text=response.text,
            reason="completed",
        )

    async def stream(
        self,
        model_id: str,
        prompt: str,
        *,
        system: str | None = None,
        worker_id: str | None = None,
        request_id: str | None = None,
    ) -> AsyncIterator[GenerateChunk]:
        """Yield chunks. Cancellation stops the iterator between chunks."""

        self._registry.get(model_id)
        started = self._begin(
            model_id,
            prompt,
            system=system,
            worker_id=worker_id,
            request_id=request_id,
        )
        if isinstance(started, InferenceResult):
            raise ProviderError(started.reason, code=started.code, provider="model-runtime")
        try:
            async for chunk in started.engine.stream(started.request, started.request_id):
                if started.request_id in self._cancel_ids:
                    self._finish(
                        started.model_id,
                        started.request_id,
                        outcome="cancelled",
                        text="",
                        reason="inference was cancelled",
                    )
                    return
                yield chunk
        except asyncio.CancelledError:
            self._finish(
                started.model_id,
                started.request_id,
                outcome="cancelled",
                text="",
                reason="inference was cancelled",
            )
            raise
        except ProviderError as exc:
            outcome = "cancelled" if exc.code == "cancelled" else "failed"
            self._finish(
                started.model_id,
                started.request_id,
                outcome=outcome,
                text="",
                reason=str(exc),
            )
            raise
        if started.request_id in self._cancel_ids:
            self._finish(
                started.model_id,
                started.request_id,
                outcome="cancelled",
                text="",
                reason="inference was cancelled",
            )
            return
        self._finish(
            started.model_id,
            started.request_id,
            outcome="ok",
            text="",
            reason="completed",
        )

    def cancel(self, request_id: str) -> dict[str, object]:
        """Stop one in-flight request and return the model to idle."""

        with self._lock:
            model_id = self._requests.get(request_id)
            if model_id is None:
                return {
                    "performed": False,
                    "request_id": request_id,
                    "reason": "request is not running",
                    "code": "not_running",
                }
            self._cancel_ids.add(request_id)
            session = self._sessions[model_id]
            engine_name = session.engine
            running = self._lifecycle.state(model_id) is ModelLifecycleState.RUNNING
        if engine_name is not None:
            self._engines[engine_name].cancel(request_id)
        if running:
            finished = self._finish(
                model_id,
                request_id,
                outcome="cancelled",
                text="",
                reason="inference was cancelled",
            )
            return {
                "performed": True,
                "request_id": request_id,
                "model_id": model_id,
                "state": finished.state,
                "reason": finished.reason,
                "code": "cancelled",
            }
        return {
            "performed": True,
            "request_id": request_id,
            "model_id": model_id,
            "reason": "cancellation requested",
            "code": "cancelled",
        }

    def health(self, model_id: str) -> dict[str, object]:
        model = self._registry.get(model_id)
        with self._lock:
            session = self._require(model_id)
            state = self._lifecycle.state(model_id)
            return {
                "model_id": model.id,
                "lifecycle": state.value,
                "engine": session.engine,
                "available": state in SELECTABLE_STATES,
                "loaded": state in LOADED_STATES,
                "resident": session.resident,
                "context_window": model.context_window,
                "ram_mb": _known(model.requirements.ram_mb, model.requirements.ram_known),
                "vram_mb": _known(model.requirements.vram_mb, model.requirements.vram_known),
                "ram_known": model.requirements.ram_known,
                "vram_known": model.requirements.vram_known,
                "gpu": session.gpu,
                "worker_id": session.worker_id,
                "healthy": state
                not in {ModelLifecycleState.FAILED, ModelLifecycleState.UNAVAILABLE},
                "failure": session.failure,
            }

    def health_all(self) -> list[dict[str, object]]:
        return [self.health(model.id) for model in self._registry.enabled()]

    def available_ids(self) -> set[str]:
        """Ids the router may select. Failed and missing models stay out."""

        with self._lock:
            return {
                model_id
                for model_id in self._sessions
                if self._lifecycle.state(model_id) in SELECTABLE_STATES
            }

    def state(self, model_id: str) -> ModelLifecycleState:
        self._require(model_id)
        return self._lifecycle.state(model_id)

    def _probe(
        self,
        engine_name: str,
        model: ModelMetadata,
        configured: bool,
    ) -> tuple[bool, bool, str, str | None]:
        if not configured:
            if engine_name == "mock":
                return False, False, "none", "model provider is not configured"
            return False, False, "unknown", "local model runtime is not configured"
        engine = self._engines[engine_name]
        try:
            status = engine.probe()
        except ProviderError as exc:
            return False, False, "unknown", str(exc)
        if not status.configured:
            return False, False, status.gpu, status.reason
        resident = model.model_name in status.resident
        if resident:
            return True, True, status.gpu, None
        return False, False, status.gpu, "model is not installed on the local runtime"

    def _load_refusal(
        self,
        model: ModelMetadata,
        session: _Session,
        worker_id: str | None,
        snapshot: ResourceSnapshot,
    ) -> dict[str, object] | None:
        state = self._lifecycle.state(model.id)
        engine_name = session.engine
        if engine_name is None:
            return _status(
                model.id,
                performed=False,
                state=state.value,
                reason="cloud models are not loaded as local weights",
                code="cloud",
                engine=None,
            )
        if state is ModelLifecycleState.UNAVAILABLE:
            return _status(
                model.id,
                performed=False,
                state=state.value,
                reason=session.failure or "model is unavailable",
                code="unavailable",
                engine=engine_name,
            )
        if state in {ModelLifecycleState.LOADED, ModelLifecycleState.IDLE}:
            return _status(
                model.id,
                performed=False,
                state=state.value,
                reason="model is already loaded",
                code="loaded",
                engine=engine_name,
            )
        if state in {
            ModelLifecycleState.RUNNING,
            ModelLifecycleState.LOADING,
            ModelLifecycleState.UNLOADING,
        }:
            return _status(
                model.id,
                performed=False,
                state=state.value,
                reason=f"model is {state.value.lower()}",
                code="busy",
                engine=engine_name,
            )
        if worker_id is not None and self._workers is not None and not self._workers(worker_id):
            return _status(
                model.id,
                performed=False,
                state=state.value,
                reason="worker is not running",
                code="worker",
                engine=engine_name,
            )
        if not session.resident:
            return _status(
                model.id,
                performed=False,
                state=state.value,
                reason=session.failure or "model is not installed on the local runtime",
                code="not_installed",
                engine=engine_name,
            )
        decision, reason = allocate(
            snapshot,
            AllocationRequest(
                requirements=model.requirements,
                local=model.local,
                cloud_available=False,
            ),
        )
        if decision is not AllocationDecision.ALLOW:
            return _status(
                model.id,
                performed=False,
                state=state.value,
                reason=reason,
                code="resources",
                engine=engine_name,
            )
        return None

    def _begin(
        self,
        model_id: str,
        prompt: str,
        *,
        system: str | None,
        worker_id: str | None,
        request_id: str | None,
    ) -> _Running | InferenceResult:
        model = self._registry.get(model_id)
        with self._lock:
            session = self._require(model_id)
            state = self._lifecycle.state(model_id)
            if session.engine is None:
                return _inference(
                    model_id,
                    state.value,
                    performed=False,
                    reason="cloud models are requested through their provider",
                    code="cloud",
                )
            if state not in {ModelLifecycleState.LOADED, ModelLifecycleState.IDLE}:
                return _inference(
                    model_id,
                    state.value,
                    performed=False,
                    reason=f"model is {state.value.lower()}",
                    code="not_loaded",
                )
            if worker_id is not None and self._workers is not None and not self._workers(worker_id):
                return _inference(
                    model_id,
                    state.value,
                    performed=False,
                    reason="worker is not running",
                    code="worker",
                )
            window = model.context_window
            counted = estimate_tokens(_prompt_text(prompt, system))
            if window is not None and counted > window:
                return _inference(
                    model_id,
                    state.value,
                    performed=False,
                    reason="prompt exceeds the context window",
                    code="context_limit",
                )
            identifier = request_id or str(uuid4())
            self._lifecycle.transition(model_id, ModelLifecycleState.RUNNING)
            session.request_id = identifier
            if worker_id is not None:
                session.worker_id = worker_id
            self._requests[identifier] = model_id
            engine = self._engines[session.engine]
            bound_worker = session.worker_id
            engine_name = session.engine
        self._emit(
            "model.running",
            model_id,
            bound_worker,
            {"lifecycle": "RUNNING", "engine": engine_name, "request_id": identifier},
        )
        return _Running(
            engine=engine,
            request=GenerateRequest(model=model.model_name, prompt=prompt, system=system),
            request_id=identifier,
            model_id=model_id,
        )

    def _finish(
        self,
        model_id: str,
        request_id: str,
        *,
        outcome: str,
        text: str,
        reason: str,
    ) -> InferenceResult:
        with self._lock:
            session = self._sessions.get(model_id)
            state = self._lifecycle.state(model_id)
            cancelled = outcome == "cancelled" or request_id in self._cancel_ids
            if (
                session is None
                or session.request_id != request_id
                or state is not ModelLifecycleState.RUNNING
            ):
                return _inference(
                    model_id,
                    state.value,
                    request_id=request_id,
                    text="" if cancelled else text,
                    performed=outcome == "ok" and not cancelled,
                    cancelled=cancelled,
                    reason=reason,
                    code="cancelled" if cancelled else outcome,
                )
            if outcome == "failed":
                self._lifecycle.transition(model_id, ModelLifecycleState.FAILED)
                session.failure = reason
                event_type = "model.failed"
                lifecycle = "FAILED"
            else:
                self._lifecycle.transition(model_id, ModelLifecycleState.IDLE)
                session.failure = None
                event_type = "model.cancelled" if outcome == "cancelled" else "model.idle"
                lifecycle = "IDLE"
            session.request_id = None
            self._requests.pop(request_id, None)
            worker_id = session.worker_id
            engine_name = session.engine
            final = self._lifecycle.state(model_id).value
        self._emit(
            event_type,
            model_id,
            worker_id,
            {"lifecycle": lifecycle, "engine": engine_name, "request_id": request_id},
        )
        return _inference(
            model_id,
            final,
            request_id=request_id,
            text="" if outcome != "ok" else text,
            performed=outcome == "ok",
            cancelled=outcome == "cancelled",
            reason=reason,
            code="ok" if outcome == "ok" else outcome,
        )

    def _fail_load(
        self,
        model_id: str,
        session: _Session,
        reason: str,
        code: str,
    ) -> dict[str, object]:
        with self._lock:
            if self._lifecycle.state(model_id) is ModelLifecycleState.LOADING:
                self._lifecycle.transition(model_id, ModelLifecycleState.FAILED)
            session.failure = reason
            worker_id = session.worker_id
            engine_name = session.engine
        self._emit(
            "model.failed",
            model_id,
            worker_id,
            {"lifecycle": "FAILED", "engine": engine_name, "reason": reason},
        )
        return _status(
            model_id,
            performed=False,
            state=ModelLifecycleState.FAILED.value,
            reason=reason,
            code=code,
            engine=engine_name,
        )

    def _engine_name(self, model: ModelMetadata) -> str | None:
        if model.provider == "mock" and "mock" in self._engines:
            return "mock"
        if model.provider == "local" and "openai-compatible" in self._engines:
            return "openai-compatible"
        return None

    def _require(self, model_id: str) -> _Session:
        try:
            return self._sessions[model_id]
        except KeyError as exc:
            raise KeyError(f"unknown model: {model_id}") from exc

    def _emit(
        self,
        event_type: str,
        model_id: str,
        worker_id: str | None,
        payload: dict[str, object],
    ) -> None:
        self._events.publish(
            event_type,
            model_id=model_id,
            worker_id=worker_id,
            source="models",
            payload=payload,
        )


def estimate_tokens(text: str) -> int:
    """Estimate tokens as about four characters each. Empty text is zero."""

    if not text:
        return 0
    return (len(text) + 3) // 4


def _prompt_text(prompt: str, system: str | None) -> str:
    if system:
        return f"{system}\n{prompt}"
    return prompt


def _known(value: int, known: bool) -> int | None:
    if known:
        return value
    return None


def _status(
    model_id: str,
    *,
    performed: bool,
    state: str,
    reason: str,
    code: str,
    engine: str | None,
) -> dict[str, object]:
    return {
        "model_id": model_id,
        "performed": performed,
        "state": state,
        "reason": reason,
        "code": code,
        "engine": engine,
    }


def _inference(
    model_id: str,
    state: str,
    *,
    performed: bool,
    reason: str,
    code: str,
    request_id: str = "",
    text: str = "",
    cancelled: bool = False,
) -> InferenceResult:
    return InferenceResult(
        model_id=model_id,
        request_id=request_id,
        text=text,
        performed=performed,
        cancelled=cancelled,
        state=state,
        reason=reason,
        code=code,
    )
