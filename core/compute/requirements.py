"""Declared resource requirements.

Numeric fields are declarations made by an agent or model manifest. They are
not measurements. ``ram_known`` and ``vram_known`` stay false when the
manifest does not know how much hardware a local model needs.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ResourceRequirements(BaseModel):
    """Hardware a workload declares that it needs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ram_mb: int = Field(default=0, ge=0)
    vram_mb: int = Field(default=0, ge=0)
    cpu_threads: int = Field(default=1, ge=0)
    disk_mb: int = Field(default=0, ge=0)
    gpu: bool = False
    ram_known: bool = True
    vram_known: bool = True
