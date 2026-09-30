"""Configured shortcuts for OMNE. The keyboard stream is not read.

Providers report keyboards and mice. Activation, cancel, and push-to-talk are
chords from configuration. A host grab is not installed.
"""

from omne.input.model import Chord, InputDevice, InputRequest, InputState
from omne.input.select import input_service, select_provider
from omne.input.service import InputService

__all__ = [
    "Chord",
    "InputDevice",
    "InputRequest",
    "InputService",
    "InputState",
    "input_service",
    "select_provider",
]
