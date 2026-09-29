"""Provider-independent model types."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Usage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    input_tokens: int | None = None
    output_tokens: int | None = None


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str
    prompt: str
    system: str | None = None
    tools: list[dict[str, Any]] = Field(default_factory=list)


class GenerateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    model: str
    provider: str
    usage: Usage = Field(default_factory=Usage)
    finish_reason: str = "stop"


class GenerateChunk(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    done: bool = False


class ToolCallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str
    prompt: str
    tools: list[dict[str, Any]] = Field(default_factory=list)


class ToolCallResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_name: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    text: str | None = None


class ProviderError(Exception):
    """A normalized provider failure."""

    def __init__(self, message: str, *, code: str, provider: str) -> None:
        super().__init__(message)
        self.code = code
        self.provider = provider
