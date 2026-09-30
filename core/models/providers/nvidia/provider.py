"""NVIDIA NIM chat-completions adapter.

The API key is supplied by the caller. This module has no default credential
and never records one.
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.request
from collections.abc import AsyncIterator, Callable
from typing import Any

from core.models.types import (
    GenerateChunk,
    GenerateRequest,
    GenerateResponse,
    ProviderError,
    ToolCallRequest,
    ToolCallResponse,
    Usage,
)
from omne.secrets.redact import redact_text

Transport = Callable[[str, dict[str, str], bytes | None, float], tuple[int, bytes]]

_RETRYABLE = frozenset({"timeout", "connection_error", "rate_limited", "unavailable"})


class NvidiaProvider:
    """Call the NVIDIA NIM HTTP API and normalize the response.

    A tool request is returned to the caller. This provider does not execute
    tools or operating-system commands.
    """

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str,
        timeout_seconds: int,
        max_retries: int,
        transport: Transport | None = None,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._base_url = base_url.rstrip("/")
        self._timeout = float(timeout_seconds)
        self._max_retries = max_retries
        self._transport = transport or _urllib_transport

    def __repr__(self) -> str:
        state = "configured" if self.configured else "not-configured"
        return f"NvidiaProvider({state})"

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        payload = self._request_body(request, stream=False)
        body = await asyncio.to_thread(self._post, payload)
        return _normalize_completion(body, request.model)

    async def stream(self, request: GenerateRequest) -> AsyncIterator[GenerateChunk]:
        payload = self._request_body(request, stream=True)
        raw = await asyncio.to_thread(self._post_bytes, payload)
        text = raw.decode("utf-8", errors="replace")
        yielded = False
        for chunk in _parse_sse(text):
            yielded = True
            yield chunk
        if not yielded:
            yield GenerateChunk(text="", done=True)

    async def tool_call(self, request: ToolCallRequest) -> ToolCallResponse:
        """Return a tool request. The tool is not executed."""

        payload = self._request_body(
            GenerateRequest(model=request.model, prompt=request.prompt, tools=request.tools),
            stream=False,
        )
        body = await asyncio.to_thread(self._post, payload)
        parsed = _tool_call_from_completion(body)
        if parsed is not None:
            return parsed
        generated = _normalize_completion(body, request.model)
        return ToolCallResponse(tool_name=None, arguments={}, text=generated.text)

    async def probe(self, model: str) -> dict[str, object]:
        """One small completion. No tools are declared and none are executed."""

        started = time.perf_counter()
        if not self.configured:
            return _probe_result(
                configured=False,
                provider_state="UNAVAILABLE",
                model=model,
                inference="FAIL",
                authentication="SKIPPED",
                catalog="SKIPPED",
                latency_ms=None,
                detail="NVIDIA_API_KEY is not set",
            )
        catalog = await asyncio.to_thread(self._catalog_state, model)
        if catalog == "authentication":
            return _probe_result(
                configured=True,
                provider_state="UNAVAILABLE",
                model=model,
                inference="FAIL",
                authentication="FAIL",
                catalog="FAIL",
                latency_ms=_elapsed(started),
                detail="NVIDIA rejected the API key",
            )
        try:
            response = await self._ping(model)
        except ProviderError as exc:
            authentication = "FAIL" if exc.code == "authentication" else "PASS"
            unavailable = exc.code in {"authentication", "configuration"}
            provider_state = "UNAVAILABLE" if unavailable else "AVAILABLE"
            return _probe_result(
                configured=True,
                provider_state=provider_state,
                model=model,
                inference="FAIL",
                authentication=authentication,
                catalog=catalog,
                latency_ms=_elapsed(started),
                detail=redact_text(str(exc)),
            )
        text = redact_text(response.text).strip()
        if not text:
            return _probe_result(
                configured=True,
                provider_state="AVAILABLE",
                model=model,
                inference="FAIL",
                authentication="PASS",
                catalog=catalog,
                latency_ms=_elapsed(started),
                detail="NVIDIA returned an empty completion",
            )
        return _probe_result(
            configured=True,
            provider_state="AVAILABLE",
            model=response.model,
            inference="PASS",
            authentication="PASS",
            catalog=catalog,
            latency_ms=_elapsed(started),
            detail="",
            answered_provider=response.provider,
        )

    async def _ping(self, model: str) -> GenerateResponse:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "Reply with the single word pong."}],
            "max_tokens": 16,
            "temperature": 0,
            "stream": False,
        }
        body = await asyncio.to_thread(self._post, payload)
        return _normalize_completion(body, model)

    def _catalog_state(self, model: str) -> str:
        try:
            ids = self.list_model_ids()
        except ProviderError as exc:
            if exc.code == "authentication":
                return "authentication"
            return "UNKNOWN"
        if model in ids:
            return "LISTED"
        return "NOT LISTED"

    def list_model_ids(self) -> list[str]:
        """Return catalog identifiers. The caller must already hold a key."""

        self._require_key()
        status, raw = self._transport(
            f"{self._base_url}/models",
            self._headers(),
            None,
            self._timeout,
        )
        if status in {401, 403}:
            raise self._error("NVIDIA rejected the API key", "authentication")
        if status >= 400:
            raise self._error(f"NVIDIA status {status}", "unavailable")
        try:
            loaded = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise self._error("NVIDIA catalog was not JSON", "invalid_response") from exc
        rows = loaded.get("data") if isinstance(loaded, dict) else None
        if not isinstance(rows, list):
            raise self._error("NVIDIA catalog did not include data", "invalid_response")
        names: list[str] = []
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("id"), str):
                names.append(row["id"])
        return names

    def _request_body(self, request: GenerateRequest, *, stream: bool) -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})
        body: dict[str, Any] = {"model": request.model, "messages": messages, "stream": stream}
        if request.tools:
            body["tools"] = request.tools
        return body

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw = self._post_bytes(payload)
        try:
            loaded = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise self._error("NVIDIA response was not JSON", "invalid_response") from exc
        if not isinstance(loaded, dict):
            raise self._error("NVIDIA response was not an object", "invalid_response")
        return loaded

    def _post_bytes(self, payload: dict[str, Any]) -> bytes:
        self._require_key()
        data = json.dumps(payload).encode("utf-8")
        url = f"{self._base_url}/chat/completions"
        last_error: Exception | None = None
        last_code = "unavailable"
        attempts = self._max_retries + 1
        for _attempt in range(attempts):
            try:
                status, body = self._transport(url, self._headers(), data, self._timeout)
            except TimeoutError as exc:
                last_error = exc
                last_code = "timeout"
                continue
            except urllib.error.URLError as exc:
                last_error = exc
                if isinstance(exc.reason, TimeoutError):
                    last_code = "timeout"
                else:
                    last_code = "connection_error"
                continue
            if status in {401, 403}:
                raise self._error("NVIDIA rejected the API key", "authentication")
            if status == 429:
                last_error = self._error("NVIDIA rate limit", "rate_limited")
                last_code = "rate_limited"
                continue
            if status >= 500:
                last_error = self._error(f"NVIDIA status {status}", "unavailable")
                last_code = "unavailable"
                continue
            if status >= 400:
                raise self._error(f"NVIDIA status {status}", "request_rejected")
            return body
        if last_code not in _RETRYABLE:
            last_code = "unavailable"
        raise self._error(
            f"NVIDIA request failed after {attempts} attempts",
            last_code,
        ) from last_error

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _require_key(self) -> None:
        if not self._api_key:
            raise self._error(
                "NVIDIA credentials are missing. Set the NVIDIA_API_KEY environment variable.",
                "configuration",
            )

    def _error(self, message: str, code: str) -> ProviderError:
        return ProviderError(redact_text(message), code=code, provider="nvidia")


def _urllib_transport(
    url: str, headers: dict[str, str], data: bytes | None, timeout: float
) -> tuple[int, bytes]:
    method = "GET" if data is None else "POST"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read()


def _normalize_completion(payload: dict[str, Any], model: str) -> GenerateResponse:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ProviderError(
            "NVIDIA response did not include choices",
            code="invalid_response",
            provider="nvidia",
        )
    message = choices[0].get("message", {})
    if not isinstance(message, dict):
        message = {}
    text = message.get("content") or ""
    if not isinstance(text, str):
        text = str(text)
    text = redact_text(text)
    usage_value = payload.get("usage")
    usage_raw: dict[str, Any] = usage_value if isinstance(usage_value, dict) else {}
    usage = Usage(
        input_tokens=_optional_int(usage_raw.get("prompt_tokens")),
        output_tokens=_optional_int(usage_raw.get("completion_tokens")),
    )
    finish = choices[0].get("finish_reason")
    return GenerateResponse(
        text=text,
        model=str(payload.get("model") or model),
        provider="nvidia",
        usage=usage,
        finish_reason=finish if isinstance(finish, str) else "stop",
    )


def _tool_call_from_completion(payload: dict[str, Any]) -> ToolCallResponse | None:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None
    message = choices[0].get("message")
    if not isinstance(message, dict):
        return None
    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list) or not tool_calls or not isinstance(tool_calls[0], dict):
        return None
    function = tool_calls[0].get("function")
    if not isinstance(function, dict):
        return None
    name = function.get("name")
    if not isinstance(name, str) or not name:
        return None
    raw_arguments = function.get("arguments", "{}")
    arguments: dict[str, Any] = {}
    if isinstance(raw_arguments, dict):
        arguments = raw_arguments
    elif isinstance(raw_arguments, str) and raw_arguments:
        try:
            loaded = json.loads(raw_arguments)
        except json.JSONDecodeError:
            loaded = {}
        if isinstance(loaded, dict):
            arguments = loaded
    return ToolCallResponse(tool_name=name, arguments=arguments, text=None)


def _parse_sse(body: str) -> list[GenerateChunk]:
    chunks: list[GenerateChunk] = []
    for line in body.splitlines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            chunks.append(GenerateChunk(text="", done=True))
            break
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            continue
        delta = choices[0].get("delta", {})
        content = delta.get("content") if isinstance(delta, dict) else ""
        if isinstance(content, str) and content:
            chunks.append(GenerateChunk(text=redact_text(content), done=False))
    return chunks


def _optional_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    return None


def _elapsed(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


def _probe_result(
    *,
    configured: bool,
    provider_state: str,
    model: str,
    inference: str,
    authentication: str,
    catalog: str,
    latency_ms: int | None,
    detail: str,
    answered_provider: str = "",
) -> dict[str, object]:
    return {
        "nvidia": "CONFIGURED" if configured else "NOT CONFIGURED",
        "provider": provider_state,
        "model": model,
        "inference": inference,
        "authentication": authentication,
        "catalog": catalog,
        "latency_ms": latency_ms,
        "answered_provider": answered_provider or ("nvidia" if inference == "PASS" else ""),
        "detail": redact_text(detail),
    }
