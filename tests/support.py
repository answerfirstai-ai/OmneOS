"""Helpers for runtime tests."""

from __future__ import annotations

from pathlib import Path

from tests.conftest import ROOT

from core.config.settings import Settings, load_settings


def runtime_settings(tmp_path: Path, **overrides: str) -> Settings:
    """Load settings pointed at a temporary workspace and the repo manifests."""

    environ = {
        "OMNE_ENVIRONMENT": "testing",
        "OMNE_LOG_LEVEL": "ERROR",
        "OMNE_WORKSPACE_ROOT": str(tmp_path / "workspace"),
        "OMNE_DATA_DIR": str(tmp_path / "memory"),
        "OMNE_AGENTS_DIR": str(ROOT / "agents"),
        "OMNE_MODELS_DIR": str(ROOT / "models" / "manifests"),
        "OMNE_TASK_RETRY_LIMIT": "1",
    }
    environ.update(overrides)
    return load_settings(environ=environ, cwd=tmp_path)
