"""Parse a configured shortcut. The chord is data, not a key log."""

from __future__ import annotations

import re
from typing import cast

from omne.input.model import ButtonName, Chord, ModifierName

_MODIFIERS: tuple[ModifierName, ...] = ("ctrl", "alt", "shift", "super")
_BUTTONS = frozenset({"left", "right", "middle"})
_KEY = re.compile(r"^(?:space|escape|enter|tab|backspace|f(?:[1-9]|1[0-9]|2[0-4])|[a-z0-9])$")


def canonical_shortcut(value: str) -> str:
    """Return the stored form of a shortcut. An empty value stays empty."""

    stripped = value.strip().lower()
    if not stripped:
        return ""
    chord = _parse(stripped)
    return chord.label


def parse_shortcut(value: str) -> Chord | None:
    """Parse one configured chord. An empty value means the binding is absent."""

    stripped = value.strip().lower()
    if not stripped:
        return None
    return _parse(stripped)


def _parse(text: str) -> Chord:
    if any(character.isspace() for character in text):
        raise ValueError("shortcut must include a modifier and a key")
    parts = text.split("+")
    if any(not part for part in parts):
        raise ValueError("shortcut must include a modifier and a key")
    modifiers: list[str] = []
    key: str | None = None
    button: ButtonName | None = None
    for part in parts:
        if part in _MODIFIERS:
            if part in modifiers:
                raise ValueError("shortcut must include a modifier and a key")
            modifiers.append(part)
            continue
        if part in _BUTTONS:
            if button is not None or key is not None:
                raise ValueError("shortcut must include a modifier and a key")
            button = cast(ButtonName, part)
            continue
        if _KEY.fullmatch(part) is None or key is not None or button is not None:
            raise ValueError("shortcut must include a modifier and a key")
        key = part
    if not modifiers or (key is None and button is None):
        raise ValueError("shortcut must include a modifier and a key")
    ordered = [name for name in _MODIFIERS if name in modifiers]
    return Chord(modifiers=ordered, key=key, button=button)
