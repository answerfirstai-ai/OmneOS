"""Persist recovery history beside the core data directory.

The file is the boot journal. Saving it does not remove user files.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from omne.recovery.model import Journal


class RecoveryJournal:
    """Load and save ``journal.json``. Invalid contents become an empty journal."""

    def __init__(self, directory: Path | None) -> None:
        self._directory = directory

    def load(self) -> Journal:
        directory = self._directory
        if directory is None:
            return Journal()
        path = directory / "journal.json"
        if not path.is_file():
            return Journal()
        try:
            return Journal.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeError, json.JSONDecodeError, ValidationError):
            return Journal()

    def save(self, journal: Journal) -> Journal:
        directory = self._directory
        if directory is None:
            return journal
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "journal.json"
        path.write_text(
            json.dumps(journal.model_dump(mode="json"), sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        return journal
