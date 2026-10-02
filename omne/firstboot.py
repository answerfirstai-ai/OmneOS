"""First-boot setup and the desktop theme document.

Completion and the password verifier live in the data directory. The theme
file in that same directory is the only path theme changes may write. Boot
files, unit files, and package files are refused.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_STATE_FILES = frozenset({"setup.json", "theme.json"})
_HEX = re.compile(r"^#[0-9a-f]{6}$")
_TYPE = re.compile(r"^[A-Za-z0-9 ,\"'-]{1,160}$")
_NAME = re.compile(r"^[^\x00-\x1f\\/]{1,40}$")
_OS_ROOTS = (
    Path("/boot"),
    Path("/efi"),
    Path("/usr"),
    Path("/etc"),
    Path("/lib"),
    Path("/lib64"),
    Path("/bin"),
    Path("/sbin"),
    Path("/opt"),
    Path("/dev"),
    Path("/proc"),
    Path("/sys"),
    Path("/run"),
)
_UNIT_SUFFIXES = frozenset({".service", ".mount", ".socket", ".target", ".device", ".swap"})

DEPENDENCY_NOTE = "Staged with the image. Model weights are not downloaded."
_DEPENDENCIES = (
    ("shell", "OMNE shell"),
    ("core", "OMNE core"),
    ("session", "Desktop session"),
    ("catalog", "Model catalog"),
)

DUSK_WALLPAPER = (
    "radial-gradient(ellipse 70% 45% at 78% 108%, rgba(214, 146, 72, 0.55), transparent 58%), "
    "linear-gradient(180deg, #24384c 0%, #152433 46%, #1a1612 100%)"
)
NIGHT_WALLPAPER = "linear-gradient(180deg, #0c1218 0%, #1a2430 55%, #101418 100%)"
PAPER_WALLPAPER = "linear-gradient(180deg, #3a3228 0%, #1c1814 100%)"
INTERFACE_TYPE = '"Segoe UI", ui-sans-serif, system-ui, sans-serif'
EDITORIAL_TYPE = '"Iowan Old Style", Palatino, "Palatino Linotype", serif'
MONO_TYPE = 'ui-monospace, "Cascadia Mono", "Segoe UI Mono", monospace'

DEFAULT_THEME: dict[str, object] = {
    "colors": {
        "accent": "#e4c27a",
        "desktop": "#152433",
        "glass": "#12171d",
        "ink": "#f3efe6",
        "muted": "#c5c0b6",
    },
    "type": INTERFACE_TYPE,
    "wallpaper": DUSK_WALLPAPER,
}


class ThemePathError(Exception):
    """A theme write targeted something other than the theme data file."""

    def __init__(self) -> None:
        super().__init__("refusing a path outside the theme data file")


class SetupClosed(Exception):
    """Setup already finished. A later boot cannot open it again."""

    def __init__(self) -> None:
        super().__init__("setup is already complete")


class ThemeColors(BaseModel):
    """Colors the desktop paints. Values are #rrggbb, not file paths."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    accent: str
    desktop: str
    glass: str
    ink: str
    muted: str

    @field_validator("accent", "desktop", "glass", "ink", "muted")
    @classmethod
    def _hex(cls, value: str) -> str:
        lowered = value.lower()
        if _HEX.fullmatch(lowered) is None:
            raise ValueError("color must be a #rrggbb value")
        return lowered


class ThemeDocument(BaseModel):
    """Look data. Wallpaper is a gradient, never a filesystem path."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    colors: ThemeColors
    type: str
    wallpaper: str

    @field_validator("type")
    @classmethod
    def _type(cls, value: str) -> str:
        if _TYPE.fullmatch(value) is None or "/" in value or "url" in value.lower():
            raise ValueError("type is not a font stack")
        return value

    @field_validator("wallpaper")
    @classmethod
    def _wallpaper(cls, value: str) -> str:
        if "/" in value or "\\" in value or "url" in value.lower():
            raise ValueError("wallpaper must be a gradient")
        if not _gradient(value):
            raise ValueError("wallpaper must be a gradient")
        return value


class PasswordVerifier(BaseModel):
    """A scrypt verifier. The password itself is not a field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    algorithm: Literal["scrypt"]
    n: int
    r: int
    p: int
    salt: str
    hash: str


class SetupRecord(BaseModel):
    """The done flag and the verifier. Plaintext passwords are not stored."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    complete: bool
    name: str
    verifier: PasswordVerifier

    @field_validator("complete")
    @classmethod
    def _done(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("setup record must be complete")
        return value

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        cleaned = value.strip()
        if _NAME.fullmatch(cleaned) is None:
            raise ValueError("name is not a display name")
        return cleaned


class SetupRequest(BaseModel):
    """What the shell posts once. The password is hashed and dropped."""

    model_config = ConfigDict(extra="forbid")

    name: str
    password: str
    confirm: str
    theme: ThemeDocument

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        cleaned = value.strip()
        if _NAME.fullmatch(cleaned) is None:
            raise ValueError("name is not a display name")
        return cleaned

    @field_validator("password")
    @classmethod
    def _password(cls, value: str) -> str:
        if len(value) < 8 or len(value) > 128:
            raise ValueError("password must be 8 to 128 characters")
        return value


def dependency_stages(ready_through: int) -> list[dict[str, object]]:
    """Stages already present on the image. This does not fetch model weights."""

    stages: list[dict[str, object]] = []
    for index, (identifier, label) in enumerate(_DEPENDENCIES):
        stages.append(
            {
                "id": identifier,
                "label": label,
                "state": "staged" if index <= ready_through else "waiting",
                "weights": False,
            }
        )
    return stages


def boot_gate(data_dir: Path) -> Literal["setup", "password"]:
    """Password after the flag is set. Otherwise the first-boot setup."""

    record = load_setup(data_dir)
    if record is not None and record.complete:
        return "password"
    return "setup"


def public_setup(data_dir: Path) -> dict[str, object]:
    """The shell's boot document. The verifier is not included."""

    record = load_setup(data_dir)
    complete = record is not None and record.complete
    return {
        "complete": complete,
        "gate": "password" if complete else "setup",
        "name": record.name if complete and record is not None else "",
        "steps": ["welcome", "name", "look", "password"],
        "dependencies": dependency_stages(3 if complete else 0),
        "dependency_note": DEPENDENCY_NOTE,
        "theme": load_theme(data_dir).model_dump(),
    }


def finish_setup(data_dir: Path, payload: Mapping[str, object]) -> dict[str, object]:
    """Record setup once. A second call does not rewrite the verifier."""

    setup_path = _state_file(data_dir, "setup.json")
    _state_file(data_dir, "theme.json")
    if _complete(setup_path):
        raise SetupClosed()
    request = SetupRequest.model_validate(payload)
    if request.password != request.confirm:
        raise ValueError("password does not match")
    record = SetupRecord(
        complete=True,
        name=request.name,
        verifier=PasswordVerifier.model_validate(_verifier(request.password)),
    )
    _write_text(setup_path, _dump(record.model_dump()))
    apply_theme(data_dir, request.theme.model_dump())
    return public_setup(data_dir)


def unlock(data_dir: Path, password: str) -> bool:
    """True only when the verifier matches. A miss does not change state."""

    record = load_setup(data_dir)
    if record is None or not record.complete:
        return False
    return _password_matches(record.verifier, password)


def load_setup(data_dir: Path) -> SetupRecord | None:
    """Return a finished setup, or nothing when the record is missing or broken."""

    path = _state_file(data_dir, "setup.json")
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return SetupRecord.model_validate(payload)
    except (OSError, json.JSONDecodeError, UnicodeError, ValidationError):
        return None


def load_theme(data_dir: Path) -> ThemeDocument:
    """Read the theme file. A missing or broken file uses the built-in document."""

    path = _state_file(data_dir, "theme.json")
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return ThemeDocument.model_validate(payload)
        except (OSError, json.JSONDecodeError, UnicodeError, ValidationError):
            return ThemeDocument.model_validate(DEFAULT_THEME)
    return ThemeDocument.model_validate(DEFAULT_THEME)


def apply_theme(
    data_dir: Path,
    document: Mapping[str, object],
    *,
    destination: Path | None = None,
) -> Path:
    """Write the theme document. Any other destination is refused before a write."""

    allowed = _state_file(data_dir, "theme.json")
    if destination is not None and Path(destination).resolve() != allowed:
        raise ThemePathError()
    theme = ThemeDocument.model_validate(document)
    _write_text(allowed, _dump(theme.model_dump()))
    return allowed


def _complete(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        record = SetupRecord.model_validate(payload)
    except (OSError, json.JSONDecodeError, UnicodeError, ValidationError):
        return False
    return record.complete


def _verifier(password: str) -> dict[str, object]:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=32,
    )
    return {
        "algorithm": "scrypt",
        "n": _SCRYPT_N,
        "r": _SCRYPT_R,
        "p": _SCRYPT_P,
        "salt": salt.hex(),
        "hash": digest.hex(),
    }


def _password_matches(verifier: PasswordVerifier, password: str) -> bool:
    if (
        verifier.algorithm != "scrypt"
        or verifier.n != _SCRYPT_N
        or verifier.r != _SCRYPT_R
        or verifier.p != _SCRYPT_P
    ):
        return False
    try:
        salt = bytes.fromhex(verifier.salt)
        expected = bytes.fromhex(verifier.hash)
    except ValueError:
        return False
    if not salt or not expected:
        return False
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=len(expected),
    )
    return secrets.compare_digest(digest, expected)


def _state_file(data_dir: Path, name: str) -> Path:
    if name not in _STATE_FILES:
        raise ThemePathError()
    root = data_dir.resolve()
    _refuse_os_path(root)
    path = (root / name).resolve()
    if path.parent != root or path.name != name:
        raise ThemePathError()
    _refuse_os_path(path)
    return path


def _refuse_os_path(path: Path) -> None:
    resolved = path.resolve()
    for root in _OS_ROOTS:
        if resolved == root or root in resolved.parents:
            raise ThemePathError()
    if "systemd" in resolved.parts and resolved.suffix in _UNIT_SUFFIXES:
        raise ThemePathError()
    if resolved.name in {"styles.css", "index.html"} and "shell" in resolved.parts:
        raise ThemePathError()


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    if temporary.resolve().parent != path.resolve().parent:
        raise ThemePathError()
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _dump(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _gradient(value: str) -> bool:
    parts = [part.strip() for part in _split_gradients(value)]
    if not parts:
        return False
    for part in parts:
        if not (part.startswith("linear-gradient(") or part.startswith("radial-gradient(")):
            return False
        if not part.endswith(")") or part.count("(") != part.count(")"):
            return False
        if len(part) > 320:
            return False
    return len(value) <= 1200


def _split_gradients(value: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    start = 0
    for index, character in enumerate(value):
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        elif character == "," and depth == 0:
            parts.append(value[start:index])
            start = index + 1
    parts.append(value[start:])
    return parts
