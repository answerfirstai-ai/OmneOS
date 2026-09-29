"""Voice stays silent without an allow decision and a provider."""

from __future__ import annotations

from core.permissions.evaluator import PermissionEvaluator
from core.voice.service import VoiceService


def test_listen_does_not_capture_audio() -> None:
    voice = VoiceService(PermissionEvaluator(), environment="testing")

    status = voice.status()
    heard = voice.listen()

    assert status["provider"] == "unavailable"
    assert status["hardware"] == "unavailable"
    assert status["permission"] == "DENY"
    assert status["listening"] is False
    assert heard["audio"] is False
    assert heard["listening"] is False
