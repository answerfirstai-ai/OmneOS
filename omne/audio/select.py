"""Choose an audio provider without opening a microphone."""

from __future__ import annotations

import sys
from pathlib import Path

from omne.audio.provider import AudioProvider
from omne.audio.providers.linux import LinuxAudioProvider
from omne.audio.providers.mock import MockAudioProvider
from omne.audio.service import AudioService, Authorize, EventSink


def select_provider(environment: str, *, root: Path | None = None) -> AudioProvider:
    """Use the mock provider in tests and on non-Linux hosts.

    Development and production on Linux read the published audio record. That
    read does not start a session or open a capture device.
    """

    if environment == "testing" or not sys.platform.startswith("linux"):
        return MockAudioProvider()
    return LinuxAudioProvider(root=root)


def audio_service(
    environment: str,
    *,
    sink: EventSink | None = None,
    authorize: Authorize | None = None,
    root: Path | None = None,
) -> AudioService:
    """Return a service bound to the selected provider."""

    return AudioService(select_provider(environment, root=root), sink=sink, authorize=authorize)
