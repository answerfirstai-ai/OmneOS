"""Audio records for the Linux stack. OMNE does not replace PipeWire.

Providers read devices, defaults, volume, mute, and streams. Mixer changes stay
behind the permission system and are not applied to the host in this revision.
Microphone audio is not captured or transmitted.
"""

from omne.audio.model import AudioDevice, AudioRequest, AudioState, AudioStream
from omne.audio.select import audio_service, select_provider
from omne.audio.service import AudioService

__all__ = [
    "AudioDevice",
    "AudioRequest",
    "AudioService",
    "AudioState",
    "AudioStream",
    "audio_service",
    "select_provider",
]
