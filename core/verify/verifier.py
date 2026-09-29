"""Check evidence after a worker reports a result."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    status: str
    evidence: list[str] = Field(default_factory=list)
    checks: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    confidence: str
    timestamp: datetime


def verify_observations(
    verification_id: str,
    observations: list[dict[str, Any]],
    *,
    workspace: Path,
) -> VerificationResult:
    """Verify tool observations that name a file. Other results stay inconclusive."""

    checks: list[str] = []
    evidence: list[str] = []
    errors: list[str] = []
    saw_file = False
    for observation in observations:
        kind = str(observation.get("kind", ""))
        if kind == "model_then_write":
            saw_file = True
            path = workspace / str(observation.get("path", ""))
            expected = str(observation.get("text", ""))
            checks.append("html file contents")
            if not path.is_file():
                errors.append(f"missing file {path.name}")
                continue
            content = path.read_text(encoding="utf-8")
            evidence.append(f"read {path.name}")
            if expected and expected not in content:
                errors.append(f"{path.name} does not contain the written text")
            if "<html" not in content.lower():
                errors.append(f"{path.name} does not contain html")
        if kind == "tool" and observation.get("tool_id") == "filesystem.write":
            saw_file = True
            output = observation.get("output")
            relative = ""
            if isinstance(output, dict):
                relative = str(output.get("path", ""))
            path = workspace / relative
            checks.append("written file exists")
            if relative and path.is_file():
                evidence.append(f"exists {relative}")
            elif relative:
                errors.append(f"missing file {relative}")
    if errors:
        status = "FAIL"
        confidence = "high"
    elif saw_file:
        status = "PASS"
        confidence = "high"
    else:
        status = "INCONCLUSIVE"
        confidence = "low"
        checks.append("no file evidence was required")
    return VerificationResult(
        id=verification_id,
        status=status,
        evidence=evidence,
        checks=checks,
        errors=errors,
        confidence=confidence,
        timestamp=datetime.now(UTC),
    )
