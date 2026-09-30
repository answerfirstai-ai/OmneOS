"""The only path that executes a tool."""

from __future__ import annotations

from typing import Any

from core.events.bus import EventBus
from core.logging_config import get_logger
from core.permissions.audit import AuditEntry, AuditLog, audit_now
from core.permissions.evaluator import PermissionEvaluator
from core.permissions.policies import PermissionDecision, PermissionRequest
from core.security.boundary import BoundaryDecision, admit_tool
from core.tools.base import ToolContext, ToolError, ToolResult
from core.tools.registry import ToolRegistry

logger = get_logger("tools")


class ToolGateway:
    """Validate input, evaluate permission, then execute."""

    def __init__(
        self,
        registry: ToolRegistry,
        evaluator: PermissionEvaluator,
        audit: AuditLog,
        events: EventBus,
    ) -> None:
        self._registry = registry
        self._evaluator = evaluator
        self._audit = audit
        self._events = events

    def invoke(
        self,
        *,
        tool_id: str,
        arguments: dict[str, Any],
        context: ToolContext,
        grants: dict[str, list[str]],
        environment: str,
        approved: bool = False,
    ) -> ToolResult:
        self._events.publish(
            "tool.requested",
            task_id=context.task_id,
            agent_id=context.agent_id,
            tool_id=tool_id,
            payload={"arguments": arguments},
        )
        try:
            tool = self._registry.get(tool_id)
            validated = tool.validate(arguments)
        except (KeyError, ToolError) as exc:
            return self._fail(tool_id, context, code="invalid_tool", message=str(exc))

        request = PermissionRequest(
            tool_id=tool_id,
            arguments=validated,
            grants=grants,
            environment=environment,
            workspace_root=str(context.workspace_root),
            task_id=context.task_id,
            agent_id=context.agent_id,
            user=context.user,
        )
        self._events.publish(
            "permission.requested",
            task_id=context.task_id,
            agent_id=context.agent_id,
            tool_id=tool_id,
        )
        decision = self._evaluator.evaluate(request)
        self._audit.record(
            AuditEntry(
                timestamp=audit_now(),
                decision=decision.decision.value,
                policy_id=decision.policy_id,
                reason=decision.reason,
                tool_id=tool_id,
                task_id=context.task_id,
                agent_id=context.agent_id,
                user=context.user,
                arguments=validated,
            )
        )
        if decision.decision is PermissionDecision.DENY:
            self._events.publish(
                "permission.denied",
                task_id=context.task_id,
                agent_id=context.agent_id,
                tool_id=tool_id,
                payload={"reason": decision.reason},
            )
            self._events.publish(
                "tool.denied",
                task_id=context.task_id,
                agent_id=context.agent_id,
                tool_id=tool_id,
                payload={"reason": decision.reason},
            )
            return ToolResult(
                ok=False,
                tool_id=tool_id,
                error={"code": "denied", "message": decision.reason},
            )
        if decision.decision is PermissionDecision.CONFIRM and not approved:
            return ToolResult(
                ok=False,
                tool_id=tool_id,
                confirmation_required=True,
                error={"code": "confirmation_required", "message": decision.reason},
                output={"arguments": validated},
            )

        self._events.publish(
            "permission.granted",
            task_id=context.task_id,
            agent_id=context.agent_id,
            tool_id=tool_id,
        )
        boundary = admit_tool(
            profile=context.profile,
            tool_id=tool_id,
            arguments=validated,
            workspace=str(context.workspace_root),
        )
        if boundary.decision is BoundaryDecision.DENY:
            self._events.publish(
                "security.denied",
                task_id=context.task_id,
                agent_id=context.agent_id,
                tool_id=tool_id,
                payload={"reason": boundary.reason, "profile": boundary.profile},
            )
            self._events.publish(
                "tool.denied",
                task_id=context.task_id,
                agent_id=context.agent_id,
                tool_id=tool_id,
                payload={"reason": boundary.reason},
            )
            return ToolResult(
                ok=False,
                tool_id=tool_id,
                error={"code": "denied", "message": boundary.reason},
            )
        try:
            output = tool.execute(validated, context)
        except ToolError as exc:
            return self._fail(tool_id, context, code=exc.code, message=str(exc))
        except Exception as exc:
            logger.exception("tool failed id=%s", tool_id)
            return self._fail(tool_id, context, code="tool_failed", message=str(exc))
        unavailable = bool(output.get("available") is False)
        self._events.publish(
            "tool.executed",
            task_id=context.task_id,
            agent_id=context.agent_id,
            tool_id=tool_id,
            payload={"unavailable": unavailable},
        )
        return ToolResult(ok=True, tool_id=tool_id, output=output, unavailable=unavailable)

    def _fail(self, tool_id: str, context: ToolContext, *, code: str, message: str) -> ToolResult:
        self._events.publish(
            "tool.failed",
            task_id=context.task_id,
            agent_id=context.agent_id,
            tool_id=tool_id,
            payload={"code": code, "message": message},
        )
        return ToolResult(ok=False, tool_id=tool_id, error={"code": code, "message": message})
