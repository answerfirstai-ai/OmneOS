"""The hub shares native configuration, compute admission and events."""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from tests.support import runtime_settings

from core.api.runtime import build_OMNE
from core.api.server import CoreServer
from core.compute.manager import ReservationState
from core.harnesses.models import OMNEModels
from core.harnesses.service import HubService
from core.harnesses.store import Store
from core.models.registry import ModelMetadata
from core.models.types import GenerateResponse, ProviderError, Usage


def test_native_http_mount_requires_token_and_origin(tmp_path: Path) -> None:
    settings = runtime_settings(tmp_path).model_copy(update={"port": 0})
    runtime = build_OMNE(settings)
    server = CoreServer(settings, runtime)
    server.start_in_thread()
    root = f"http://127.0.0.1:{server.port}"
    token = (settings.data_dir / "hub-token").read_text()
    try:
        with urllib.request.urlopen(root + "/hub/") as res:
            assert b"OMNE OS" in res.read()
        with pytest.raises(urllib.error.HTTPError) as denied:
            urllib.request.urlopen(root + "/hub/api/state")
        assert denied.value.code == 401
        req = urllib.request.Request(
            root + "/hub/api/state",
            headers={
                "Authorization": "Bearer " + token,
                "Origin": root,
            },
        )
        with urllib.request.urlopen(req) as res:
            state = json.load(res)
            assert state["harnesses"] == []
            assert state["integration"] == "OMNE OS"
            assert any(m["id"] == "auto" for m in state["models"])
            assert not any(m["ready"] for m in state["models"])
        req.add_header("Origin", "https://untrusted.example")
        with pytest.raises(urllib.error.HTTPError) as denied:
            urllib.request.urlopen(req)
        assert denied.value.code == 403
    finally:
        server.stop()


def test_harness_events_reach_native_bus(tmp_path: Path) -> None:
    settings = runtime_settings(tmp_path)
    runtime = build_OMNE(settings)
    hub = HubService(runtime, settings.data_dir)
    try:
        hub.store.event("World ready", "h-test")
        events = runtime.list_events()
        assert events[-1].type == "harness.updated"
        assert events[-1].payload["harness_id"] == "h-test"
    finally:
        hub.close()


def test_bridge_reuses_native_model_and_settles_usage(tmp_path: Path) -> None:
    runtime = build_OMNE(runtime_settings(tmp_path))
    runtime.generate_harness = AsyncMock(
        return_value=GenerateResponse(
            text="artifact",
            provider="test",
            model="test",
            usage=Usage(input_tokens=7, output_tokens=9),
        )
    )
    store = Store(tmp_path / "harnesses.sqlite")
    try:
        bridge = OMNEModels(runtime, store)
        assert (
            bridge.call("test", [{"role": "user", "content": "hello"}], {"daily_tokens": 50000})
            == "artifact"
        )
        assert store.used() == 16
        runtime.generate_harness.assert_awaited_once()
    finally:
        store.db.close()


def test_mock_cannot_masquerade_as_live_harness_model(tmp_path: Path) -> None:
    runtime = build_OMNE(runtime_settings(tmp_path))
    mock_id = next(m["id"] for m in runtime.model_views() if m["provider"] == "mock")
    with pytest.raises(ValueError, match="real local or API"):
        asyncio.run(runtime.generate_harness(str(mock_id), "hello", "system"))


def test_cloud_provider_reservation_is_released_on_failure(tmp_path: Path) -> None:
    runtime = build_OMNE(runtime_settings(tmp_path))
    model = ModelMetadata(
        id="test-cloud", provider="xai", model_name="test", capabilities=["reasoning"], local=False
    )
    runtime._models.register(model)
    runtime._available_model_ids = lambda: {"test-cloud"}
    provider = AsyncMock()
    provider.generate.side_effect = ProviderError("unavailable", code="timeout", provider="test")
    runtime._providers["test-cloud"] = provider
    with pytest.raises(ValueError, match="timeout"):
        asyncio.run(runtime.generate_harness("test-cloud", "hello", "system"))
    assert runtime.resources is not None
    reservations = runtime.resources._reservations.values()
    assert any(r.owner == "harness:test-cloud" for r in reservations)
    assert all(r.state is ReservationState.RELEASE for r in reservations)
