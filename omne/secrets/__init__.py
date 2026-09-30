"""Scoped credentials for OMNE.

Providers keep secrets out of source, logs, events, prompts, task records,
and plain configuration. An agent receives only a credential whose audience
names that agent.
"""

from omne.secrets.model import (
    SecretDenied,
    SecretError,
    SecretInvalid,
    SecretScope,
    SecretUnavailable,
)
from omne.secrets.select import select_provider
from omne.secrets.service import SecretService

__all__ = [
    "SecretDenied",
    "SecretError",
    "SecretInvalid",
    "SecretScope",
    "SecretService",
    "SecretUnavailable",
    "select_provider",
]
