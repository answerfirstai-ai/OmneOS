"""Resolve the xAI credential without writing it into configuration.

Development and testing still accept ``XAI_API_KEY``. Production uses only a
``model/xai`` secret addressed to ``core``.
"""

from __future__ import annotations

import os

from core.config.settings import Settings
from omne.secrets.model import SecretError
from omne.secrets.service import SecretService


def xai_api_key(settings: Settings, secrets: SecretService) -> str | None:
    """Return the xAI credential, or None when this process should not call xAI."""

    stored = _stored_key(settings, secrets)
    if stored is not None:
        return stored
    if settings.environment not in {"development", "testing"}:
        return None
    raw = os.environ.get("XAI_API_KEY", "").strip()
    if not raw:
        return None
    secrets.redactor.register(raw)
    return raw


def _stored_key(settings: Settings, secrets: SecretService) -> str | None:
    try:
        return secrets.retrieve(
            scope="model",
            name="xai",
            agent_id="core",
            grants={"secrets": ["use"]},
            environment=settings.environment,
        )
    except SecretError:
        return None
