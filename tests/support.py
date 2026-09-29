"""Helpers for runtime tests."""

from __future__ import annotations

from pathlib import Path

from tests.conftest import ROOT

from core.config.settings import Settings, load_settings


def runtime_settings(tmp_path: Path, **overrides: str) -> Settings:
    """Load settings pointed at a temporary workspace and the repo manifests."""

    environ = {
        "JARVIS_ENVIRONMENT": "testing",
        "JARVIS_LOG_LEVEL": "ERROR",
        "JARVIS_WORKSPACE_ROOT": str(tmp_path / "workspace"),
        "JARVIS_DATA_DIR": str(tmp_path / "memory"),
        "JARVIS_AGENTS_DIR": str(ROOT / "agents"),
        "JARVIS_MODELS_DIR": str(ROOT / "models" / "manifests"),
        "JARVIS_TASK_RETRY_LIMIT": "1",
    }
    environ.update(overrides)
    return load_settings(environ=environ, cwd=tmp_path)
