"""Mock, xAI, local providers, and routing."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from core.compute.monitor import (
    CpuTelemetry,
    DiskTelemetry,
    GpuTelemetry,
    MemoryTelemetry,
    NetworkTelemetry,
    ResourceSnapshot,
)
from core.compute.requirements import ResourceRequirements
from core.models.providers.local.provider import LocalProvider
from core.models.providers.mock.provider import MockProvider
from core.models.providers.xai.provider import XAIProvider
from core.models.registry import ModelMetadata, ModelRegistry
from core.models.router import ModelRouter, RoutingError
from core.models.types import GenerateRequest, ProviderError, ToolCallRequest


def _snapshot(**memory: float | None) -> ResourceSnapshot:
    return ResourceSnapshot(
        cpu=CpuTelemetry(usage_percent=10),
        memory=MemoryTelemetry(total_mb=8192, available_mb=4096, used_mb=4096, **memory),
        gpu=GpuTelemetry(available=False),
        disk=DiskTelemetry(total_mb=1000, used_mb=100, available_mb=900),
        network=NetworkTelemetry(available=True),
    )


def test_mock_provider_is_deterministic() -> None:
    provider = MockProvider()
    page = asyncio.run(provider.generate(GenerateRequest(model="mock", prompt="write html")))
    text = asyncio.run(provider.generate(GenerateRequest(model="mock", prompt="hello there")))
    call = asyncio.run(
        provider.tool_call(
            ToolCallRequest(model="mock", prompt='CALL filesystem.read {"path": "a.txt"}')
        )
    )

    assert "<html" in page.text.lower()
    assert text.text == "mock-response:hello there"
    assert call.tool_name == "filesystem.read"
    assert call.arguments == {"path": "a.txt"}


def test_xai_missing_key_does_not_call_transport() -> None:
    def transport(
        url: str, headers: dict[str, str], data: bytes, timeout: float
    ) -> tuple[int, bytes]:
        raise AssertionError("transport should not be called")

    provider = XAIProvider(
        api_key=None,
        base_url="https://api.x.ai/v1",
        timeout_seconds=5,
        max_retries=0,
        transport=transport,
    )

    with pytest.raises(ProviderError) as caught:
        asyncio.run(provider.generate(GenerateRequest(model="grok-4", prompt="hi")))

    assert caught.value.code == "configuration"


def test_xai_parses_a_mocked_completion_and_tool_call() -> None:
    def transport(
        url: str, headers: dict[str, str], data: bytes, timeout: float
    ) -> tuple[int, bytes]:
        assert url == "https://api.x.ai/v1/chat/completions"
        assert headers["Authorization"] == "Bearer test-key"
        if b"tools" in data:
            body = (
                b'{"model":"grok-4","choices":[{"finish_reason":"tool_calls","message":'
                b'{"content":"","tool_calls":[{"function":{"name":"filesystem.read",'
                b'"arguments":"{\\"path\\":\\"a.txt\\"}"}}]}}]}'
            )
        else:
            body = (
                b'{"model":"grok-4","choices":[{"finish_reason":"stop","message":{"content":"hello"}}],'
                b'"usage":{"prompt_tokens":3,"completion_tokens":1}}'
            )
        return 200, body

    provider = XAIProvider(
        api_key="test-key",
        base_url="https://api.x.ai/v1",
        timeout_seconds=5,
        max_retries=1,
        transport=transport,
    )
    generated = asyncio.run(provider.generate(GenerateRequest(model="grok-4", prompt="hi")))
    called = asyncio.run(
        provider.tool_call(ToolCallRequest(model="grok-4", prompt="use a tool", tools=[{}]))
    )

    assert generated.text == "hello"
    assert generated.provider == "xai"
    assert generated.usage.input_tokens == 3
    assert called.tool_name == "filesystem.read"
    assert called.arguments == {"path": "a.txt"}


def test_xai_does_not_retry_authentication_failures() -> None:
    attempts = {"count": 0}

    def transport(
        url: str, headers: dict[str, str], data: bytes, timeout: float
    ) -> tuple[int, bytes]:
        attempts["count"] += 1
        return 401, b"{}"

    provider = XAIProvider(
        api_key="test-key",
        base_url="https://api.x.ai/v1",
        timeout_seconds=5,
        max_retries=2,
        transport=transport,
    )

    with pytest.raises(ProviderError) as caught:
        asyncio.run(provider.generate(GenerateRequest(model="grok-4", prompt="hi")))

    assert caught.value.code == "authentication"
    assert attempts["count"] == 1


def test_local_provider_without_url_does_not_connect() -> None:
    def transport(
        url: str, headers: dict[str, str], data: bytes, timeout: float
    ) -> tuple[int, bytes]:
        raise AssertionError("transport should not be called")

    provider = LocalProvider(base_url="", timeout_seconds=5, transport=transport)

    with pytest.raises(ProviderError) as caught:
        asyncio.run(provider.generate(GenerateRequest(model="local", prompt="hi")))

    assert caught.value.code == "unavailable"


def test_router_prefers_the_mock_provider() -> None:
    registry = ModelRegistry()
    registry.discover(Path("models/manifests"))
    route = ModelRouter(registry).select(["coding"], _snapshot())

    assert route.model.id == "mock-default"
    assert route.decision.value == "ALLOW"


def test_router_reports_missing_capabilities() -> None:
    registry = ModelRegistry()
    registry.register(
        ModelMetadata(
            id="mock-default",
            provider="mock",
            model_name="mock",
            capabilities=["coding"],
            local=False,
            requirements=ResourceRequirements(),
        )
    )

    with pytest.raises(RoutingError, match="capabilities"):
        ModelRouter(registry).select(["not-a-capability"], _snapshot())
