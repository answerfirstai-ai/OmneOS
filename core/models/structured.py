"""Structured model decisions.

The model may describe a tool request. Nothing in this module executes a tool
or an operating-system command.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ToolRequest(BaseModel):
    """A tool the model asked for. The gateway has not run it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class StructuredDecision(BaseModel):
    """A validated model decision. Hidden reasoning is not retained."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    intent: str = ""
    plan: list[str] = Field(default_factory=list)
    tool_requests: list[ToolRequest] = Field(default_factory=list)
    expected_result: str = ""
    clarification_required: bool = False
    confirmation_required: bool = False
    final_response: str = ""
    reasoning_summary: str = ""
    rejected_tools: list[str] = Field(default_factory=list)
    provider: str = ""
    model: str = ""


def parse_structured(text: str, *, provider: str, model: str) -> StructuredDecision:
    """Read a decision from model text. Plain text becomes the final response."""

    payload = _extract_object(text)
    if payload is None:
        return StructuredDecision(
            final_response=text.strip(),
            provider=provider,
            model=model,
        )
    for hidden in ("chain_of_thought", "reasoning", "thinking", "cot", "thought"):
        payload.pop(hidden, None)
    summary = payload.get("reasoning_summary", "")
    payload["reasoning_summary"] = summary[:240] if isinstance(summary, str) else ""
    plan = payload.get("plan", [])
    if isinstance(plan, str):
        payload["plan"] = [plan] if plan else []
    elif not isinstance(plan, list):
        payload["plan"] = []
    else:
        payload["plan"] = [str(item) for item in plan if isinstance(item, str)]
    payload["tool_requests"] = _tool_requests(payload.get("tool_requests"))
    for flag in ("clarification_required", "confirmation_required"):
        if not isinstance(payload.get(flag), bool):
            payload[flag] = False
    for key in ("intent", "expected_result", "final_response"):
        if not isinstance(payload.get(key), str):
            payload[key] = ""
    decision = StructuredDecision.model_validate(payload)
    return decision.model_copy(
        update={
            "provider": provider,
            "model": model,
            "reasoning_summary": decision.reasoning_summary[:240],
        }
    )


def validate_tool_requests(
    decision: StructuredDecision, known_tools: set[str]
) -> tuple[StructuredDecision, list[str]]:
    """Keep known tool names and report the rest. No tool is executed."""

    accepted: list[ToolRequest] = []
    rejected: list[str] = []
    for request in decision.tool_requests:
        if request.name in known_tools:
            accepted.append(request)
        else:
            rejected.append(request.name)
    return decision.model_copy(update={"tool_requests": accepted}), rejected


def _tool_requests(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"]:
            continue
        arguments = item.get("arguments")
        cleaned.append(
            {
                "name": item["name"],
                "arguments": arguments if isinstance(arguments, dict) else {},
            }
        )
    return cleaned


def _extract_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = [line for line in stripped.splitlines() if not line.startswith("```")]
        stripped = "\n".join(lines).strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        loaded = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(loaded, dict):
        return None
    return loaded
