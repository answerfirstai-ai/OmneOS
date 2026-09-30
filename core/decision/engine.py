"""Choose how a mission should run."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core.intent.engine import Intent
from core.security.commands import classify_command, is_destructive

DecisionName = Literal[
    "DIRECT_TOOL",
    "LOCAL_MODEL",
    "CLOUD_MODEL",
    "HYBRID",
    "DEFER",
    "WAIT",
    "ASK_USER",
    "DENY",
]


class ExecutionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: DecisionName
    reason: str
    alternatives: list[str] = Field(default_factory=list)
    selected_option: str
    constraints: list[str] = Field(default_factory=list)
    trace_id: str = ""
    resources: dict[str, str] = Field(default_factory=dict)


class DecisionEngine:
    """Pick an execution path from intent, mode, and declared resources."""

    def decide(
        self,
        intent: Intent,
        *,
        mode: str,
        local_available: bool,
        cloud_available: bool,
        cpu_wait: bool,
        trace_id: str,
    ) -> ExecutionDecision:
        if intent.ambiguous:
            return _decision(
                "ASK_USER",
                "the request does not name a single target",
                ["DENY"],
                trace_id,
                intent.constraints,
            )
        if intent.intent == "terminal.execute":
            argv = str(intent.entities.get("command", "")).split()
            if is_destructive(argv) or "PRIVILEGED" in {
                item.value for item in classify_command(argv)
            }:
                return _decision(
                    "DENY",
                    "the command class is privileged or destructive",
                    [],
                    trace_id,
                    [item.value for item in classify_command(argv)],
                )
        if intent.intent in {
            "filesystem.write",
            "git.status",
            "system.inspect",
            "browser.open",
            "application.open",
            "research.workspace",
        }:
            return _decision(
                "DIRECT_TOOL",
                "the outcome is a known tool and does not need a model",
                ["HYBRID"],
                trace_id,
                intent.constraints,
            )
        if intent.intent in {"create_website", "diagnose_and_fix_network"}:
            return _decision(
                "HYBRID",
                "the mission needs a model and a host tool",
                ["DIRECT_TOOL", "CLOUD_MODEL"],
                trace_id,
                intent.constraints,
            )
        if cpu_wait:
            return _decision(
                "WAIT",
                "host CPU is above the scheduling threshold",
                ["DEFER"],
                trace_id,
                [],
            )
        if mode in {"offline", "local"} or intent.privacy == "private":
            if local_available:
                return _decision(
                    "LOCAL_MODEL",
                    "the mode keeps the request off the network and a local model is declared",
                    ["DEFER"],
                    trace_id,
                    [mode],
                )
            if mode == "offline":
                return _decision(
                    "DIRECT_TOOL",
                    "offline mode uses the deterministic mock route when no local model is loaded",
                    ["DEFER"],
                    trace_id,
                    [mode],
                )
            return _decision(
                "DEFER",
                "no local model is available for this mode",
                ["CLOUD_MODEL"] if cloud_available else [],
                trace_id,
                [mode],
            )
        if mode == "production" and not cloud_available and not local_available:
            return _decision(
                "DENY",
                "production has no available model for this request",
                [],
                trace_id,
                [mode],
            )
        if cloud_available or mode in {"development", "testing", "online", "hybrid"}:
            return _decision(
                "CLOUD_MODEL",
                "the request needs a model and the mode allows the configured route",
                ["LOCAL_MODEL"] if local_available else ["DEFER"],
                trace_id,
                [mode],
            )
        return _decision("DEFER", "no execution path is currently available", [], trace_id, [mode])


def _decision(
    name: DecisionName,
    reason: str,
    alternatives: list[str],
    trace_id: str,
    constraints: list[str],
) -> ExecutionDecision:
    return ExecutionDecision(
        decision=name,
        reason=reason,
        alternatives=alternatives,
        selected_option=name,
        constraints=constraints,
        trace_id=trace_id,
    )
