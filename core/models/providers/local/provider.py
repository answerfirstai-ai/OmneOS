"""Local runtime adapter.

No weights are loaded here. When a base URL is configured, requests use the
OpenAI-compatible chat endpoint. When it is not, the provider reports that
the runtime is unavailable and does not open a connection.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from core.models.providers.xai.provider import Transport, XAIProvider
from core.models.types import (
    GenerateChunk,
    GenerateRequest,
    GenerateResponse,
    ProviderError,
    ToolCallRequest,
    ToolCallResponse,
)


class LocalProvider:
    """Talk to a configured local server, or report that none is configured."""

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: int,
        transport: Transport | None = None,
    ) -> None:
        self._base_url = base_url.strip()
        self._delegate: XAIProvider | None = None
        if self._base_url:
            self._delegate = XAIProvider(
                api_key="local",
                base_url=self._base_url
                if self._base_url.endswith("/v1")
                else f"{self._base_url}/v1",
                timeout_seconds=timeout_seconds,
                max_retries=0,
                transport=transport,
            )

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        delegate = self._require()
        response = await delegate.generate(request)
        return response.model_copy(update={"provider": "local"})

    async def stream(self, request: GenerateRequest) -> AsyncIterator[GenerateChunk]:
        delegate = self._require()
        async for chunk in delegate.stream(request):
            yield chunk

    async def tool_call(self, request: ToolCallRequest) -> ToolCallResponse:
        delegate = self._require()
        return await delegate.tool_call(request)

    def _require(self) -> XAIProvider:
        if self._delegate is None:
            raise ProviderError(
                "local model provider is not configured",
                code="unavailable",
                provider="local",
            )
        return self._delegate
