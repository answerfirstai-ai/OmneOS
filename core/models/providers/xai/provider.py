"""xAI chat-completions adapter.

Credentials are read from the environment when the provider is constructed by
the runtime. This module never stores a default API key.
"""

from __future__ import annotations

import json
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

Transport = Callable[[str, dict[str, str], bytes, float], tuple[int, bytes]]


class XAIProvider:
    """Call the xAI HTTP API and normalize the response."""

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

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        payload = self._request_body(request, stream=False)
        body = self._post(payload)
        return _normalize_completion(body, request.model)

    async def stream(self, request: GenerateRequest) -> AsyncIterator[GenerateChunk]:
        payload = self._request_body(request, stream=True)
        raw = self._post_bytes(payload)
        text = raw.decode("utf-8", errors="replace")
        yielded = False
        for chunk in _parse_sse(text):
            yielded = True
            yield chunk
        if not yielded:
            yield GenerateChunk(text="", done=True)

    async def tool_call(self, request: ToolCallRequest) -> ToolCallResponse:
        payload = self._request_body(
            GenerateRequest(model=request.model, prompt=request.prompt, tools=request.tools),
            stream=False,
        )
        body = self._post(payload)
        parsed = _tool_call_from_completion(body)
        if parsed is not None:
            return parsed
        generated = _normalize_completion(body, request.model)
        return ToolCallResponse(tool_name=None, arguments={}, text=generated.text)

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
            raise ProviderError(
                "xAI response was not JSON", code="invalid_response", provider="xai"
            ) from exc
        if not isinstance(loaded, dict):
            raise ProviderError(
                "xAI response was not an object", code="invalid_response", provider="xai"
            )
        return loaded

    def _post_bytes(self, payload: dict[str, Any]) -> bytes:
        self._require_key()
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._base_url}/chat/completions"
        last_error: Exception | None = None
        attempts = self._max_retries + 1
        for _attempt in range(attempts):
            try:
                status, body = self._transport(url, headers, data, self._timeout)
            except TimeoutError as exc:
                last_error = exc
                continue
            except urllib.error.URLError as exc:
                if isinstance(exc.reason, TimeoutError):
                    last_error = exc
                    continue
                raise ProviderError(
                    str(exc.reason), code="connection_error", provider="xai"
                ) from exc
            if status == 401:
                raise ProviderError(
                    "xAI rejected the API key", code="authentication", provider="xai"
                )
            if status == 429 or status >= 500:
                last_error = ProviderError(
                    f"xAI status {status}", code="unavailable", provider="xai"
                )
                continue
            if status >= 400:
                raise ProviderError(f"xAI status {status}", code="request_rejected", provider="xai")
            return body
        raise ProviderError(
            f"xAI request failed after {attempts} attempts",
            code="unavailable",
            provider="xai",
        ) from last_error

    def _require_key(self) -> None:
        if not self._api_key:
            raise ProviderError(
                "xAI credentials are missing. Set the XAI_API_KEY environment variable.",
                code="configuration",
                provider="xai",
            )


def _urllib_transport(
    url: str, headers: dict[str, str], data: bytes, timeout: float
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read()


def _normalize_completion(payload: dict[str, Any], model: str) -> GenerateResponse:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ProviderError(
            "xAI response did not include choices", code="invalid_response", provider="xai"
        )
    message = choices[0].get("message", {})
    if not isinstance(message, dict):
        message = {}
    text = message.get("content") or ""
    if not isinstance(text, str):
        text = str(text)
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list) and tool_calls and not text:
        text = json.dumps(tool_calls[0])
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
        provider="xai",
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
            chunks.append(GenerateChunk(text=content, done=False))
    return chunks


def _optional_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    return None
