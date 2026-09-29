"""Identify the workspace project from files that are actually present."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class ProjectContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str
    root: str
    name: str
    type: str
    languages: list[str] = Field(default_factory=list)
    repository: bool
    git_branch: str | None = None
    documentation: list[str] = Field(default_factory=list)


def inspect_project(root: Path) -> ProjectContext:
    """Read project identity from the workspace. Missing git data stays null."""

    languages: list[str] = []
    if (root / "pyproject.toml").is_file():
        languages.append("python")
    if (root / "package.json").is_file():
        languages.append("javascript")
    docs = [path.name for path in sorted(root.glob("*.md"))]
    branch = _git_branch(root)
    kind = "code" if languages else "files"
    return ProjectContext(
        project_id=root.name or "workspace",
        root=str(root),
        name=root.name or "workspace",
        type=kind,
        languages=languages,
        repository=branch is not None or (root / ".git").exists(),
        git_branch=branch,
        documentation=docs,
    )


def _git_branch(root: Path) -> str | None:
    head = root / ".git" / "HEAD"
    if not head.is_file():
        return None
    try:
        text = head.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    marker = "ref: refs/heads/"
    if text.startswith(marker):
        return text[len(marker) :]
    return None
