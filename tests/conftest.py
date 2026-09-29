"""Shared test fixtures."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _reset_OMNE_logging() -> Iterator[None]:
    """Drop handlers so one test cannot leave a closed stream attached."""

    yield
    logger = logging.getLogger("OMNE")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.handlers.clear()


@pytest.fixture(autouse=True)
def _clear_OMNE_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep tests independent from developer environment variables."""

    for key in list(os.environ):
        if key.startswith("OMNE_"):
            monkeypatch.delenv(key)
    yield


@pytest.fixture
def repo_root() -> Path:
    return ROOT
