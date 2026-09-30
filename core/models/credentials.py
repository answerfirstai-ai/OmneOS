"""Resolve provider credentials without writing them into configuration.

Development and testing still accept ``XAI_API_KEY``. Production uses only a
``model/xai`` secret addressed to ``core``. ``NVIDIA_API_KEY`` is read in every
environment because NVIDIA is optional and is not a boot dependency. A missing
value leaves the provider unavailable.
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


def nvidia_api_key(settings: Settings, secrets: SecretService) -> str | None:
    """Return the NVIDIA credential, or None when this process should not call NVIDIA."""

    stored = _stored_named(settings, secrets, "nvidia")
    if stored is not None:
        return stored
    raw = os.environ.get("NVIDIA_API_KEY", "").strip()
    if not raw:
        return None
    secrets.redactor.register(raw)
    return raw


def preferred_nvidia_model(settings: Settings) -> str:
    """The catalog id to request. ``NVIDIA_MODEL`` overrides the setting."""

    override = os.environ.get("NVIDIA_MODEL", "").strip()
    if override:
        return override
    return settings.nvidia_model


def _stored_key(settings: Settings, secrets: SecretService) -> str | None:
    return _stored_named(settings, secrets, "xai")


def _stored_named(settings: Settings, secrets: SecretService, name: str) -> str | None:
    try:
        return secrets.retrieve(
            scope="model",
            name=name,
            agent_id="core",
            grants={"secrets": ["use"]},
            environment=settings.environment,
        )
    except SecretError:
        return None
