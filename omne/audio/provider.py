"""Audio provider interface.

Core calls this protocol. A provider does not replace PipeWire or open a microphone.
"""

from __future__ import annotations

from typing import Protocol

from omne.audio.model import ApplyOutcome, AudioRequest, AudioState


class AudioProvider(Protocol):
    """Inspect the stack and apply a request to the recorded session."""

    def inspect(self) -> AudioState:
        """Return the current audio record."""

    def apply(self, request: AudioRequest) -> ApplyOutcome:
        """Update the record. Do not change the host audio stack."""
