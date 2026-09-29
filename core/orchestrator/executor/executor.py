"""Run planned calls through models and the tool gateway."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from core.agents.manifest import AgentManifest
from core.agents.registry import AgentRegistry
from core.agents.runtime import AgentRuntime
from core.events.bus import EventBus
from core.models.cache import ResponseCache
from core.models.providers.base import ModelProvider
from core.models.types import GenerateRequest, ToolCallRequest
from core.orchestrator.store import TaskStore
from core.orchestrator.task import PlannedCall, Task, TaskStatus
from core.tools.base import ToolContext, ToolResult
from core.tools.gateway import ToolGateway


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
                self._runtime.begin(manifest)
        elif task.status is TaskStatus.WAITING:
            task = self._store.transition(task, TaskStatus.RUNNING)
            if manifest is not None:
                self._runtime.begin(manifest)
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
            task = self._store.transition(task, TaskStatus.VERIFYING, observations=observations)
            task = self._store.transition(
                task, TaskStatus.COMPLETED, result={"observations": observations}
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
        provider = self._provider(task)
        request = GenerateRequest(model=self._external_model_name(task), prompt=prompt)
        label = self._provider_labels.get(task.assigned_model or "", task.assigned_model or "")
        cached = self._responses.get(label, request)
        if cached is not None:
            return cached.text
        response = await provider.generate(request)
        self._responses.put(label, request, response)
        return response.text

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
