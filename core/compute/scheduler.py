"""Reserve declared resources against a snapshot."""

from __future__ import annotations

from core.compute.allocation import AllocationDecision, AllocationRequest, allocate
from core.compute.monitor import ResourceSnapshot, SystemMonitor
from core.compute.requirements import ResourceRequirements


class ComputeScheduler:
    """Track in-flight reservations and ask the allocator before starting work."""

    def __init__(self, monitor: SystemMonitor) -> None:
        self._monitor = monitor
        self._reserved_ram = 0
        self._reserved_vram = 0

    def request(
        self,
        requirements: ResourceRequirements,
        *,
        local: bool,
        cloud_available: bool,
        snapshot: ResourceSnapshot | None = None,
    ) -> AllocationDecision:
        current = snapshot or self._monitor.snapshot()
        adjusted = _subtract(current, self._reserved_ram, self._reserved_vram)
        decision, _reason = allocate(
            adjusted,
            AllocationRequest(
                requirements=requirements,
                local=local,
                cloud_available=cloud_available,
            ),
        )
        if decision is AllocationDecision.ALLOW:
            self._reserved_ram += requirements.ram_mb
            self._reserved_vram += requirements.vram_mb
        return decision

    def release(self, requirements: ResourceRequirements) -> None:
        self._reserved_ram = max(0, self._reserved_ram - requirements.ram_mb)
        self._reserved_vram = max(0, self._reserved_vram - requirements.vram_mb)


def _subtract(snapshot: ResourceSnapshot, ram_mb: int, vram_mb: int) -> ResourceSnapshot:
    memory = snapshot.memory
    gpu = snapshot.gpu
    available = None if memory.available_mb is None else max(0.0, memory.available_mb - ram_mb)
    free_vram = None
    if gpu.vram_total_mb is not None and gpu.vram_used_mb is not None:
        free_vram = max(0.0, gpu.vram_total_mb - gpu.vram_used_mb - vram_mb)
    updated_gpu = gpu
    if free_vram is not None and gpu.vram_total_mb is not None:
        updated_gpu = gpu.model_copy(update={"vram_used_mb": gpu.vram_total_mb - free_vram})
    return snapshot.model_copy(
        update={
            "memory": memory.model_copy(update={"available_mb": available}),
            "gpu": updated_gpu,
        }
    )
