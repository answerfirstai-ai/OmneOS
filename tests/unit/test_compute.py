"""Telemetry, allocation, and model-cache metadata."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from core.compute.allocation import AllocationDecision, AllocationRequest, allocate
from core.compute.model_cache import ModelCache
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


def _snapshot(
    *,
    cpu: float | None = 10,
    available_ram: float | None = 4096,
    gpu: bool | None = False,
    free_vram: float | None = None,
) -> ResourceSnapshot:
    vram_total = None if free_vram is None else free_vram + 100
    vram_used = None if free_vram is None else 100
    return ResourceSnapshot(
        cpu=CpuTelemetry(usage_percent=cpu),
        memory=MemoryTelemetry(
            total_mb=8192 if available_ram is not None else None,
            available_mb=available_ram,
            used_mb=None if available_ram is None else 8192 - available_ram,
        ),
        gpu=GpuTelemetry(
            available=gpu,
            vram_total_mb=vram_total,
            vram_used_mb=vram_used,
        ),
        disk=DiskTelemetry(total_mb=1000, used_mb=100, available_mb=900),
        network=NetworkTelemetry(available=True),
    )


def _request(
    *,
    ram_mb: int = 64,
    vram_mb: int = 0,
    threads: int = 1,
    local: bool = True,
    cloud: bool = False,
    ram_known: bool = True,
    vram_known: bool = True,
) -> AllocationRequest:
    return AllocationRequest(
        requirements=ResourceRequirements(
            ram_mb=ram_mb,
            vram_mb=vram_mb,
            cpu_threads=threads,
            ram_known=ram_known,
            vram_known=vram_known,
        ),
        local=local,
        cloud_available=cloud,
    )


def test_live_snapshot_uses_host_sources() -> None:
    snapshot = SystemMonitor().snapshot()

    assert snapshot.memory.total_mb is not None
    assert snapshot.cpu.usage_percent is not None
    assert snapshot.disk.total_mb is not None
    assert snapshot.network.available is True
    assert snapshot.cpu.count is None or snapshot.cpu.count >= 1
    assert snapshot.thermal.celsius is None or isinstance(snapshot.thermal.celsius, float)
    if snapshot.gpu.available is False:
        assert snapshot.gpu.count == 0
    elif snapshot.gpu.available is None:
        assert snapshot.gpu.count is None


def test_snapshot_is_reused_within_the_ttl(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monitor = SystemMonitor(sample_seconds=0.05, cache_ttl=5)
    calls = {"cpu": 0}
    original = monitor.cpu

    def counted() -> CpuTelemetry:
        calls["cpu"] += 1
        return original()

    monkeypatch.setattr(monitor, "cpu", counted)
    first = monitor.snapshot()
    started = time.perf_counter()
    second = monitor.snapshot()
    elapsed = time.perf_counter() - started

    assert second == first
    assert calls["cpu"] == 1
    assert elapsed < 0.02

    monitor.snapshot(disk_path=tmp_path)
    assert calls["cpu"] == 2
    monitor.snapshot()
    assert calls["cpu"] == 2


def test_allocator_decisions() -> None:
    allow, _ = allocate(_snapshot(), _request())
    deny, _ = allocate(_snapshot(available_ram=32), _request(ram_mb=64))
    defer, _ = allocate(_snapshot(available_ram=None), _request(ram_mb=64))
    unknown, _ = allocate(_snapshot(), _request(local=True, ram_known=False))
    cloud, _ = allocate(_snapshot(available_ram=32), _request(ram_mb=64, cloud=True))
    wait, _ = allocate(_snapshot(cpu=95), _request(threads=2))
    vram, _ = allocate(_snapshot(gpu=False), _request(vram_mb=100, cloud=True))

    assert allow is AllocationDecision.ALLOW
    assert deny is AllocationDecision.DENY
    assert defer is AllocationDecision.DEFER
    assert unknown is AllocationDecision.DEFER
    assert cloud is AllocationDecision.USE_CLOUD
    assert wait is AllocationDecision.WAIT
    assert vram is AllocationDecision.USE_CLOUD


def test_missing_sources_stay_null(tmp_path: Path) -> None:
    monitor = SystemMonitor(root=tmp_path, sample_seconds=0)

    assert monitor.cpu().count is None
    assert monitor.cpu().usage_percent is None
    assert monitor.memory().available_mb is None
    assert monitor.thermal().celsius is None
    assert monitor.network().available is False
    assert monitor.network().interfaces == []


def test_cpu_count_and_thermal_use_only_the_provided_files(tmp_path: Path) -> None:
    stat = tmp_path / "proc" / "stat"
    stat.parent.mkdir(parents=True)
    stat.write_text(
        "cpu 10 0 0 10 0 0 0 0\ncpu0 5 0 0 5 0 0 0 0\ncpu1 5 0 0 5 0 0 0 0\n",
        encoding="utf-8",
    )
    unrelated = tmp_path / "sys" / "class" / "thermal" / "thermal_zone0"
    unrelated.mkdir(parents=True)
    (unrelated / "type").write_text("acpitz\n", encoding="utf-8")
    (unrelated / "temp").write_text("30000\n", encoding="utf-8")
    package = tmp_path / "sys" / "class" / "thermal" / "thermal_zone1"
    package.mkdir()
    (package / "type").write_text("x86_pkg_temp\n", encoding="utf-8")
    (package / "temp").write_text("47000\n", encoding="utf-8")
    monitor = SystemMonitor(root=tmp_path, sample_seconds=0)

    assert monitor.cpu().count == 2
    assert monitor.thermal().celsius == 47.0


def test_gpu_probe_does_not_invent_a_device(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("core.compute.monitor.shutil.which", lambda _name: None)
    missing = SystemMonitor().gpu()

    assert missing.available is False
    assert missing.count == 0
    assert missing.usage_percent is None
    assert missing.vram_total_mb is None

    def timeout(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd="nvidia-smi", timeout=2)

    monkeypatch.setattr("core.compute.monitor.shutil.which", lambda _name: "nvidia-smi")
    monkeypatch.setattr("core.compute.monitor.subprocess.run", timeout)
    failed = SystemMonitor().gpu()

    assert failed.available is None
    assert failed.count is None
    assert failed.vram_used_mb is None
    assert failed.usage_percent is None


def test_model_cache_does_not_load_weights() -> None:
    cache = ModelCache()
    cache.register("local-default", size_bytes=None)

    loaded = cache.load("local-default")
    evicted = cache.evict("local-default")

    assert loaded.performed is False
    assert "weights" in loaded.reason
    assert evicted.performed is False
