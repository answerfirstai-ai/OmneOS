"""An Obsidian vault: a folder of markdown notes on disk.

Core appends a task note and can read it back. The folder is OMNE state, not
an OS package.
"""

from __future__ import annotations

import re
from pathlib import Path

_OS_ROOTS = (
    Path("/boot"),
    Path("/efi"),
    Path("/usr"),
    Path("/etc"),
    Path("/lib"),
    Path("/bin"),
    Path("/sbin"),
    Path("/opt"),
)
_WORDS = re.compile(r"[A-Za-z0-9]+")


class VaultPathError(Exception):
    """A note would be written outside the vault."""

    def __init__(self) -> None:
        super().__init__("refusing a path outside the vault")


class ObsidianVault:
    """One vault directory. Notes are markdown files."""

    def __init__(self, root: Path) -> None:
        resolved = root.resolve()
        _refuse(resolved)
        self.root = resolved

    def record_task(self, title: str, body: str) -> Path:
        """Append ``body`` to the note for ``title``."""

        path = self._note(title)
        path.parent.mkdir(parents=True, exist_ok=True)
        heading = " ".join(title.split())
        block = f"\n{body.strip()}\n"
        if path.is_file():
            path.write_text(path.read_text(encoding="utf-8") + block, encoding="utf-8")
        else:
            path.write_text(f"# {heading}\n{block}", encoding="utf-8")
        return path

    def read_note(self, title: str) -> str:
        """Return the note text. A missing note is an error."""

        path = self._note(title)
        if not path.is_file():
            raise FileNotFoundError(title)
        return path.read_text(encoding="utf-8")

    def _note(self, title: str) -> Path:
        slug = "-".join(_WORDS.findall(title.lower())) or "note"
        path = (self.root / f"{slug}.md").resolve()
        if path.parent != self.root:
            raise VaultPathError()
        _refuse(path)
        return path


def remember_task(vault: ObsidianVault, objective: str, outcome: str) -> Path:
    """The task side effect: write the outcome into the vault."""

    return vault.record_task(objective, outcome)


def _refuse(path: Path) -> None:
    resolved = path.resolve()
    for root in _OS_ROOTS:
        if resolved == root or root in resolved.parents:
            raise VaultPathError()
