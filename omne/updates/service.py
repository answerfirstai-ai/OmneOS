"""Check, verify, stage, and roll back updates.

Staging writes a pending slot under OMNE's data directory. It does not call
apt or dpkg, and it does not change the booted slot. A dry-run only reports
the plan.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from omne.updates.catalog import load_catalog, package_path, verify_package
from omne.updates.model import (
    CHANNELS,
    ChannelName,
    ChannelResult,
    Generation,
    UpdatePhase,
    UpdatePlan,
    UpdateState,
    UpdateStatus,
)
from omne.updates.plan import install_commands
from omne.updates.state import UpdateStore, other_slot
from omne.updates.verify import VerificationError

EventSink = Callable[[str, dict[str, Any]], None]


class UpdateRejected(Exception):
    """An update cannot be staged or rolled back."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.code = "rejected"


class UpdateService:
    """The OMNE update layer. Host installation stays off."""

    def __init__(
        self,
        state_dir: Path | None,
        *,
        host_protected: bool = True,
        sink: EventSink | None = None,
    ) -> None:
        self._store = UpdateStore(state_dir)
        self._host_protected = host_protected
        self._sink = sink
        self._state_dir = state_dir

    def status(self, catalog: Path | None = None) -> UpdateStatus:
        """Report history and, when a catalog is given, verify it without staging."""

        channels = self.inspect(catalog) if catalog is not None else []
        return self._status(channels)

    def inspect(self, catalog: Path, *, dry_run: bool = True) -> list[ChannelResult]:
        """Verify each present channel. A failure rejects that channel."""

        results: list[ChannelResult] = []
        for channel in CHANNELS:
            if not (catalog / channel / "updates.json").is_file():
                continue
            results.append(self._check_channel(catalog, channel, dry_run=dry_run))
        return results

    def plan(self, catalog: Path, *, dry_run: bool = True) -> UpdatePlan:
        """Return the apt plan. Installation is refused when this host is protected."""

        if not dry_run:
            raise UpdateRejected("refusing to install updates on this host")
        channels = self.inspect(catalog)
        self._emit("update.checked", {"channels": [item.channel for item in channels]})
        return UpdatePlan(dry_run=True, executed=False, host_updated=False, channels=channels)

    def stage(self, catalog: Path) -> UpdateStatus:
        """Copy verified artifacts into the pending slot. The booted slot stays put."""

        if not self._host_protected:
            raise UpdateRejected("refusing to install updates on this host")
        channels = self.inspect(catalog, dry_run=False)
        if not channels:
            raise UpdateRejected("no updates")
        if any(not item.verified for item in channels):
            self._emit(
                "update.rejected",
                {"channels": [item.channel for item in channels if not item.verified]},
            )
            raise UpdateRejected("update was not verified")
        for item in channels:
            self._stage_channel(catalog, item)
        self._emit("update.staged", {"channels": [item.channel for item in channels]})
        return self._status(channels)

    def commit(self) -> UpdateStatus:
        """Record the pending slot as booted after a reboot. This does not reboot."""

        state = self._store.state
        staged = [item for item in state.generations if item.phase is UpdatePhase.STAGED]
        if not staged:
            raise UpdateRejected("no verified pending update")
        newest = staged[-1]
        staged_ids = {item.id for item in staged}
        generations = []
        for item in state.generations:
            if item.id in staged_ids:
                generations.append(
                    item.model_copy(
                        update={"phase": UpdatePhase.INSTALLED, "booted": item.id == newest.id}
                    )
                )
            elif item.booted:
                generations.append(item.model_copy(update={"booted": False}))
            else:
                generations.append(item)
        self._store.save(
            state.model_copy(
                update={
                    "generations": generations,
                    "booted_generation": newest.id,
                    "pending_generation": None,
                    "boot_slot": newest.slot,
                }
            )
        )
        self._emit("update.committed", {"generation": newest.id, "slot": newest.slot})
        return self._status([])

    def rollback(self) -> UpdateStatus:
        """Drop a pending slot, or restore the previous booted generation."""

        state = self._store.state
        staged = [item for item in state.generations if item.phase is UpdatePhase.STAGED]
        if staged:
            staged_ids = {item.id for item in staged}
            generations = [
                item.model_copy(update={"phase": UpdatePhase.ROLLED_BACK})
                if item.id in staged_ids
                else item
                for item in state.generations
            ]
            self._store.save(
                state.model_copy(update={"generations": generations, "pending_generation": None})
            )
            self._emit("update.rolled_back", {"generations": [item.id for item in staged]})
            return self._status([])
        target = _installed_before(state, state.booted_generation)
        current = self._store.generation(state.booted_generation)
        if target is None or current is None:
            raise UpdateRejected("rollback is not available")
        generations = []
        for item in state.generations:
            if item.id == current.id:
                generations.append(
                    item.model_copy(update={"phase": UpdatePhase.ROLLED_BACK, "booted": False})
                )
            elif item.id == target.id:
                generations.append(item.model_copy(update={"booted": True}))
            else:
                generations.append(item)
        self._store.save(
            state.model_copy(
                update={
                    "generations": generations,
                    "booted_generation": target.id,
                    "boot_slot": target.slot,
                    "pending_generation": None,
                }
            )
        )
        self._emit("update.rolled_back", {"generation": current.id, "target": target.id})
        return self._status([])

    def _check_channel(
        self, catalog: Path, channel: ChannelName, *, dry_run: bool
    ) -> ChannelResult:
        try:
            loaded = load_catalog(catalog, channel, public_key=catalog / "trusted.pub")
            for package in loaded.packages:
                verify_package(package_path(catalog, channel, package), package)
        except VerificationError as exc:
            return ChannelResult(channel=channel, phase=UpdatePhase.REJECTED, reason=str(exc))
        reboot = loaded.reboot_required or any(item.reboot for item in loaded.packages)
        if channel == "linux":
            reboot = True
        return ChannelResult(
            channel=channel,
            version=loaded.version,
            phase=UpdatePhase.VERIFIED,
            reason="verified",
            reboot_required=reboot,
            packages=[item.name for item in loaded.packages],
            commands=install_commands(loaded, dry_run=dry_run),
            verified=True,
        )

    def _stage_channel(self, catalog: Path, result: ChannelResult) -> None:
        state = self._store.state
        slot = other_slot(state.boot_slot)
        generation = Generation(
            id=str(uuid4()),
            channel=result.channel,
            version=result.version,
            phase=UpdatePhase.INSTALLING,
            slot=slot,
            reboot_required=result.reboot_required,
            packages=list(result.packages),
        )
        generations = [*state.generations, generation]
        self._store.save(
            state.model_copy(
                update={"generations": generations, "pending_generation": generation.id}
            )
        )
        try:
            self._copy_channel(catalog, result.channel, generation.id)
        except VerificationError as exc:
            self._mark(generation.id, UpdatePhase.FAILED)
            raise UpdateRejected(str(exc)) from exc
        except OSError as exc:
            self._mark(generation.id, UpdatePhase.FAILED)
            raise UpdateRejected("update package could not be staged") from exc
        self._mark(generation.id, UpdatePhase.STAGED)

    def _copy_channel(self, catalog: Path, channel: ChannelName, generation_id: str) -> None:
        directory = self._state_dir
        if directory is None:
            raise OSError("update state directory is missing")
        loaded = load_catalog(catalog, channel, public_key=catalog / "trusted.pub")
        destination = directory / "staging" / generation_id
        destination.mkdir(parents=True, exist_ok=True)
        for package in loaded.packages:
            source = package_path(catalog, channel, package)
            verify_package(source, package)
            target = destination / Path(package.filename).name
            shutil.copyfile(source, target)
            verify_package(target, package)

    def _mark(self, generation_id: str, phase: UpdatePhase) -> None:
        state = self._store.state
        generations = [
            item.model_copy(update={"phase": phase}) if item.id == generation_id else item
            for item in state.generations
        ]
        pending = state.pending_generation
        if (
            phase in {UpdatePhase.FAILED, UpdatePhase.INTERRUPTED, UpdatePhase.ROLLED_BACK}
            and pending == generation_id
        ):
            pending = None
        self._store.save(
            state.model_copy(update={"generations": generations, "pending_generation": pending})
        )

    def _status(self, channels: list[ChannelResult]) -> UpdateStatus:
        state = self._store.state
        staged = [item for item in state.generations if item.phase is UpdatePhase.STAGED]
        pending_slot = staged[-1].slot if staged else None
        reboot = any(item.reboot_required for item in staged)
        return UpdateStatus(
            provider="catalog" if channels or state.generations else "none",
            automatic=False,
            host_protected=self._host_protected,
            host_updated=False,
            boot_slot=state.boot_slot,
            pending_slot=pending_slot,
            reboot_required=reboot,
            rollback=self._store.rollback_target(),
            channels=channels,
            history=list(state.generations),
        )

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._sink is not None:
            self._sink(event_type, payload)


def _installed_before(state: UpdateState, current: str | None) -> Generation | None:
    found: Generation | None = None
    for item in state.generations:
        if item.phase is UpdatePhase.INSTALLED and item.id != current:
            found = item
    return found
