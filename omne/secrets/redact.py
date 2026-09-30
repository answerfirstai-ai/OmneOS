"""Replace known secret values before text is recorded.

The registry holds values only so later logs, events, errors, traces, and
prompts can be scrubbed. It does not write them anywhere.
"""

from __future__ import annotations

import threading
from typing import Any

from omne.secrets.model import REDACTED

_HIDDEN_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "cookie",
        "credential",
        "credentials",
        "passwd",
        "passphrase",
        "password",
        "secret",
        "token",
        "xai_api_key",
        "nvidia_api_key",
    }
)
_MIN_REGISTERED = 8

_lock = threading.Lock()
_redactor: SecretRedactor | None = None


class SecretRedactor:
    """Remember secret values for the life of this process."""

    def __init__(self) -> None:
        self._values: set[str] = set()
        self._lock = threading.Lock()

    def register(self, value: str) -> None:
        """Remember a value that later text must not repeat."""

        if len(value) < _MIN_REGISTERED or value == REDACTED:
            return
        with self._lock:
            self._values.add(value)

    def redact(self, text: str) -> str:
        """Replace every remembered value in ``text``."""

        with self._lock:
            values = sorted(self._values, key=len, reverse=True)
        for value in values:
            if value in text:
                text = text.replace(value, REDACTED)
        return text

    def redact_object(self, value: Any) -> Any:
        """Return a copy with secret text and credential fields removed."""

        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, dict):
            cleaned: dict[Any, Any] = {}
            for key, item in value.items():
                if isinstance(key, str) and key.lower() in _HIDDEN_KEYS:
                    cleaned[key] = REDACTED
                else:
                    cleaned[key] = self.redact_object(item)
            return cleaned
        if isinstance(value, list):
            return [self.redact_object(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.redact_object(item) for item in value)
        return value


def install_redactor(redactor: SecretRedactor) -> None:
    """Use ``redactor`` for process-wide log, event, and record scrubbing."""

    global _redactor
    with _lock:
        _redactor = redactor


def active_redactor() -> SecretRedactor | None:
    """Return the installed redactor, if the runtime created one."""

    with _lock:
        return _redactor


def redact_text(value: str) -> str:
    """Scrub ``value`` when a redactor is installed."""

    current = active_redactor()
    if current is None:
        return value
    return current.redact(value)


def redact_object(value: Any) -> Any:
    """Scrub nested text when a redactor is installed."""

    current = active_redactor()
    if current is None:
        return value
    return current.redact_object(value)
