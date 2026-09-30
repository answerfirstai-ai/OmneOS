"""Persist update history and recover an interrupted install.

An installing generation never becomes the booted slot. Loading it marks the
attempt interrupted and leaves the previous boot slot in place.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from omne.updates.model import Generation, RollbackState, SlotName, UpdatePhase, UpdateState


class UpdateStore:
    """Save generations beside the core data directory. This is not the host dpkg database."""

    def __init__(self, directory: Path | None) -> None:
        self._directory = directory
        self._state = UpdateState()
        if directory is not None:
            self._load()

    @property
    def state(self) -> UpdateState:
        return self._state

    def save(self, state: UpdateState) -> UpdateState:
        self._state = state
        directory = self._directory
        if directory is None:
            return state
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "state.json"
        path.write_text(
            json.dumps(state.model_dump(mode="json"), sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        return state

    def replace(self, **updates: object) -> UpdateState:
        return self.save(self._state.model_copy(update=updates))

    def generation(self, generation_id: str | None) -> Generation | None:
        if generation_id is None:
            return None
        for item in self._state.generations:
            if item.id == generation_id:
                return item
        return None

    def rollback_target(self) -> RollbackState:
        if any(item.phase is UpdatePhase.STAGED for item in self._state.generations):
            booted = self.generation(self._state.booted_generation)
            if booted is None:
                return RollbackState(available=True, target=None, slot=self._state.boot_slot)
            return RollbackState(
                available=True,
                target=booted.id,
                slot=booted.slot,
                version=booted.version,
            )
        previous = _previous_booted(self._state)
        if previous is None:
            return RollbackState(available=False)
        return RollbackState(
            available=True,
            target=previous.id,
            slot=previous.slot,
            version=previous.version,
        )

    def _load(self) -> None:
        directory = self._directory
        if directory is None:
            return
        path = directory / "state.json"
        if not path.is_file():
            return
        try:
            loaded = UpdateState.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeError, json.JSONDecodeError, ValidationError):
            self._state = UpdateState()
            return
        self._state = _recover(loaded)
        if self._state != loaded:
            self.save(self._state)


def other_slot(slot: SlotName) -> SlotName:
    if slot == "A":
        return "B"
    return "A"


def _recover(state: UpdateState) -> UpdateState:
    changed = False
    generations: list[Generation] = []
    pending = state.pending_generation
    for item in state.generations:
        if item.phase is UpdatePhase.INSTALLING:
            generations.append(item.model_copy(update={"phase": UpdatePhase.INTERRUPTED}))
            if pending == item.id:
                pending = None
            changed = True
            continue
        generations.append(item)
    if not changed:
        return state
    return state.model_copy(update={"generations": generations, "pending_generation": pending})


def _previous_booted(state: UpdateState) -> Generation | None:
    current = state.booted_generation
    found: Generation | None = None
    for item in state.generations:
        if item.phase is not UpdatePhase.INSTALLED or item.id == current:
            continue
        found = item
    return found
