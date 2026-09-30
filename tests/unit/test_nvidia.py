"""NVIDIA NIM provider, routing, redaction, and cloud resource accounting."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from tests.support import runtime_settings

from core.api.main import main
from core.api.runtime import build_OMNE
from core.compute.manager import ResourceManager
from core.compute.monitor import (
    CpuTelemetry,
    DiskTelemetry,
    GpuTelemetry,
    MemoryTelemetry,
    NetworkTelemetry,
    ResourceSnapshot,
    SystemMonitor,
)
from core.compute.requirements import ResourceRequirements
from core.events.bus import EventBus
from core.models.cortex import Cortex, IntelligenceContext
from core.models.providers.mock.provider import MockProvider
from core.models.providers.nvidia.provider import NvidiaProvider
from core.models.registry import ModelMetadata, ModelRegistry
from core.models.router import ModelRouter
from core.models.structured import parse_structured, validate_tool_requests
from core.models.types import GenerateRequest, ProviderError, ToolCallRequest
from omne.secrets.redact import SecretRedactor

_KEY = "nvapi-unit-test-key-not-real"


def _snapshot() -> ResourceSnapshot:
    return ResourceSnapshot(
        cpu=CpuTelemetry(usage_percent=10, count=4),
        memory=MemoryTelemetry(total_mb=8192, available_mb=4096, used_mb=4096),
        gpu=GpuTelemetry(available=True, count=1, vram_total_mb=16000, vram_used_mb=1000),
        disk=DiskTelemetry(total_mb=1000, used_mb=100, available_mb=900),
        network=NetworkTelemetry(available=True),
    )


def _provider(
    transport,  # type: ignore[no-untyped-def]
    *,
    api_key: str | None = _KEY,
    retries: int = 1,
) -> NvidiaProvider:
    return NvidiaProvider(
        api_key=api_key,
        base_url="https://integrate.api.nvidia.com/v1",
        timeout_seconds=5,
        max_retries=retries,
        transport=transport,
    )


def test_missing_key_does_not_call_transport() -> None:
    def transport(
        url: str, headers: dict[str, str], data: bytes | None, timeout: float
    ) -> tuple[int, bytes]:
        raise AssertionError("transport should not be called")

    provider = _provider(transport, api_key=None)

    with pytest.raises(ProviderError) as caught:
        asyncio.run(provider.generate(GenerateRequest(model="nvidia/nemotron", prompt="hi")))

    assert caught.value.code == "configuration"
    assert _KEY not in str(caught.value)
    assert "not-configured" in repr(provider)


def test_valid_completion_and_tool_request_are_not_executed() -> None:
    calls = {"count": 0}

    def transport(
        url: str, headers: dict[str, str], data: bytes | None, timeout: float
    ) -> tuple[int, bytes]:
        calls["count"] += 1
        assert url == "https://integrate.api.nvidia.com/v1/chat/completions"
        assert headers["Authorization"] == f"Bearer {_KEY}"
        assert data is not None
        if b'"tools"' in data:
            body = (
                b'{"model":"nvidia/nemotron-3-super-120b-a12b","choices":[{"finish_reason":'
                b'"tool_calls","message":{"content":"","tool_calls":[{"function":'
                b'{"name":"filesystem.read","arguments":"{\\"path\\":\\"a.txt\\"}"}}]}}]}'
            )
        else:
            body = (
                b'{"model":"nvidia/nemotron-3-super-120b-a12b","choices":[{"finish_reason":'
                b'"stop","message":{"content":"pong"}}],"usage":{"prompt_tokens":4,'
                b'"completion_tokens":1}}'
            )
        return 200, body

    provider = _provider(transport)
    generated = asyncio.run(
        provider.generate(GenerateRequest(model="nvidia/nemotron-3-super-120b-a12b", prompt="hi"))
    )
    called = asyncio.run(
        provider.tool_call(
            ToolCallRequest(
                model="nvidia/nemotron-3-super-120b-a12b",
                prompt="read a file",
                tools=[{"type": "function"}],
            )
        )
    )

    assert generated.text == "pong"
    assert generated.provider == "nvidia"
    assert generated.usage.input_tokens == 4
    assert called.tool_name == "filesystem.read"
    assert called.arguments == {"path": "a.txt"}
    assert calls["count"] == 2


def test_authentication_failure_is_not_retried() -> None:
    attempts = {"count": 0}

    def transport(
        url: str, headers: dict[str, str], data: bytes | None, timeout: float
    ) -> tuple[int, bytes]:
        attempts["count"] += 1
        return 401, f'{{"error":"{_KEY}"}}'.encode()

    provider = _provider(transport, retries=2)

    with pytest.raises(ProviderError) as caught:
        asyncio.run(provider.generate(GenerateRequest(model="nvidia/model", prompt="hi")))

    assert caught.value.code == "authentication"
    assert attempts["count"] == 1
    assert _KEY not in str(caught.value)


def _ask(provider: NvidiaProvider):
    return provider.generate(GenerateRequest(model="nvidia/model", prompt="hi"))


def test_timeout_network_rate_limit_and_server_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    del monkeypatch

    def scripted(statuses: list[object]):
        attempts = {"count": 0}

        def transport(
            url: str, headers: dict[str, str], data: bytes | None, timeout: float
        ) -> tuple[int, bytes]:
            item = statuses[attempts["count"]]
            attempts["count"] += 1
            if isinstance(item, Exception):
                raise item
            return int(item), b"{}"

        return transport, attempts

    timeout_transport, timeout_attempts = scripted([TimeoutError("slow"), TimeoutError("slow")])
    with pytest.raises(ProviderError) as timeout:
        asyncio.run(_ask(_provider(timeout_transport, retries=1)))
    assert timeout.value.code == "timeout"
    assert timeout_attempts["count"] == 2

    network_attempts = {"count": 0}

    def network(
        url: str, headers: dict[str, str], data: bytes | None, timeout: float
    ) -> tuple[int, bytes]:
        import urllib.error

        network_attempts["count"] += 1
        raise urllib.error.URLError("network down")

    with pytest.raises(ProviderError) as connection:
        asyncio.run(_ask(_provider(network, retries=1)))
    assert connection.value.code == "connection_error"
    assert network_attempts["count"] == 2

    limited, limited_attempts = scripted([429, 429])
    with pytest.raises(ProviderError) as rate:
        asyncio.run(
            _ask(_provider(limited, retries=1))
        )
    assert rate.value.code == "rate_limited"
    assert limited_attempts["count"] == 2

    failed, failed_attempts = scripted([503, 503])
    with pytest.raises(ProviderError) as server:
        asyncio.run(
            _ask(_provider(failed, retries=1))
        )
    assert server.value.code == "unavailable"
    assert failed_attempts["count"] == 2


def test_malformed_and_streaming_responses() -> None:
    def bad_json(
        url: str, headers: dict[str, str], data: bytes | None, timeout: float
    ) -> tuple[int, bytes]:
        return 200, b"not-json"

    with pytest.raises(ProviderError) as malformed:
        asyncio.run(
            _ask(_provider(bad_json, retries=0))
        )
    assert malformed.value.code == "invalid_response"

    def bad_shape(
        url: str, headers: dict[str, str], data: bytes | None, timeout: float
    ) -> tuple[int, bytes]:
        return 200, b'{"choices":[]}'

    with pytest.raises(ProviderError) as shape:
        asyncio.run(
            _provider(bad_shape, retries=0).generate(
                GenerateRequest(model="nvidia/model", prompt="hi")
            )
        )
    assert shape.value.code == "invalid_response"

    def stream(
        url: str, headers: dict[str, str], data: bytes | None, timeout: float
    ) -> tuple[int, bytes]:
        body = (
            'data: {"choices":[{"delta":{"content":"po"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"ng"}}]}\n\n'
            "data: [DONE]\n"
        )
        return 200, body.encode()

    async def read() -> str:
        parts: list[str] = []
        async for chunk in _provider(stream, retries=0).stream(
            GenerateRequest(model="nvidia/model", prompt="hi")
        ):
            parts.append(chunk.text)
        return "".join(parts)

    assert asyncio.run(read()) == "pong"


def test_probe_reports_status_without_the_key() -> None:
    def transport(
        url: str, headers: dict[str, str], data: bytes | None, timeout: float
    ) -> tuple[int, bytes]:
        if url.endswith("/models"):
            return 200, b'{"data":[{"id":"nvidia/nemotron-3-super-120b-a12b"}]}'
        return (
            200,
            b'{"model":"nvidia/nemotron-3-super-120b-a12b","choices":[{"message":{"content":"pong"}}]}',
        )

    result = asyncio.run(_provider(transport).probe("nvidia/nemotron-3-super-120b-a12b"))
    rendered = json.dumps(result)

    assert result["nvidia"] == "CONFIGURED"
    assert result["provider"] == "AVAILABLE"
    assert result["inference"] == "PASS"
    assert result["authentication"] == "PASS"
    assert result["answered_provider"] == "nvidia"
    assert _KEY not in rendered

    empty = asyncio.run(
        _provider(transport, api_key=None).probe("nvidia/nemotron-3-super-120b-a12b")
    )
    assert empty["nvidia"] == "NOT CONFIGURED"
    assert empty["inference"] == "FAIL"


def test_completion_text_is_redacted() -> None:
    def transport(
        url: str, headers: dict[str, str], data: bytes | None, timeout: float
    ) -> tuple[int, bytes]:
        body = json.dumps(
            {"choices": [{"message": {"content": f"leak {_KEY}"}}], "model": "nvidia/model"}
        )
        return 200, body.encode()

    redactor = SecretRedactor()
    redactor.register(_KEY)
    from omne.secrets.redact import install_redactor

    install_redactor(redactor)
    generated = asyncio.run(
        _provider(transport, retries=0).generate(GenerateRequest(model="nvidia/model", prompt="hi"))
    )

    assert _KEY not in generated.text
    assert "[redacted]" in generated.text


def test_router_auto_prefers_nvidia_then_local_then_mock() -> None:
    registry = ModelRegistry()
    registry.discover(Path("models/manifests"))
    router = ModelRouter(registry)
    available = {model.id for model in registry.enabled() if model.provider != "xai"}

    auto = router.order(
        ["reasoning"],
        _snapshot(),
        route="auto",
        available=available,
        preferred_model="nvidia/nemotron-3-super-120b-a12b",
    )
    nvidia_only = router.order(["vision"], _snapshot(), route="nvidia", available=available)
    local_only = router.order(["reasoning"], _snapshot(), route="local", available=available)
    mock_only = router.order(["reasoning"], _snapshot(), route="mock", available=available)
    without_nvidia = router.order(
        ["reasoning"],
        _snapshot(),
        route="auto",
        available={model.id for model in registry.enabled() if model.provider == "mock"},
    )

    assert auto[0].provider == "nvidia"
    assert auto[0].id == "nvidia-reasoning"
    assert [model.provider for model in auto].index("mock") > 0
    assert nvidia_only[0].id == "nvidia-vision"
    assert local_only == [] or all(model.provider == "local" for model in local_only)
    assert mock_only[0].id == "mock-default"
    assert without_nvidia[0].id == "mock-default"
    assert all(model.provider != "nvidia" for model in without_nvidia)


def test_structured_tool_request_is_validated_and_not_executed() -> None:
    executed = {"count": 0}

    def run_tool() -> None:
        executed["count"] += 1

    raw = json.dumps(
        {
            "intent": "read",
            "plan": ["read the file"],
            "tool_requests": [
                {"name": "filesystem.read", "arguments": {"path": "a.txt"}},
                {"name": "terminal.execute", "arguments": {"command": "rm -rf /"}},
            ],
            "expected_result": "contents",
            "clarification_required": False,
            "confirmation_required": True,
            "final_response": "",
            "reasoning_summary": "read one file",
            "chain_of_thought": "hidden steps that must not be stored",
        }
    )
    decision = parse_structured(raw, provider="nvidia", model="nvidia/nemotron-3-super-120b-a12b")
    checked, rejected = validate_tool_requests(decision, {"filesystem.read"})
    run_tool_was_not_used = run_tool

    assert decision.provider == "nvidia"
    assert "chain_of_thought" not in decision.model_dump()
    assert "hidden steps" not in decision.model_dump_json()
    assert checked.tool_requests[0].name == "filesystem.read"
    assert rejected == ["terminal.execute"]
    assert executed["count"] == 0
    assert run_tool_was_not_used is run_tool


def test_cortex_falls_back_and_names_the_provider_that_answered() -> None:
    def fail(
        url: str, headers: dict[str, str], data: bytes | None, timeout: float
    ) -> tuple[int, bytes]:
        raise TimeoutError("slow")

    nvidia = _provider(fail, retries=0)
    mock = MockProvider()
    registry = ModelRegistry()
    registry.register(
        ModelMetadata(
            id="nvidia-reasoning",
            provider="nvidia",
            model_name="nvidia/nemotron-3-super-120b-a12b",
            capabilities=["reasoning"],
            local=False,
            requirements=ResourceRequirements(vram_mb=0, vram_known=True, ram_known=True),
        )
    )
    registry.register(
        ModelMetadata(
            id="mock-default",
            provider="mock",
            model_name="mock",
            capabilities=["reasoning"],
            local=False,
            priority=0,
            requirements=ResourceRequirements(),
        )
    )
    events = EventBus()
    cortex = Cortex(
        router=ModelRouter(registry),
        providers={"nvidia-reasoning": nvidia, "mock-default": mock},
        model_names={
            "nvidia-reasoning": "nvidia/nemotron-3-super-120b-a12b",
            "mock-default": "mock",
        },
        provider_labels={"nvidia-reasoning": "nvidia", "mock-default": "mock"},
        events=events,
        known_tools=set(),
    )
    decision = asyncio.run(
        cortex.complete(
            IntelligenceContext(objective="say hello"),
            _snapshot(),
            capability="reasoning",
            route="auto",
            available={"nvidia-reasoning", "mock-default"},
        )
    )
    kinds = [event.type for event in events.list_events()]
    rendered = json.dumps([event.model_dump(mode="json") for event in events.list_events()])

    assert decision.provider == "mock"
    assert decision.provider != "nvidia"
    assert "model.fallback" in kinds
    assert "model.completed" in kinds
    assert _KEY not in rendered


def test_cloud_reservation_does_not_hold_vram() -> None:
    manager = ResourceManager(SystemMonitor())
    requirements = ResourceRequirements(ram_mb=0, vram_mb=8000, gpu=True, vram_known=True)
    cloud = manager.request(
        requirements,
        owner="nvidia-reasoning",
        kind="model",
        local=False,
        cloud_available=True,
        snapshot=_snapshot(),
    )
    local = manager.request(
        requirements,
        owner="local-default",
        kind="model",
        local=True,
        cloud_available=False,
        snapshot=_snapshot(),
    )

    assert cloud.resource_class == "CLOUD_MODEL_RESOURCE"
    assert cloud.decision.value == "ALLOW"
    assert cloud.requirements.vram_mb == 0
    assert local.resource_class == "LOCAL_MODEL_RESOURCE"
    assert manager.held().vram_mb == local.requirements.vram_mb
    assert manager.held().vram_mb == 8000


def test_hidden_nvidia_field_is_redacted() -> None:
    redactor = SecretRedactor()
    cleaned = redactor.redact_object({"nvidia_api_key": _KEY, "provider": "nvidia"})

    assert cleaned["nvidia_api_key"] != _KEY
    assert cleaned["provider"] == "nvidia"


def test_models_command_does_not_require_nvidia(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_MODEL", raising=False)
    settings = runtime_settings(tmp_path)
    omne = build_OMNE(settings)
    view = {str(item["id"]): item for item in omne.model_views()}
    status = omne.nvidia_status()
    rendered = json.dumps(status)

    assert view["nvidia-reasoning"]["provider"] == "nvidia"
    assert view["nvidia-reasoning"]["resource_class"] == "CLOUD_MODEL_RESOURCE"
    assert view["nvidia-reasoning"]["availability"] == "unavailable"
    assert view["nvidia-reasoning"]["vram_mb"] == 0
    assert view["mock-default"]["availability"] == "available"
    assert status["nvidia"] == "NOT CONFIGURED"
    assert status["provider"] == "UNAVAILABLE"
    assert status["inference"] == "NOT RUN"
    assert _KEY not in rendered
    assert omne.request_model("reasoning")["provider"] == "mock"
    kinds = [event.type for event in omne.list_events()]
    assert "model.provider.unavailable" in kinds
    assert "model.provider.available" in kinds

    code = main(["--config", str(_config(tmp_path)), "check"])
    assert code == 0
    captured = capsys.readouterr()
    assert "ok" in captured.out
    assert _KEY not in captured.out


def test_models_status_lines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_MODEL", raising=False)
    code = main(["--config", str(_config(tmp_path)), "models"])
    captured = capsys.readouterr()

    assert code == 0
    assert "NVIDIA: NOT CONFIGURED" in captured.out
    assert "Provider: UNAVAILABLE" in captured.out
    assert "Inference: NOT RUN" in captured.out
    assert "NVIDIA_API_KEY" not in captured.out
    assert _KEY not in captured.out


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "OMNE.toml"
    path.write_text(
        "\n".join(
            [
                'environment = "testing"',
                'log_level = "ERROR"',
                f'workspace_root = "{tmp_path / "workspace"}"',
                f'data_dir = "{tmp_path / "memory"}"',
                f'agents_dir = "{Path("agents").resolve()}"',
                f'models_dir = "{Path("models/manifests").resolve()}"',
            ]
        ),
        encoding="utf-8",
    )
    return path
