"""The reboot channel accepts one word and ignores an empty read."""

from __future__ import annotations

from omne.rebootchannel import command_from


def test_reboot_is_a_complete_line() -> None:
    pending, command = command_from(b"", b"reboot\n")

    assert command == "reboot"
    assert pending == b""


def test_a_split_line_waits_for_the_newline() -> None:
    pending, command = command_from(b"re", b"boot")

    assert command is None
    assert pending == b"reboot"
    pending, command = command_from(pending, b"\n")

    assert command == "reboot"


def test_an_empty_read_is_not_a_reboot() -> None:
    pending, command = command_from(b"", b"")

    assert command is None
    assert pending == b""


def test_other_words_are_not_a_reboot() -> None:
    _pending, command = command_from(b"", b"reboot now\n")

    assert command is None
