"""Adapter interface for a local model runtime.

An engine reports models it already has and runs inference for those models.
It does not fetch weights and it does not name a GPU vendor on its own.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from core.models.types import GenerateChunk, GenerateRequest, GenerateResponse


class EngineStatus(BaseModel):
    """What a probe learned without inventing hardware."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    configured: bool
    resident: list[str] = Field(default_factory=list)
    gpu: str = "unknown"
    reason: str


class ModelEngine(Protocol):
    """One local runtime. Core does not bind itself to a single product."""

    name: str

    def probe(self) -> EngineStatus:
        """Report configuration, resident model names, and an accelerator label."""

    def resident(self, model_name: str) -> bool:
        """Return whether ``model_name`` is already present on this engine."""

    def load(self, model_name: str) -> None:
        """Use a resident model. This must not download weights."""

    def unload(self, model_name: str) -> None:
        """Drop the in-runtime mapping. This must not delete model files."""

    def cancel(self, request_id: str) -> None:
        """Ask an in-flight request to stop. This must not signal a process."""

    async def generate(self, request: GenerateRequest, request_id: str) -> GenerateResponse:
        """Return one complete response."""

    def stream(self, request: GenerateRequest, request_id: str) -> AsyncIterator[GenerateChunk]:
        """Yield response chunks."""
