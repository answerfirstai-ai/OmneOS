"""Route a bounded context to a model and return a structured decision.

The model never receives the memory database and never executes a tool.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.compute.monitor import ResourceSnapshot
from core.events.bus import EventBus
from core.models.providers.base import ModelProvider
from core.models.router import ModelRouter
from core.models.structured import StructuredDecision, parse_structured, validate_tool_requests
from core.models.types import GenerateRequest, ProviderError
from omne.secrets.redact import redact_text

_SYSTEM = (
    "You are OMNE's decision model. Reply with one JSON object and no other text. "
    "Keys: intent, plan, tool_requests, expected_result, clarification_required, "
    "confirmation_required, final_response, reasoning_summary. "
    "plan is an array of short strings. tool_requests is an array of "
    '{name, arguments}. reasoning_summary is one short sentence or "". '
    "Do not include hidden reasoning. Do not claim a tool already ran. "
    "Do not emit operating-system commands. Request a tool by its registered name."
)

_FALLBACK_CODES = frozenset(
    {
        "configuration",
        "unavailable",
        "connection_error",
        "timeout",
        "rate_limited",
        "authentication",
        "invalid_response",
    }
)


class IntelligenceContext(BaseModel):
    """The notes a model is allowed to see for one request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    objective: str
    task: str = ""
    agents: list[str] = Field(default_factory=list)
    workers: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    machine: str = ""
    memory: str = ""
    project: str = ""


class Cortex:
    """Context, route, model, structured decision. Tools stay with the gateway."""

    def __init__(
        self,
        *,
        router: ModelRouter,
        providers: dict[str, ModelProvider],
        model_names: dict[str, str],
        provider_labels: dict[str, str],
        events: EventBus,
        known_tools: set[str],
    ) -> None:
        self._router = router
        self._providers = providers
        self._model_names = model_names
        self._labels = provider_labels
        self._events = events
        self._known_tools = set(known_tools)

    async def complete(
        self,
        context: IntelligenceContext,
        snapshot: ResourceSnapshot,
        *,
        capability: str,
        route: str,
        available: set[str],
        task_id: str | None = None,
        worker_id: str | None = None,
        trace_id: str | None = None,
        preferred_model: str | None = None,
        allow_mock: bool = True,
    ) -> StructuredDecision:
        chain = self._router.order(
            [capability],
            snapshot,
            route=route,
            available=available,
            allow_mock=allow_mock,
            preferred_model=preferred_model,
        )
        if not chain:
            raise ProviderError(
                "no model is available for this route",
                code="unavailable",
                provider=route,
            )
        prompt = render_context(context)
        last: ProviderError | None = None
        for index, model in enumerate(chain):
            provider = self._providers.get(model.id)
            label = self._labels.get(model.id, model.provider)
            external = self._model_names.get(model.id, model.model_name)
            if provider is None:
                continue
            started = time.perf_counter()
            self._emit(
                "model.requested",
                model_id=model.id,
                provider=label,
                model_name=external,
                task_id=task_id,
                worker_id=worker_id,
                trace_id=trace_id,
                latency=None,
            )
            self._emit(
                "model.started",
                model_id=model.id,
                provider=label,
                model_name=external,
                task_id=task_id,
                worker_id=worker_id,
                trace_id=trace_id,
                latency=None,
            )
            try:
                response = await provider.generate(
                    GenerateRequest(model=external, prompt=prompt, system=_SYSTEM)
                )
            except ProviderError as exc:
                last = exc
                self._emit(
                    "model.failed",
                    model_id=model.id,
                    provider=label,
                    model_name=external,
                    task_id=task_id,
                    worker_id=worker_id,
                    trace_id=trace_id,
                    latency=_elapsed(started),
                    code=exc.code,
                )
                if route == "auto" and index + 1 < len(chain) and exc.code in _FALLBACK_CODES:
                    nxt = chain[index + 1]
                    self._emit(
                        "model.fallback",
                        model_id=model.id,
                        provider=label,
                        model_name=external,
                        task_id=task_id,
                        worker_id=worker_id,
                        trace_id=trace_id,
                        latency=_elapsed(started),
                        code=exc.code,
                        fallback_provider=self._labels.get(nxt.id, nxt.provider),
                        fallback_model=self._model_names.get(nxt.id, nxt.model_name),
                    )
                    continue
                raise
            latency = _elapsed(started)
            answered = response.provider or label
            self._emit(
                "model.completed",
                model_id=model.id,
                provider=answered,
                model_name=response.model or external,
                task_id=task_id,
                worker_id=worker_id,
                trace_id=trace_id,
                latency=latency,
            )
            decision = parse_structured(
                response.text,
                provider=answered,
                model=response.model or external,
            )
            checked, rejected = validate_tool_requests(decision, self._known_tools)
            return checked.model_copy(update={"rejected_tools": rejected})
        if last is not None:
            raise last
        raise ProviderError("no model provider was configured", code="unavailable", provider=route)

    def _emit(
        self,
        event_type: str,
        *,
        model_id: str,
        provider: str,
        model_name: str,
        task_id: str | None,
        worker_id: str | None,
        trace_id: str | None,
        latency: int | None,
        code: str | None = None,
        fallback_provider: str | None = None,
        fallback_model: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "provider": provider,
            "model": model_name,
            "latency": latency,
        }
        if code is not None:
            payload["code"] = code
        if fallback_provider is not None:
            payload["fallback_provider"] = fallback_provider
            payload["fallback_model"] = fallback_model or ""
        self._events.publish(
            event_type,
            source="models",
            task_id=task_id,
            model_id=model_id,
            worker_id=worker_id,
            trace_id=trace_id,
            payload=payload,
        )


def render_context(context: IntelligenceContext, *, char_limit: int = 4000) -> str:
    """Render a short prompt. Each section is capped."""

    sections = [
        f"objective: {_clip(context.objective, 500)}",
        f"task: {_clip(context.task or context.objective, 500)}",
        "agents: " + _join(context.agents, 8),
        "workers: " + _join(context.workers, 8),
        "tools: " + _join(context.tools, 16),
        "permissions: " + _join(context.permissions, 12),
        f"machine: {_clip(context.machine, 240)}",
        f"project: {_clip(context.project, 120)}",
        f"memory: {_clip(context.memory, 1200)}",
    ]
    text = redact_text("\n".join(sections))
    if len(text) <= char_limit:
        return text
    return text[:char_limit]


def _join(items: list[str], limit: int) -> str:
    cleaned = [redact_text(item).strip() for item in items if item.strip()]
    return ", ".join(cleaned[:limit])


def _clip(value: str, limit: int) -> str:
    text = redact_text(value).replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[:limit]


def _elapsed(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))
