"""Choose a secret provider.

Tests use memory. Development and production use the Linux keyring when it
accepts a key. The memory provider is used for development only when the
fallback was explicitly enabled and the keyring is unavailable.
"""

from __future__ import annotations

from omne.secrets.provider import SecretProvider
from omne.secrets.providers.closed import ClosedSecretProvider
from omne.secrets.providers.linux import LinuxSecretProvider
from omne.secrets.providers.memory import MemorySecretProvider


def select_provider(environment: str, *, dev_fallback: bool = False) -> SecretProvider:
    """Return the store for this environment. An unknown environment is closed."""

    if environment == "testing":
        return MemorySecretProvider()
    linux = LinuxSecretProvider()
    if linux.available:
        return linux
    if environment == "development" and dev_fallback:
        return MemorySecretProvider()
    return ClosedSecretProvider()
