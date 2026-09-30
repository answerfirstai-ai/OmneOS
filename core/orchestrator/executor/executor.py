"""Run planned calls through models and the tool gateway."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from core.agents.manifest import AgentManifest
from core.agents.registry import AgentRegistry
from core.agents.runtime import AgentRuntime
from core.events.bus import EventBus
from core.models.cache import CacheContext, ResponseCache
from core.models.providers.base import ModelProvider
from core.models.types import GenerateRequest, ProviderError, ToolCallRequest
from core.orchestrator.store import TaskStore
from core.orchestrator.task import PlannedCall, Task, TaskStatus
from core.tools.base import ToolContext, ToolResult
from core.tools.gateway import ToolGateway
from core.verify.verifier import verify_observations
from omne.secrets.redact import redact_text

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


class ExecutionFailure(Exception):
    """A call failed and the scheduler may recover."""

    def __init__(self, message: str, *, code: str = "execution_failed") -> None:
        super().__init__(message)
        self.code = code


class TaskExecutor:
    """Execute one task's calls. Models cannot reach the host except through the gateway."""

    def __init__(
        self,
        *,
        store: TaskStore,
        gateway: ToolGateway,
        agents: AgentRegistry,
        runtime: AgentRuntime,
        events: EventBus,
        providers: dict[str, ModelProvider],
        model_names: dict[str, str],
        environment: str,
        workspace_root: Path,
        timeout_seconds: int,
        responses: ResponseCache | None = None,
        provider_labels: dict[str, str] | None = None,
        context_text: Any | None = None,
        verification_required: bool = True,
    ) -> None:
        self._store = store
        self._gateway = gateway
        self._agents = agents
        self._runtime = runtime
        self._events = events
        self._providers = providers
        self._model_names = model_names
        self._responses = responses or ResponseCache()
        self._provider_labels = provider_labels or {}
        self._context_text = context_text
        self._verification_required = verification_required
        self._environment = environment
        self._workspace = workspace_root
        self._timeout = timeout_seconds

    async def run(self, task: Task) -> Task:
        task = self._store.get(task.id)
        manifest = self._manifest(task)
        if task.status is TaskStatus.QUEUED:
            task = self._store.transition(task, TaskStatus.PLANNING)
            task = self._store.transition(task, TaskStatus.RUNNING)
            self._events.publish(
                "task.started",
                task_id=task.id,
                agent_id=task.assigned_agent,
                model_id=task.assigned_model,
            )
            if manifest is not None:
                self._begin_worker(manifest, task)
        elif task.status is TaskStatus.WAITING:
            task = self._store.transition(task, TaskStatus.RUNNING)
            if manifest is not None:
                self._begin_worker(manifest, task)
        observations = list(task.observations)
        try:
            for call in task.calls[len(observations) :]:
                outcome = await self._execute_call(task, call, manifest)
                if isinstance(outcome, ToolResult):
                    if not outcome.confirmation_required:
                        raise ExecutionFailure(
                            "tool result was not recorded",
                            code="execution_failed",
                        )
                    self._release_for_confirmation(manifest)
                    pending = {
                        "tool_id": outcome.tool_id,
                        "arguments": outcome.output.get("arguments", call.arguments),
                        "requested": call.arguments,
                        "approved": False,
                    }
                    return self._store.transition(
                        task,
                        TaskStatus.WAITING,
                        observations=observations,
                        pending_confirmation=pending,
                    )
                observations.append(outcome)
                task = self._store.save(
                    task.model_copy(
                        update={"observations": observations, "pending_confirmation": None}
                    )
                )
            verdict = verify_observations(task.id, observations, workspace=self._workspace)
            self._events.publish(
                "verification.recorded",
                task_id=task.id,
                agent_id=task.assigned_agent,
                payload={"status": verdict.status, "id": verdict.id},
            )
            if self._verification_required and verdict.status == "FAIL":
                raise ExecutionFailure(
                    verdict.errors[0] if verdict.errors else "verification failed",
                    code="verification_failed",
                )
            task = self._store.transition(task, TaskStatus.VERIFYING, observations=observations)
            task = self._store.transition(
                task,
                TaskStatus.COMPLETED,
                result={
                    "observations": observations,
                    "verification": verdict.model_dump(mode="json"),
                },
            )
        except ExecutionFailure:
            raise
        self._events.publish(
            "task.completed",
            task_id=task.id,
            agent_id=task.assigned_agent,
            model_id=task.assigned_model,
        )
        if manifest is not None:
            self._runtime.succeed(manifest)
        return self._store.get(task.id)

    async def _execute_call(
        self,
        task: Task,
        call: PlannedCall,
        manifest: AgentManifest | None,
    ) -> dict[str, Any] | ToolResult:
        if call.kind == "tool":
            result = await self._call_tool(task, call.tool_id, call.arguments, manifest)
            if result.confirmation_required:
                return result
            if not result.ok:
                message = result.error["message"] if result.error else "tool failed"
                raise ExecutionFailure(message, code="tool_failed")
            return {
                "kind": "tool",
                "tool_id": call.tool_id,
                "output": result.output,
                "unavailable": result.unavailable,
            }
        if call.kind == "research_note":
            return {
                "kind": "research_note",
                "available": False,
                "source": "external",
                "message": "External research sources are not configured.",
            }
        if call.kind == "model":
            return {"kind": "model", "text": await self._generate(task, call.prompt)}
        if call.kind == "model_then_write":
            text = await self._generate(task, call.prompt)
            result = await self._call_tool(
                task,
                "filesystem.write",
                {"path": call.output_path, "content": text},
                manifest,
            )
            if result.confirmation_required:
                return result
            if not result.ok:
                message = result.error["message"] if result.error else "write failed"
                raise ExecutionFailure(message, code="tool_failed")
            return {"kind": "model_then_write", "path": call.output_path, "text": text}
        if call.kind == "model_tool":
            provider = self._provider(task)
            response = await provider.tool_call(
                ToolCallRequest(model=self._external_model_name(task), prompt=call.prompt)
            )
            if response.tool_name is None:
                return {"kind": "model_tool", "text": response.text}
            result = await self._call_tool(task, response.tool_name, response.arguments, manifest)
            if result.confirmation_required:
                return result
            if not result.ok:
                message = result.error["message"] if result.error else "tool failed"
                raise ExecutionFailure(message, code="tool_failed")
            return {"kind": "model_tool", "tool_id": response.tool_name, "output": result.output}
        if call.kind == "verify_file":
            result = await self._call_tool(task, "filesystem.read", call.arguments, manifest)
            if result.confirmation_required:
                return result
            if not result.ok:
                message = result.error["message"] if result.error else "read failed"
                raise ExecutionFailure(message, code="verification_failed")
            content = str(result.output.get("content", ""))
            if "<html" not in content.lower():
                raise ExecutionFailure("verification did not find html", code="verification_failed")
            return {"kind": "verify_file", "ok": True}
        raise ExecutionFailure(f"unknown call kind {call.kind}", code="invalid_plan")

    def _invoke(
        self,
        task: Task,
        tool_id: str,
        arguments: dict[str, Any],
        manifest: AgentManifest | None,
    ) -> ToolResult:
        pending = task.pending_confirmation or {}
        stored = pending.get("arguments")
        approved = bool(
            pending.get("approved") is True
            and pending.get("tool_id") == tool_id
            and isinstance(stored, dict)
            and (stored == arguments or pending.get("requested") == arguments)
        )
        invoke_arguments = stored if approved and isinstance(stored, dict) else arguments
        return self._gateway.invoke(
            tool_id=tool_id,
            arguments=invoke_arguments,
            context=self._context(task),
            grants=manifest.permissions if manifest is not None else {},
            environment=self._environment,
            approved=approved,
        )

    async def _call_tool(
        self,
        task: Task,
        tool_id: str,
        arguments: dict[str, Any],
        manifest: AgentManifest | None,
    ) -> ToolResult:
        return await asyncio.to_thread(self._invoke, task, tool_id, arguments, manifest)

    async def _generate(self, task: Task, prompt: str) -> str:
        context_note = ""
        if self._context_text is not None:
            context_note = str(self._context_text(task))
        full_prompt = f"{context_note}\n\n{prompt}" if context_note else prompt
        chain = _model_chain(task)
        last: ProviderError | None = None
        for index, model_id in enumerate(chain):
            provider = self._providers.get(model_id)
            if provider is None:
                continue
            label = self._provider_labels.get(model_id, model_id)
            external = self._model_names.get(model_id, model_id)
            request = GenerateRequest(model=external, prompt=full_prompt)
            revision = task.metadata.get("world_revision", 0)
            context = CacheContext(
                world_revision=int(revision) if isinstance(revision, int) else 0,
                context_revision=len(context_note),
            )
            if index == 0 and task.metadata.get("cache") == "bypass":
                self._responses.bypass(reason="task requested a fresh model call")
            elif index == 0:
                cached = self._responses.get(label, request, context=context)
                if cached is not None:
                    self._events.publish("cache.hit", task_id=task.id, model_id=model_id)
                    return cached.text
                self._events.publish("cache.miss", task_id=task.id, model_id=model_id)
            started = time.perf_counter()
            self._emit_model(task, "model.requested", model_id, label, external, latency=None)
            self._emit_model(task, "model.started", model_id, label, external, latency=None)
            try:
                response = await provider.generate(request)
            except ProviderError as exc:
                last = exc
                latency = _latency(started)
                self._emit_model(
                    task,
                    "model.failed",
                    model_id,
                    label,
                    external,
                    latency=latency,
                    code=exc.code,
                )
                if index + 1 < len(chain) and exc.code in _FALLBACK_CODES:
                    nxt = chain[index + 1]
                    self._emit_model(
                        task,
                        "model.fallback",
                        model_id,
                        label,
                        external,
                        latency=latency,
                        code=exc.code,
                        fallback_provider=self._provider_labels.get(nxt, nxt),
                        fallback_model=self._model_names.get(nxt, nxt),
                    )
                    continue
                raise ExecutionFailure(redact_text(str(exc)), code="model_unavailable") from exc
            latency = _latency(started)
            answered = response.provider or label
            self._emit_model(
                task,
                "model.completed",
                model_id,
                answered,
                response.model or external,
                latency=latency,
            )
            if index == 0:
                self._responses.put(label, request, response, context=context)
            return response.text
        if last is not None:
            raise ExecutionFailure(redact_text(str(last)), code="model_unavailable")
        raise ExecutionFailure("model provider is not available", code="model_unavailable")

    def _emit_model(
        self,
        task: Task,
        event_type: str,
        model_id: str,
        provider: str,
        model_name: str,
        *,
        latency: int | None,
        code: str | None = None,
        fallback_provider: str | None = None,
        fallback_model: str | None = None,
    ) -> None:
        worker = task.metadata.get("worker_id")
        trace = task.metadata.get("trace_id")
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
            task_id=task.id,
            model_id=model_id,
            worker_id=worker if isinstance(worker, str) else None,
            trace_id=trace if isinstance(trace, str) else None,
            payload=payload,
        )

    def _begin_worker(self, manifest: AgentManifest, task: Task) -> None:
        mission = task.metadata.get("mission_id")
        trace = task.metadata.get("trace_id")
        self._runtime.begin(
            manifest,
            task_id=task.id,
            mission_id=mission if isinstance(mission, str) else None,
            model_id=task.assigned_model,
            trace_id=trace if isinstance(trace, str) else None,
        )

    def _provider(self, task: Task) -> ModelProvider:
        model_id = task.assigned_model or ""
        provider = self._providers.get(model_id)
        if provider is None:
            raise ExecutionFailure(
                f"model provider is not available for {model_id}", code="model_unavailable"
            )
        return provider

    def _external_model_name(self, task: Task) -> str:
        model_id = task.assigned_model or ""
        return self._model_names.get(model_id, model_id)

    def _manifest(self, task: Task) -> AgentManifest | None:
        if task.assigned_agent is None:
            return None
        return self._agents.get(task.assigned_agent)

    def _context(self, task: Task) -> ToolContext:
        return ToolContext(
            task_id=task.id,
            agent_id=task.assigned_agent,
            user="local",
            workspace_root=self._workspace,
            timeout_seconds=self._timeout,
        )

    def _release_for_confirmation(self, manifest: AgentManifest | None) -> None:
        if manifest is None:
            return
        self._runtime.release(manifest)


def _model_chain(task: Task) -> list[str]:
    primary = task.assigned_model or ""
    chain = [primary] if primary else []
    stored = task.metadata.get("model_fallbacks")
    if isinstance(stored, list):
        chain.extend(item for item in stored if isinstance(item, str) and item not in chain)
    return chain


def _latency(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))
