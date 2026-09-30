"""Storage records. OMNE reads published disks and mounts. It does not format them.

A missing size stays null. Raw device contents are not part of the record.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ProviderName = Literal["mock", "linux"]
PartitionRole = Literal["system", "boot", "user", "device", "omne", "unknown"]
StorageEventType = Literal[
    "storage.disk.added",
    "storage.disk.removed",
    "storage.partition.added",
    "storage.partition.removed",
    "storage.mount.added",
    "storage.mount.removed",
    "storage.space.changed",
]


class Disk(BaseModel):
    """One whole disk. ``device`` is a name, not an open handle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    device: str = Field(min_length=1)
    size_bytes: int | None = Field(default=None, ge=0)
    removable: bool
    read_only: bool
    protected: bool
    rotational: bool | None = None


class Partition(BaseModel):
    """One partition. A protected partition is not a write target."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    disk: str = Field(min_length=1)
    device: str = Field(min_length=1)
    size_bytes: int | None = Field(default=None, ge=0)
    removable: bool
    read_only: bool
    protected: bool
    role: PartitionRole


class FilesystemMount(BaseModel):
    """One mounted filesystem and the space the kernel reported for it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    device: str = Field(min_length=1)
    mount: str = Field(min_length=1)
    type: str = Field(min_length=1)
    read_only: bool
    removable: bool
    used_bytes: int | None = Field(default=None, ge=0)
    free_bytes: int | None = Field(default=None, ge=0)
    role: PartitionRole
    protected: bool


class StorageState(BaseModel):
    """One read of disks, partitions, and mounts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: ProviderName
    observed: bool
    disks: list[Disk] = Field(default_factory=list)
    partitions: list[Partition] = Field(default_factory=list)
    filesystems: list[FilesystemMount] = Field(default_factory=list)
    raw_access: bool = False
    formatting: bool = False
    gaps: list[str] = Field(default_factory=list)

    @field_validator("raw_access", "formatting")
    @classmethod
    def _stay_closed(cls, value: bool) -> bool:
        if value:
            raise ValueError("storage mutation must stay closed")
        return value


class StorageEvent(BaseModel):
    """One storage change. Payloads name a disk or a mount, not file contents."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: StorageEventType
    payload: dict[str, Any] = Field(default_factory=dict)
