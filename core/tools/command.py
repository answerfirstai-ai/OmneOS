"""Subprocess helper that never invokes a shell."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from core.security.profiles import profile_for


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
            [sys.executable, "-m", "core.security.launch", str(cwd), *argv],
            cwd=cwd,
            timeout=timeout,
            capture_output=True,
            text=True,
            shell=False,
            env=env or _sandbox_env(),
            check=False,
        )
        if completed.returncode == 126 and completed.stderr.startswith("omne-sandbox:"):
            raise OSError(completed.stderr.strip())
        return CommandOutput(
            exit_code=completed.returncode,
            stdout=_truncate(completed.stdout),
            stderr=_truncate(completed.stderr),
        )

    def start(self, argv: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> int:
        del argv, cwd, env
        raise OSError("unsandboxed process start is denied")


def _sandbox_env() -> dict[str, str]:
    profile = profile_for("WORKER")
    if profile is None:
        raise OSError("worker profile is missing")
    ceiling = profile.ceiling
    kept = {}
    for key in ("PATH", "LANG", "LC_ALL"):
        value = os.environ.get(key)
        if value:
            kept[key] = value
    kept["OMNE_SANDBOX_AS"] = str(ceiling.ram_mb * 1024 * 1024)
    kept["OMNE_SANDBOX_CPU"] = str(ceiling.cpu_seconds)
    kept["OMNE_SANDBOX_NOFILE"] = str(ceiling.nofile)
    kept["OMNE_SANDBOX_FSIZE"] = str(ceiling.file_mb * 1024 * 1024)
    return kept


def _truncate(value: str, limit: int = 100_000) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "\n[truncated]"
