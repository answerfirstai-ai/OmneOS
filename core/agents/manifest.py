"""Agent manifest schema."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from core.compute.requirements import ResourceRequirements


class LifecycleSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    persistent: bool = False
    startup: Literal["on_demand"]
    shutdown: Literal["after_task", "never"]


class AgentManifest(BaseModel):
    """A validated agent declaration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,63}$")
    name: str
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    description: str
    capabilities: list[str] = Field(min_length=1)
    tools: list[str]
    resources: ResourceRequirements = Field(default_factory=ResourceRequirements)
    permissions: dict[str, list[str]]
    lifecycle: LifecycleSpec

    @model_validator(mode="after")
    def _consistent_lifecycle(self) -> AgentManifest:
        if self.lifecycle.persistent and self.lifecycle.shutdown != "never":
            raise ValueError("persistent agents must set lifecycle.shutdown to never")
        if not self.lifecycle.persistent and self.lifecycle.shutdown != "after_task":
            raise ValueError("on-demand agents must set lifecycle.shutdown to after_task")
        if not self.description.strip():
            raise ValueError("description must not be empty")
        return self


def load_manifest(path: Path, *, known_tools: set[str] | None = None) -> AgentManifest:
    """Load and validate one manifest."""

    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid agent manifest {path}: {exc}") from exc
    try:
        manifest = AgentManifest.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"invalid agent manifest {path}: {exc}") from exc
    if known_tools is not None:
        unknown = [tool for tool in manifest.tools if tool not in known_tools]
        if unknown:
            raise ValueError(f"invalid agent manifest {path}: unknown tools {', '.join(unknown)}")
    return manifest
