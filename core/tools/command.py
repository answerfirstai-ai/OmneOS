"""Subprocess helper that never invokes a shell."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class CommandOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    exit_code: int
    stdout: str
    stderr: str


class SubprocessCommands:
    """Run argv lists with ``shell=False``."""

    def run(
        self,
        argv: list[str],
        *,
        cwd: Path,
        timeout: float,
        env: dict[str, str] | None = None,
    ) -> CommandOutput:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            timeout=timeout,
            capture_output=True,
            text=True,
            shell=False,
            env=env or _safe_env(),
            check=False,
        )
        return CommandOutput(
            exit_code=completed.returncode,
            stdout=_truncate(completed.stdout),
            stderr=_truncate(completed.stderr),
        )

    def start(self, argv: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> int:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env or _safe_env(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            shell=False,
        )
        return int(process.pid)


def _safe_env() -> dict[str, str]:
    kept = {}
    for key in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT"):
        value = os.environ.get(key)
        if value:
            kept[key] = value
    return kept


def _truncate(value: str, limit: int = 100_000) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "\n[truncated]"
