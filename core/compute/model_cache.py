"""Metadata for a future local model cache.

Tiers are SSD, RAM, VRAM, and GPU. This module records metadata only. It does
not copy weights, and it does not treat storage as memory.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core.compute.requirements import ResourceRequirements

CacheState = Literal["registered", "unavailable"]
CacheLocation = Literal["not_loaded", "ssd", "ram", "vram", "gpu"]


class CacheRecord(BaseModel):
    """Tracked metadata for one model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str
    size_bytes: int | None = None
    last_access: datetime | None = None
    access_count: int = 0
    load_time_seconds: float | None = None
    state: CacheState = "registered"
    location: CacheLocation = "not_loaded"
    requirements: ResourceRequirements = Field(default_factory=ResourceRequirements)


class CacheOperation(BaseModel):
    """Result of a load or eviction request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str
    performed: bool
    reason: str


class ModelCache:
    """Track model cache metadata without loading weights."""

    def __init__(self) -> None:
        self._records: dict[str, CacheRecord] = {}

    def register(
        self,
        model_id: str,
        *,
        size_bytes: int | None,
        requirements: ResourceRequirements | None = None,
    ) -> CacheRecord:
        record = CacheRecord(
            model_id=model_id,
            size_bytes=size_bytes,
            requirements=requirements or ResourceRequirements(),
            state="registered" if size_bytes is not None else "unavailable",
        )
        self._records[model_id] = record
        return record

    def record_access(self, model_id: str, *, when: datetime | None = None) -> CacheRecord:
        current = self._require(model_id)
        updated = current.model_copy(
            update={
                "last_access": when or datetime.now(UTC),
                "access_count": current.access_count + 1,
            }
        )
        self._records[model_id] = updated
        return updated

    def get(self, model_id: str) -> CacheRecord:
        return self._require(model_id)

    def load(self, model_id: str) -> CacheOperation:
        self._require(model_id)
        return CacheOperation(
            model_id=model_id,
            performed=False,
            reason="no local runtime is configured to load model weights",
        )

    def evict(self, model_id: str) -> CacheOperation:
        record = self._require(model_id)
        if record.location == "not_loaded":
            return CacheOperation(
                model_id=model_id,
                performed=False,
                reason="model weights are not loaded",
            )
        return CacheOperation(
            model_id=model_id, performed=False, reason="eviction is not implemented"
        )

    def _require(self, model_id: str) -> CacheRecord:
        try:
            return self._records[model_id]
        except KeyError as exc:
            raise KeyError(f"model is not registered in the cache: {model_id}") from exc
