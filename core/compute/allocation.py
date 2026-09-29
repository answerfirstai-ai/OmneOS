"""Deterministic resource allocation."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from core.compute.monitor import ResourceSnapshot
from core.compute.requirements import ResourceRequirements


class AllocationDecision(StrEnum):
    """What the allocator tells the scheduler to do."""

    ALLOW = "ALLOW"
    WAIT = "WAIT"
    DEFER = "DEFER"
    USE_DIFFERENT_MODEL = "USE_DIFFERENT_MODEL"
    USE_CLOUD = "USE_CLOUD"
    DENY = "DENY"


class AllocationRequest(BaseModel):
    """One allocation question."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requirements: ResourceRequirements
    local: bool
    cloud_available: bool


def allocate(
    snapshot: ResourceSnapshot, request: AllocationRequest
) -> tuple[AllocationDecision, str]:
    """Return a decision that depends only on the snapshot and the request."""

    requirements = request.requirements
    if request.local and not requirements.ram_known:
        return AllocationDecision.DEFER, "local memory requirement is unknown"
    if request.local and not requirements.vram_known and requirements.vram_mb > 0:
        return AllocationDecision.DEFER, "local video memory requirement is unknown"

    available_ram = snapshot.memory.available_mb
    if requirements.ram_mb > 0 and available_ram is None:
        return AllocationDecision.DEFER, "memory telemetry is unknown"
    if available_ram is not None and requirements.ram_mb > available_ram:
        if request.cloud_available and request.local:
            return AllocationDecision.USE_CLOUD, "local memory is below the declared requirement"
        if request.cloud_available:
            return AllocationDecision.USE_DIFFERENT_MODEL, "selected model exceeds available memory"
        return AllocationDecision.DENY, "memory requirement exceeds available memory"

    if requirements.vram_mb > 0:
        gpu_available = snapshot.gpu.available is True
        free_vram = _free_vram(snapshot)
        fits = gpu_available and free_vram is not None and free_vram >= requirements.vram_mb
        if not fits:
            if request.cloud_available:
                return (
                    AllocationDecision.USE_CLOUD,
                    "local video memory cannot satisfy the requirement",
                )
            return AllocationDecision.DENY, "video memory requirement cannot be satisfied"

    cpu_usage = snapshot.cpu.usage_percent
    if requirements.cpu_threads >= 2 and cpu_usage is not None and cpu_usage > 90:
        return AllocationDecision.WAIT, "cpu usage is above 90 percent"
    if (
        available_ram is not None
        and requirements.ram_mb > 0
        and available_ram < requirements.ram_mb * 2
        and cpu_usage is not None
        and cpu_usage > 85
    ):
        return AllocationDecision.DEFER, "cpu and memory headroom are both low"
    return AllocationDecision.ALLOW, "requirements fit the snapshot"


def _free_vram(snapshot: ResourceSnapshot) -> float | None:
    total = snapshot.gpu.vram_total_mb
    used = snapshot.gpu.vram_used_mb
    if total is None or used is None:
        return None
    return total - used
