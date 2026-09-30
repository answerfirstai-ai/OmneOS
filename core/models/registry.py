"""Validated model metadata and lookup."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from core.compute.requirements import ResourceRequirements

ProviderName = Literal["mock", "xai", "local"]


class ModelMetadata(BaseModel):
    """Declared facts about a model. Unknown metrics stay the string ``unknown``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,63}$")
    provider: ProviderName
    model_name: str
    capabilities: list[str]
    local: bool
    requirements: ResourceRequirements = Field(default_factory=ResourceRequirements)
    cost_input: str = "unknown"
    cost_output: str = "unknown"
    latency: str = "unknown"
    reliability: str = "unknown"
    privacy: str = "unknown"
    context_window: int | None = None
    modalities: list[str] = Field(default_factory=lambda: ["text"])
    priority: int = 100

    @field_validator("cost_input", "cost_output", "latency")
    @classmethod
    def _metric(cls, value: str) -> str:
        if value == "unknown":
            return value
        try:
            float(value)
        except ValueError as exc:
            raise ValueError("metric must be 'unknown' or a number") from exc
        return value

    @field_validator("model_name")
    @classmethod
    def _model_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("model_name must not be empty")
        return stripped


class ModelRegistry:
    """Load model manifests and reject duplicates."""

    def __init__(self) -> None:
        self._models: dict[str, ModelMetadata] = {}
        self._disabled: set[str] = set()

    def discover(self, directory: Path) -> list[ModelMetadata]:
        if not directory.is_dir():
            return []
        loaded: list[ModelMetadata] = []
        for path in sorted(directory.rglob("*.toml")):
            loaded.append(self.register_path(path))
        return loaded

    def register_path(self, path: Path) -> ModelMetadata:
        try:
            payload = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise ValueError(f"invalid model manifest {path}: {exc}") from exc
        try:
            metadata = ModelMetadata.model_validate(payload)
        except ValidationError as exc:
            raise ValueError(f"invalid model manifest {path}: {exc}") from exc
        return self.register(metadata)

    def register(self, metadata: ModelMetadata) -> ModelMetadata:
        if metadata.id in self._models:
            raise ValueError(f"duplicate model identifier: {metadata.id}")
        self._models[metadata.id] = metadata
        return metadata

    def get(self, model_id: str) -> ModelMetadata:
        try:
            return self._models[model_id]
        except KeyError as exc:
            raise KeyError(f"unknown model: {model_id}") from exc

    def enable(self, model_id: str) -> None:
        self.get(model_id)
        self._disabled.discard(model_id)

    def disable(self, model_id: str) -> None:
        self.get(model_id)
        self._disabled.add(model_id)

    def enabled(self) -> list[ModelMetadata]:
        return [model for model in self._models.values() if model.id not in self._disabled]

    def all(self) -> list[ModelMetadata]:
        return list(self._models.values())
