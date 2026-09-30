"""Choose an input provider without opening an event node."""

from __future__ import annotations

import sys
from pathlib import Path

from omne.input.provider import InputProvider
from omne.input.providers.linux import LinuxInputProvider
from omne.input.providers.mock import MockInputProvider
from omne.input.service import Authorize, EventSink, InputService


def select_provider(environment: str, *, root: Path | None = None) -> InputProvider:
    """Use the mock provider in tests and on non-Linux hosts.

    Development and production on Linux read published devices. That read does
    not grab the keyboard or the pointer.
    """

    if environment == "testing" or not sys.platform.startswith("linux"):
        return MockInputProvider()
    return LinuxInputProvider(root=root)


def input_service(
    environment: str,
    *,
    activation: str = "",
    cancel: str = "",
    push_to_talk: str = "",
    sink: EventSink | None = None,
    authorize: Authorize | None = None,
    root: Path | None = None,
) -> InputService:
    """Return a service bound to the selected provider and the configured chords."""

    return InputService(
        select_provider(environment, root=root),
        activation=activation,
        cancel=cancel,
        push_to_talk=push_to_talk,
        sink=sink,
        authorize=authorize,
    )
