"""Bounded recovery decisions."""

from __future__ import annotations

from enum import StrEnum


class FailureClass(StrEnum):
    TRANSIENT = "TRANSIENT"
    RESOURCE = "RESOURCE"
    PERMISSION = "PERMISSION"
    VALIDATION = "VALIDATION"
    MODEL = "MODEL"
    TOOL = "TOOL"
    NETWORK = "NETWORK"
    AGENT = "AGENT"
    VERIFICATION = "VERIFICATION"
    USER_REQUIRED = "USER_REQUIRED"
    FATAL = "FATAL"


class RecoveryAction(StrEnum):
    RETRY = "retry"
    RETRY_WITH_BACKOFF = "retry_with_backoff"
    DIFFERENT_MODEL = "different_model"
    DIFFERENT_AGENT = "different_agent"
    DIFFERENT_TOOL = "different_tool"
    REPLAN = "replan"
    ASK_USER = "ask_user"
    ABORT = "abort"


def classify_failure(code: str) -> FailureClass:
    """Map an execution error code to a failure class."""

    if code in {"verification_failed"}:
        return FailureClass.VERIFICATION
    if code in {"confirmation_denied", "policy_denied"}:
        return FailureClass.PERMISSION
    if code in {"model_unavailable"}:
        return FailureClass.MODEL
    if code in {"agent_failed"}:
        return FailureClass.AGENT
    if code in {"scheduling_blocked"}:
        return FailureClass.RESOURCE
    if code in {"invalid_plan", "invalid_input"}:
        return FailureClass.VALIDATION
    if code in {"tool_failed", "execution_failed"}:
        return FailureClass.TOOL
    if code in {"escalated"}:
        return FailureClass.FATAL
    return FailureClass.TRANSIENT


def decide_recovery(
    failure: FailureClass,
    *,
    retry_count: int,
    retry_limit: int,
    destructive: bool,
) -> RecoveryAction:
    """Choose one bounded recovery action."""

    if destructive:
        return RecoveryAction.ASK_USER
    if failure in {FailureClass.PERMISSION, FailureClass.FATAL, FailureClass.VALIDATION}:
        return RecoveryAction.ABORT
    if failure is FailureClass.USER_REQUIRED:
        return RecoveryAction.ASK_USER
    if failure is FailureClass.VERIFICATION:
        return RecoveryAction.REPLAN if retry_count >= retry_limit else RecoveryAction.RETRY
    if failure is FailureClass.MODEL:
        return RecoveryAction.DIFFERENT_MODEL if retry_count < retry_limit else RecoveryAction.ABORT
    if failure is FailureClass.AGENT:
        return RecoveryAction.DIFFERENT_AGENT if retry_count < retry_limit else RecoveryAction.ABORT
    if failure is FailureClass.RESOURCE:
        return RecoveryAction.RETRY_WITH_BACKOFF
    if retry_count >= retry_limit:
        return RecoveryAction.ABORT
    if failure is FailureClass.TRANSIENT:
        return RecoveryAction.RETRY_WITH_BACKOFF
    return RecoveryAction.RETRY
