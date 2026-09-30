"""In-memory engine for tests.

Loading marks a slot. It does not read files or open a socket.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator

from core.models.engines.base import EngineStatus
from core.models.providers.mock.provider import mock_text
from core.models.types import (
    GenerateChunk,
    GenerateRequest,
    GenerateResponse,
    ProviderError,
    Usage,
)


class MockEngine:
    """Deterministic engine. ``pause`` holds inference so a test can cancel it."""

    name = "mock"

    def __init__(self) -> None:
        self._resident: set[str] = set()
        self._loaded: set[str] = set()
        self._cancelled: set[str] = set()
        self._release = threading.Event()
        self._release.set()
        self._fail = False

    def allow(self, model_name: str) -> None:
        self._resident.add(model_name)

    def pause(self) -> None:
        self._release.clear()

    def resume(self) -> None:
        self._release.set()

    def fail_once(self) -> None:
        self._fail = True

    def probe(self) -> EngineStatus:
        return EngineStatus(
            configured=True,
            resident=sorted(self._resident),
            gpu="none",
            reason="mock runtime is in memory",
        )

    def resident(self, model_name: str) -> bool:
        return model_name in self._resident

    def load(self, model_name: str) -> None:
        if model_name not in self._resident:
            raise ProviderError(
                "model is not installed on the local runtime",
                code="not_installed",
                provider=self.name,
            )
        self._loaded.add(model_name)

    def unload(self, model_name: str) -> None:
        self._loaded.discard(model_name)

    def cancel(self, request_id: str) -> None:
        self._cancelled.add(request_id)
        self._release.set()

    async def generate(self, request: GenerateRequest, request_id: str) -> GenerateResponse:
        await _wait(self._release)
        if request_id in self._cancelled:
            raise ProviderError("inference was cancelled", code="cancelled", provider=self.name)
        if self._fail:
            self._fail = False
            raise ProviderError("mock runtime failed", code="runtime", provider=self.name)
        if request.model not in self._loaded:
            raise ProviderError("model is not loaded", code="not_loaded", provider=self.name)
        return GenerateResponse(
            text=mock_text(request.prompt),
            model=request.model,
            provider=self.name,
            usage=Usage(input_tokens=len(request.prompt.split()), output_tokens=1),
            finish_reason="stop",
        )

    async def stream(
        self, request: GenerateRequest, request_id: str
    ) -> AsyncIterator[GenerateChunk]:
        if request.model not in self._loaded:
            raise ProviderError("model is not loaded", code="not_loaded", provider=self.name)
        text = mock_text(request.prompt)
        for index in range(0, len(text), 24):
            if request_id in self._cancelled:
                return
            yield GenerateChunk(text=text[index : index + 24], done=False)
        if request_id in self._cancelled:
            return
        yield GenerateChunk(text="", done=True)


async def _wait(release: threading.Event) -> None:
    await asyncio.to_thread(release.wait, 5)
