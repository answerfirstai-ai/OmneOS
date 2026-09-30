"""OpenAI-compatible local runtime.

The adapter lists models the server already exposes and sends chat requests
for those names. It does not add a model to the server.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import AsyncIterator

from core.models.engines.base import EngineStatus
from core.models.providers.local.provider import LocalProvider
from core.models.providers.xai.provider import Transport
from core.models.types import GenerateChunk, GenerateRequest, GenerateResponse, ProviderError


class OpenAICompatibleEngine:
    """Talk to a configured local server through its chat endpoint."""

    name = "openai-compatible"

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: int,
        transport: Transport | None = None,
    ) -> None:
        self._base_url = base_url.strip().rstrip("/")
        self._timeout = float(timeout_seconds)
        self._transport = transport
        self._resident: set[str] | None = None
        self._loaded: set[str] = set()
        self._cancelled: set[str] = set()
        self._gpu = "unknown"

    def probe(self) -> EngineStatus:
        if not self._base_url:
            self._resident = set()
            self._gpu = "unknown"
            return EngineStatus(
                configured=False,
                resident=[],
                gpu="unknown",
                reason="local model runtime is not configured",
            )
        if not self._base_url.startswith(("http://", "https://")):
            raise ProviderError(
                "local model runtime URL is not http",
                code="configuration",
                provider=self.name,
            )
        try:
            status, body = self._get(f"{self._v1()}/models")
        except TimeoutError as exc:
            raise ProviderError(
                "local runtime timed out", code="timeout", provider=self.name
            ) from exc
        except urllib.error.URLError as exc:
            raise ProviderError(
                str(exc.reason), code="connection_error", provider=self.name
            ) from exc
        if status != 200:
            raise ProviderError(
                f"local runtime returned {status}",
                code="unavailable",
                provider=self.name,
            )
        names, gpu = _listed(body)
        self._resident = set(names)
        self._gpu = gpu
        return EngineStatus(
            configured=True,
            resident=sorted(names),
            gpu=gpu,
            reason="local runtime responded",
        )

    def resident(self, model_name: str) -> bool:
        if self._resident is None:
            self.probe()
        return model_name in (self._resident or set())

    def load(self, model_name: str) -> None:
        if not self.resident(model_name):
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

    async def generate(self, request: GenerateRequest, request_id: str) -> GenerateResponse:
        self._require_loaded(request.model)
        if request_id in self._cancelled:
            raise ProviderError("inference was cancelled", code="cancelled", provider=self.name)
        response = await self._provider().generate(request)
        if request_id in self._cancelled:
            raise ProviderError("inference was cancelled", code="cancelled", provider=self.name)
        return response

    async def stream(
        self, request: GenerateRequest, request_id: str
    ) -> AsyncIterator[GenerateChunk]:
        self._require_loaded(request.model)
        async for chunk in self._provider().stream(request):
            if request_id in self._cancelled:
                return
            yield chunk

    def _require_loaded(self, model_name: str) -> None:
        if model_name not in self._loaded:
            raise ProviderError("model is not loaded", code="not_loaded", provider=self.name)

    def _provider(self) -> LocalProvider:
        return LocalProvider(
            base_url=self._base_url,
            timeout_seconds=int(self._timeout),
            transport=self._transport,
        )

    def _v1(self) -> str:
        if self._base_url.endswith("/v1"):
            return self._base_url
        return f"{self._base_url}/v1"

    def _get(self, url: str) -> tuple[int, bytes]:
        transport = self._transport
        if transport is None:
            return _urllib_get(url, self._timeout)
        return transport(url, {"Authorization": "Bearer local"}, b"", self._timeout)


def _listed(body: bytes) -> tuple[list[str], str]:
    try:
        loaded = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ProviderError(
            "local runtime response was not JSON",
            code="invalid_response",
            provider="openai-compatible",
        ) from exc
    if not isinstance(loaded, dict):
        raise ProviderError(
            "local runtime response was not an object",
            code="invalid_response",
            provider="openai-compatible",
        )
    data = loaded.get("data", [])
    names: list[str] = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                identifier = item.get("id")
                if isinstance(identifier, str) and identifier:
                    names.append(identifier)
    accelerator = loaded.get("accelerator")
    gpu = "unknown"
    if isinstance(accelerator, str) and accelerator.strip():
        gpu = accelerator.strip()
    return names, gpu


def _urllib_get(url: str, timeout: float) -> tuple[int, bytes]:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            payload = response.read()
            return int(status), payload
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
