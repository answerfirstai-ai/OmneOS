"""Create an agent definition from a task sentence.

The result is the same manifest workers already admit. Nothing is installed
into an OS package directory.
"""

from __future__ import annotations

import re
from pathlib import Path

from core.agents.manifest import AgentManifest, LifecycleSpec, load_manifest

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
_WORDS = re.compile(r"[a-z0-9]+")


class AgentPathError(Exception):
    """The agent file would leave OMNE state."""

    def __init__(self) -> None:
        super().__init__("refusing a path outside OMNE state")


def agent_for_task(task: str) -> AgentManifest:
    """Build one on-demand agent whose description is the task."""

    description = " ".join(task.split())
    if not description:
        raise ValueError("task is empty")
    return AgentManifest(
        id=_slug(description),
        name=description[:48],
        version="0.1.0",
        description=description[:200],
        capabilities=["conversation"],
        tools=["filesystem.read", "filesystem.write", "filesystem.search"],
        permissions={"filesystem": ["workspace"]},
        lifecycle=LifecycleSpec(persistent=False, startup="on_demand", shutdown="after_task"),
        max_workers=1,
    )


def write_agent(directory: Path, manifest: AgentManifest) -> Path:
    """Write ``agent.toml`` under ``directory``. Boot and package paths are refused."""

    root = directory.resolve()
    _refuse(root)
    path = (root / manifest.id / "agent.toml").resolve()
    if path.parent.parent != root:
        raise AgentPathError()
    _refuse(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_toml(manifest), encoding="utf-8")
    return path


def load_created(path: Path) -> AgentManifest:
    """Load a manifest this module wrote."""

    return load_manifest(
        path,
        known_tools={"filesystem.read", "filesystem.write", "filesystem.search"},
    )


def _slug(task: str) -> str:
    words = _WORDS.findall(task.lower())
    slug = "-".join(words).strip("-")[:64].strip("-")
    if len(slug) < 2:
        raise ValueError("task needs a name")
    if not slug[0].isalpha():
        slug = f"agent-{slug}"[:64]
    return slug


def _toml(manifest: AgentManifest) -> str:
    tools = ", ".join(f'"{tool}"' for tool in manifest.tools)
    capabilities = ", ".join(f'"{item}"' for item in manifest.capabilities)
    return "\n".join(
        [
            f'id = "{manifest.id}"',
            f'name = "{_escape(manifest.name)}"',
            f'version = "{manifest.version}"',
            f'description = "{_escape(manifest.description)}"',
            f"capabilities = [{capabilities}]",
            f"tools = [{tools}]",
            "max_workers = 1",
            "",
            "[permissions]",
            'filesystem = ["workspace"]',
            "",
            "[lifecycle]",
            "persistent = false",
            'startup = "on_demand"',
            'shutdown = "after_task"',
            "",
        ]
    )


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _refuse(path: Path) -> None:
    resolved = path.resolve()
    for root in _OS_ROOTS:
        if resolved == root or root in resolved.parents:
            raise AgentPathError()
