"""Scoped memory access."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.memory.database import MemoryDatabase
from core.memory.retrieval import AccessGrant, MemoryAccessError
from core.memory.store import MemoryStore


def test_scopes_do_not_leak(tmp_path: Path) -> None:
    store = MemoryStore(MemoryDatabase(tmp_path / "memory.sqlite"))
    task_grant = AccessGrant({"task"})
    project_grant = AccessGrant({"project"})
    store.add(task_grant, scope="task", scope_key="alpha", content="wire the scheduler")

    found = store.retrieve(task_grant, scope="task", scope_key="alpha", query="scheduler")

    assert [record.content for record in found] == ["wire the scheduler"]
    with pytest.raises(MemoryAccessError):
        store.retrieve(project_grant, scope="task", scope_key="alpha")


def test_like_query_treats_wildcards_as_literals(tmp_path: Path) -> None:
    store = MemoryStore(MemoryDatabase(tmp_path / "memory.sqlite"))
    grant = AccessGrant({"system"})
    store.add(grant, scope="system", scope_key="boot", content="100%")
    store.add(grant, scope="system", scope_key="boot", content="plain")

    percent = store.retrieve(grant, scope="system", scope_key="boot", query="%")
    assert [record.content for record in percent] == ["100%"]
    assert store.retrieve(grant, scope="system", scope_key="boot", query="_") == []
    assert store.retrieve(grant, scope="system", scope_key="boot", query="1%0") == []
