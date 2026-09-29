"""Provider interface.

Core depends on this protocol. Provider SDK types stay inside provider packages.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from core.models.types import (
    GenerateChunk,
    GenerateRequest,
    GenerateResponse,
    ToolCallRequest,
    ToolCallResponse,
)


class ModelProvider(Protocol):
    """Generate text, stream text, or request a tool call."""

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        """Return one complete response."""

    def stream(self, request: GenerateRequest) -> AsyncIterator[GenerateChunk]:
        """Yield response chunks."""

    async def tool_call(self, request: ToolCallRequest) -> ToolCallResponse:
        """Return a tool request. The provider must not execute the tool."""
