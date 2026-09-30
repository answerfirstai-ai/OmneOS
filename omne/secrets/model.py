"""Secret names, scopes, and failures.

A failure message names the kind of rejection. It does not include the secret.
"""

from __future__ import annotations

import re
from enum import StrEnum

_NAME = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")
_MIN_VALUE = 8
_MAX_VALUE = 4096
REDACTED = "[redacted]"


class SecretScope(StrEnum):
    """The kind of credential a record holds."""

    MODEL = "model"
    API = "api"
    BROWSER = "browser"
    NETWORK = "network"
    APPLICATION = "application"
    SERVICE = "service"


class SecretError(Exception):
    """A secret operation was rejected."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class SecretDenied(SecretError):
    """Permission or audience rejected the operation."""

    def __init__(self, message: str = "secret access is denied") -> None:
        super().__init__(message, code="denied")


class SecretInvalid(SecretError):
    """The reference or value cannot be stored."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="invalid")


class SecretUnavailable(SecretError):
    """The configured store could not complete the operation."""

    def __init__(self, message: str = "secret storage is unavailable") -> None:
        super().__init__(message, code="unavailable")


def parse_scope(value: str) -> SecretScope:
    """Return a known scope. An unknown scope is invalid."""

    try:
        return SecretScope(value)
    except ValueError as exc:
        raise SecretInvalid("secret scope is invalid") from exc


def parse_name(value: str) -> str:
    """Return a name that is safe to record in an audit line."""

    if not isinstance(value, str) or _NAME.fullmatch(value) is None:
        raise SecretInvalid("secret name is invalid")
    return value


def parse_agent(value: str) -> str:
    """Return an agent id that may appear in an audience."""

    if not isinstance(value, str) or _NAME.fullmatch(value) is None:
        raise SecretInvalid("secret audience is invalid")
    return value


def parse_agents(values: object) -> tuple[str, ...]:
    """Return a non-empty audience. Duplicates collapse."""

    if isinstance(values, str) or not isinstance(values, (list, tuple)):
        raise SecretInvalid("secret audience is invalid")
    agents = tuple(dict.fromkeys(parse_agent(item) for item in values))
    if not agents:
        raise SecretInvalid("secret audience is invalid")
    return agents


def parse_value(value: object) -> str:
    """Accept one credential. The value is not repeated in the error."""

    if not isinstance(value, str):
        raise SecretInvalid("secret value is invalid")
    if value != value.strip():
        raise SecretInvalid("secret value is invalid")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise SecretInvalid("secret value is invalid")
    if len(value) < _MIN_VALUE or len(value) > _MAX_VALUE:
        raise SecretInvalid("secret value is invalid")
    if REDACTED in value:
        raise SecretInvalid("secret value is invalid")
    return value
