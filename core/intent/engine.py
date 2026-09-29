"""Turn raw text into a structured intent.

Known commands are parsed locally. A model is used only when the caller
allows it and the text is not already a known command.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

_WRITE = re.compile(r"^write file (?P<path>\S+) with content (?P<content>.+)$", re.IGNORECASE)
_TERMINAL = re.compile(r"^run terminal command (?P<command>.+)$", re.IGNORECASE)


class Intent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: str
    entities: dict[str, Any] = Field(default_factory=dict)
    constraints: list[str] = Field(default_factory=list)
    desired_outcome: str
    urgency: str = "normal"
    privacy: str = "local"
    risk: str = "low"
    requires_host_access: bool = False
    requires_network: bool = False
    ambiguous: bool = False
    question: str | None = None
    options: list[str] = Field(default_factory=list)
    source: str = "deterministic"


class IntentEngine:
    """Interpret one objective."""

    def interpret(
        self, text: str, *, allow_model: bool = False, model_text: str | None = None
    ) -> Intent:
        stripped = " ".join(text.split())
        parsed = _deterministic(stripped)
        if parsed is not None:
            return parsed
        if allow_model and model_text:
            modeled = _from_model_text(stripped, model_text)
            if modeled is not None:
                return modeled
        return Intent(
            intent="conversation",
            desired_outcome="answer",
            privacy="local",
            risk="low",
            source="fallback",
        )


def _deterministic(text: str) -> Intent | None:
    lowered = text.lower()
    if lowered in {"delete the project", "delete project", "remove the project"}:
        return _question(
            "delete_project",
            "Which project should be deleted?",
            ["the workspace project"],
        )
    if lowered in {"delete file", "remove file", "fix it", "do it"}:
        return _question("clarify", "What should OMNE act on?", [])
    write = _WRITE.match(text)
    if write:
        return Intent(
            intent="filesystem.write",
            entities={"path": write.group("path"), "content": write.group("content")},
            desired_outcome="file_written",
            risk="low",
            requires_host_access=True,
        )
    terminal = _TERMINAL.match(text)
    if terminal:
        command = terminal.group("command")
        return Intent(
            intent="terminal.execute",
            entities={"command": command},
            desired_outcome="command_finished",
            risk="high",
            requires_host_access=True,
            requires_network="http://" in command or "https://" in command,
        )
    if "website" in lowered:
        return Intent(
            intent="create_website",
            desired_outcome="html_file",
            risk="low",
            requires_host_access=True,
        )
    if "git status" in lowered:
        return Intent(
            intent="git.status",
            desired_outcome="repository_status",
            risk="low",
            requires_host_access=True,
        )
    if lowered.startswith("research") or " research " in f" {lowered} ":
        return Intent(
            intent="research.workspace",
            desired_outcome="local_sources",
            risk="low",
            requires_host_access=True,
            requires_network=False,
        )
    if lowered.startswith("open http") or "browser" in lowered:
        return Intent(
            intent="browser.open",
            desired_outcome="browser_opened",
            risk="medium",
            requires_host_access=True,
            requires_network=True,
        )
    metrics = [
        name for name in ("cpu", "memory", "gpu", "disk", "network", "processes") if name in lowered
    ]
    if metrics:
        return Intent(
            intent="system.inspect",
            entities={"metrics": metrics},
            desired_outcome="host_report",
            risk="low",
            requires_host_access=True,
        )
    if "internet" in lowered or "network is not" in lowered:
        return Intent(
            intent="diagnose_and_fix_network",
            desired_outcome="working_network",
            risk="medium",
            requires_host_access=True,
            requires_network=True,
        )
    return None


def _question(intent: str, question: str, options: list[str]) -> Intent:
    return Intent(
        intent=intent,
        desired_outcome="clarification",
        risk="high",
        ambiguous=True,
        question=question,
        options=options,
        source="deterministic",
    )


def _from_model_text(text: str, model_text: str) -> Intent | None:
    if "diagnose_and_fix_network" in model_text:
        return Intent(
            intent="diagnose_and_fix_network",
            desired_outcome="working_network",
            risk="medium",
            requires_host_access=True,
            requires_network=True,
            source="model",
        )
    if not model_text.strip():
        return None
    return Intent(
        intent="conversation",
        entities={"model_note": model_text[:240]},
        desired_outcome="answer",
        source="model",
        constraints=[text[:120]],
    )
