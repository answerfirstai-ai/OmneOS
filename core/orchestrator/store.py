"""SQLite persistence for tasks."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from core.orchestrator.task import Task, TaskStatus, transition_task
from core.sqlite import configure_sqlite
from omne.secrets.redact import redact_object


class TaskStore:
    """Save and load tasks so a process can resume them."""

    def __init__(self, path: Path, *, now: Callable[[], datetime] | None = None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._now = now or (lambda: datetime.now(UTC))
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        configure_sqlite(self._connection)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                parent_id TEXT,
                document TEXT NOT NULL
            )
            """
        )
        self._connection.execute("CREATE INDEX IF NOT EXISTS tasks_parent_id ON tasks (parent_id)")
        self._connection.commit()
        self._cache: dict[str, Task] = {}

    def save(self, task: Task) -> Task:
        task = Task.model_validate(redact_object(task.model_dump(mode="json")))
        document = json.dumps(task.model_dump(mode="json"), sort_keys=True)
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO tasks (id, parent_id, document)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    parent_id = excluded.parent_id,
                    document = excluded.document
                """,
                (task.id, task.parent_task, document),
            )
            self._connection.commit()
            self._cache[task.id] = task
        return task

    def get(self, task_id: str) -> Task:
        with self._lock:
            cached = self._cache.get(task_id)
            if cached is not None:
                return cached
            row = self._connection.execute(
                "SELECT id, document FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown task: {task_id}")
            return self._task_from_row(row)

    def list_tasks(self) -> list[Task]:
        with self._lock:
            rows = self._connection.execute("SELECT id, document FROM tasks ORDER BY id").fetchall()
            return [self._task_from_row(row) for row in rows]

    def children(self, parent_id: str) -> list[Task]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT id, document FROM tasks WHERE parent_id = ? ORDER BY id",
                (parent_id,),
            ).fetchall()
            return [self._task_from_row(row) for row in rows]

    def roots(self) -> list[Task]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT id, document FROM tasks WHERE parent_id IS NULL ORDER BY id"
            ).fetchall()
            return [self._task_from_row(row) for row in rows]

    def _task_from_row(self, row: sqlite3.Row) -> Task:
        task_id = str(row["id"])
        cached = self._cache.get(task_id)
        if cached is not None:
            return cached
        task = Task.model_validate_json(row["document"])
        self._cache[task_id] = task
        return task

    def transition(self, task: Task, status: TaskStatus, **updates: object) -> Task:
        updated = transition_task(task, status, now=self._now(), **updates)
        return self.save(updated)
