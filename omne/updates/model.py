"""Update records. The core plans package changes and does not apply them to the host.

Channels stay separate. A missing signature or a hash mismatch stays a rejection.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ChannelName = Literal["linux", "omne", "application", "model"]
SlotName = Literal["A", "B"]
CHANNELS: tuple[ChannelName, ...] = ("linux", "omne", "application", "model")
OMNE_PACKAGES = frozenset({"omne-core", "omne-shell", "omne-system"})


class UpdatePhase(StrEnum):
    """Where one generation sits. Installing is not booted."""

    CHECKED = "checked"
    DOWNLOADED = "downloaded"
    VERIFIED = "verified"
    INSTALLING = "installing"
    STAGED = "staged"
    INSTALLED = "installed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    REJECTED = "rejected"


class PackageRecord(BaseModel):
    """One artifact named by a signed catalog."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=64)
    version: str = Field(min_length=1, max_length=64)
    filename: str = Field(min_length=1, max_length=180)
    sha256: str = Field(min_length=64, max_length=64)
    size: int = Field(ge=0)
    reboot: bool = False


class ChannelCatalog(BaseModel):
    """Signed metadata for one channel. The signature is a sibling file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    channel: ChannelName
    version: str = Field(min_length=1, max_length=64)
    packages: list[PackageRecord] = Field(default_factory=list)
    reboot_required: bool = False


class ChannelResult(BaseModel):
    """The outcome of checking one channel. Rejected channels are not staged."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    channel: ChannelName
    version: str = ""
    phase: UpdatePhase
    reason: str
    reboot_required: bool = False
    packages: list[str] = Field(default_factory=list)
    commands: list[list[str]] = Field(default_factory=list)
    verified: bool = False


class Generation(BaseModel):
    """One update attempt. The booted generation is the rollback target."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    channel: ChannelName
    version: str
    phase: UpdatePhase
    slot: SlotName
    reboot_required: bool
    packages: list[str] = Field(default_factory=list)
    booted: bool = False


class RollbackState(BaseModel):
    """The generation a rollback would restore. It does not write the bootloader."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    available: bool
    target: str | None = None
    slot: SlotName | None = None
    version: str = ""


class UpdateStatus(BaseModel):
    """What OMNE knows about updates. The host package database is unchanged."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: Literal["catalog", "none"]
    automatic: bool = False
    host_protected: bool = True
    host_updated: bool = False
    boot_slot: SlotName = "A"
    pending_slot: SlotName | None = None
    reboot_required: bool = False
    rollback: RollbackState
    channels: list[ChannelResult] = Field(default_factory=list)
    history: list[Generation] = Field(default_factory=list)


class UpdatePlan(BaseModel):
    """A dry-run or a refused install. Commands are apt plans, not a subprocess."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dry_run: bool
    executed: bool = False
    host_updated: bool = False
    channels: list[ChannelResult] = Field(default_factory=list)


class UpdateState(BaseModel):
    """Persisted history. Installing generations are recovered as interrupted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    boot_slot: SlotName = "A"
    booted_generation: str | None = None
    pending_generation: str | None = None
    generations: list[Generation] = Field(default_factory=list)
