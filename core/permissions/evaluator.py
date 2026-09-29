"""Fail-closed permission evaluator."""

from __future__ import annotations

from collections.abc import Callable

from core.logging_config import get_logger
from core.permissions.policies import (
    PermissionDecision,
    PermissionRequest,
    PermissionResult,
    decide,
)

logger = get_logger("permissions")


class PermissionEvaluator:
    """Evaluate policy and deny the request when evaluation itself fails."""

    def __init__(
        self, policy: Callable[[PermissionRequest], PermissionResult] | None = None
    ) -> None:
        self._policy = policy or decide

    def evaluate(self, request: PermissionRequest) -> PermissionResult:
        try:
            result = self._policy(request)
        except Exception:
            logger.exception("permission policy failed tool=%s", request.tool_id)
            return PermissionResult(
                decision=PermissionDecision.DENY,
                reason="policy evaluation failed",
                policy_id="fail-closed",
            )
        if result.decision not in PermissionDecision:
            return PermissionResult(
                decision=PermissionDecision.DENY,
                reason="policy returned an invalid decision",
                policy_id="fail-closed",
            )
        return result
