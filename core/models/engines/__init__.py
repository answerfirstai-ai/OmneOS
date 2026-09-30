"""Local model engines.

Core depends on the engine protocol. A deployment chooses an adapter. The
mock adapter is for tests. The OpenAI-compatible adapter talks to a server
that is already running.
"""

from core.models.engines.base import EngineStatus, ModelEngine
from core.models.engines.mock import MockEngine
from core.models.engines.openai_compatible import OpenAICompatibleEngine

__all__ = [
    "EngineStatus",
    "MockEngine",
    "ModelEngine",
    "OpenAICompatibleEngine",
]
