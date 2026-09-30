"""Deterministic resource allocation.

Decisions use the snapshot and the resources already reserved. Missing
measurements stay unknown. This module does not invent a CPU count, a GPU, or
a temperature.
"""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class ResourceLedger:
    """Resources already held by RESERVE and RUN reservations."""

    cpu_threads: int = 0
    ram_mb: int = 0
    vram_mb: int = 0
    disk_mb: int = 0
    gpus: int = 0


def allocate(
    snapshot: ResourceSnapshot,
    request: AllocationRequest,
    *,
    held: ResourceLedger | None = None,
) -> tuple[AllocationDecision, str]:
    """Return a decision that depends only on the snapshot, the request, and holds."""

    requirements = request.requirements
    reserved = held or ResourceLedger()
    if request.local and not requirements.ram_known:
        return AllocationDecision.DEFER, "local memory requirement is unknown"
    if request.local and not requirements.vram_known and _needs_video(requirements):
        return AllocationDecision.DEFER, "local video memory requirement is unknown"

    memory = _memory(snapshot, request, requirements, reserved)
    if memory is not None:
        return memory
    disk = _disk(snapshot, requirements, reserved)
    if disk is not None:
        return disk
    video = _video(snapshot, request, requirements, reserved)
    if video is not None:
        return video
    processor = _cpu(snapshot, request, requirements, reserved)
    if processor is not None:
        return processor
    if _thermal_pressure(snapshot, requirements):
        return AllocationDecision.WAIT, "thermal reading is high"

    available_ram = snapshot.memory.available_mb
    remaining_ram = None if available_ram is None else available_ram - reserved.ram_mb
    cpu_usage = snapshot.cpu.usage_percent
    if (
        remaining_ram is not None
        and requirements.ram_mb > 0
        and remaining_ram < requirements.ram_mb * 2
        and cpu_usage is not None
        and cpu_usage > 85
    ):
        return AllocationDecision.DEFER, "cpu and memory headroom are both low"
    return AllocationDecision.ALLOW, "requirements fit the snapshot"


def _needs_video(requirements: ResourceRequirements) -> bool:
    return requirements.gpu or requirements.vram_mb > 0


def _memory(
    snapshot: ResourceSnapshot,
    request: AllocationRequest,
    requirements: ResourceRequirements,
    held: ResourceLedger,
) -> tuple[AllocationDecision, str] | None:
    if requirements.ram_mb <= 0:
        return None
    available = snapshot.memory.available_mb
    if available is None:
        return AllocationDecision.DEFER, "memory telemetry is unknown"
    if requirements.ram_mb > available:
        return _unsatisfiable(
            request,
            local_reason="local memory is below the declared requirement",
            other_reason="selected model exceeds available memory",
            deny_reason="memory requirement exceeds available memory",
        )
    if requirements.ram_mb > available - held.ram_mb:
        return AllocationDecision.WAIT, "memory is reserved"
    return None


def _disk(
    snapshot: ResourceSnapshot,
    requirements: ResourceRequirements,
    held: ResourceLedger,
) -> tuple[AllocationDecision, str] | None:
    if requirements.disk_mb <= 0:
        return None
    available = snapshot.disk.available_mb
    if available is None:
        return AllocationDecision.DEFER, "disk telemetry is unknown"
    if requirements.disk_mb > available:
        return AllocationDecision.DENY, "disk requirement exceeds available disk"
    if requirements.disk_mb > available - held.disk_mb:
        return AllocationDecision.WAIT, "disk is reserved"
    return None


def _video(
    snapshot: ResourceSnapshot,
    request: AllocationRequest,
    requirements: ResourceRequirements,
    held: ResourceLedger,
) -> tuple[AllocationDecision, str] | None:
    if not _needs_video(requirements):
        return None
    if snapshot.gpu.available is None:
        return AllocationDecision.DEFER, "gpu telemetry is unavailable"
    free = _free_vram(snapshot)
    if snapshot.gpu.available is True and requirements.vram_mb > 0 and free is None:
        return AllocationDecision.DEFER, "video memory telemetry is unknown"
    if snapshot.gpu.available is not True:
        return _unsatisfiable(
            request,
            local_reason="local video memory cannot satisfy the requirement",
            other_reason="selected model exceeds available video memory",
            deny_reason="video memory requirement cannot be satisfied",
        )
    if requirements.vram_mb > 0 and free is not None and requirements.vram_mb > free:
        return _unsatisfiable(
            request,
            local_reason="local video memory cannot satisfy the requirement",
            other_reason="selected model exceeds available video memory",
            deny_reason="video memory requirement cannot be satisfied",
        )
    if requirements.vram_mb > 0 and free is not None and requirements.vram_mb > free - held.vram_mb:
        return AllocationDecision.WAIT, "video memory is reserved"
    if requirements.gpu and requirements.vram_mb == 0:
        count = snapshot.gpu.count
        if count is None:
            return AllocationDecision.DEFER, "gpu telemetry is unavailable"
        if count <= 0:
            return _unsatisfiable(
                request,
                local_reason="local video memory cannot satisfy the requirement",
                other_reason="selected model exceeds available video memory",
                deny_reason="video memory requirement cannot be satisfied",
            )
        if held.gpus >= count:
            return AllocationDecision.WAIT, "gpu is reserved"
    usage = snapshot.gpu.usage_percent
    if usage is not None and usage > 90:
        return AllocationDecision.WAIT, "gpu utilization is above 90 percent"
    return None


def _cpu(
    snapshot: ResourceSnapshot,
    request: AllocationRequest,
    requirements: ResourceRequirements,
    held: ResourceLedger,
) -> tuple[AllocationDecision, str] | None:
    if requirements.cpu_threads < 2:
        return None
    usage = snapshot.cpu.usage_percent
    if usage is not None and usage > 90:
        return AllocationDecision.WAIT, "cpu usage is above 90 percent"
    count = snapshot.cpu.count
    if count is None:
        return AllocationDecision.DEFER, "cpu capacity is unknown"
    if requirements.cpu_threads > count:
        return _unsatisfiable(
            request,
            local_reason="local cpu cannot satisfy the requirement",
            other_reason="selected model exceeds available cpu",
            deny_reason="cpu requirement exceeds the machine",
        )
    if requirements.cpu_threads > count - held.cpu_threads:
        return AllocationDecision.WAIT, "cpu is reserved"
    return None


def _thermal_pressure(snapshot: ResourceSnapshot, requirements: ResourceRequirements) -> bool:
    reading = snapshot.thermal.celsius
    return requirements.cpu_threads >= 2 and reading is not None and reading >= 95


def _unsatisfiable(
    request: AllocationRequest,
    *,
    local_reason: str,
    other_reason: str,
    deny_reason: str,
) -> tuple[AllocationDecision, str]:
    if request.cloud_available and request.local:
        return AllocationDecision.USE_CLOUD, local_reason
    if request.cloud_available:
        return AllocationDecision.USE_DIFFERENT_MODEL, other_reason
    return AllocationDecision.DENY, deny_reason


def _free_vram(snapshot: ResourceSnapshot) -> float | None:
    total = snapshot.gpu.vram_total_mb
    used = snapshot.gpu.vram_used_mb
    if total is None or used is None:
        return None
    return total - used
