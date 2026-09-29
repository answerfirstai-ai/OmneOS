"""Telemetry, allocation, and model-cache metadata."""

from __future__ import annotations

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
    assert (
        snapshot.gpu.available is False
        or snapshot.gpu.available is True
        or snapshot.gpu.available is None
    )


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


def test_model_cache_does_not_load_weights() -> None:
    cache = ModelCache()
    cache.register("local-default", size_bytes=None)

    loaded = cache.load("local-default")
    evicted = cache.evict("local-default")

    assert loaded.performed is False
    assert "weights" in loaded.reason
    assert evicted.performed is False
