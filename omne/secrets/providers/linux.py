"""Kernel keyring storage for OMNE credentials.

Values live in a keyring named ``omne.secrets`` on the session keyring. They
are not written to a configuration file. A missing keyutils library or a
keyring that cannot be read back marks the provider unavailable.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import json
from ctypes import c_char_p, c_int32, c_size_t, c_void_p

from omne.secrets.model import SecretScope, SecretUnavailable

_KEY_SPEC_SESSION_KEYRING = -3
_KEY_SPEC_PROCESS_KEYRING = -2
_ENOKEY = 126
_RING_NAME = b"omne.secrets"
_PROBE_NAME = b"omne.v1.ready"
_PROBE_VALUE = b"ready"


class LinuxSecretProvider:
    """Store credentials with the Linux key retention service."""

    def __init__(self, *, keyring: int | None = None) -> None:
        self._keyring = keyring
        self._available = False
        if keyring is not None:
            self._available = True
            return
        try:
            self._keyring = _ensure_ring()
        except OSError:
            self._keyring = None
            return
        self._available = True

    @property
    def available(self) -> bool:
        return self._available

    def put(
        self,
        scope: SecretScope,
        name: str,
        value: str,
        agents: tuple[str, ...],
    ) -> None:
        ring = self._require()
        _add(_secret_name(scope, name), value.encode("utf-8"), ring)
        meta = json.dumps({"agents": list(agents)}, sort_keys=True).encode("utf-8")
        try:
            _add(_meta_name(scope, name), meta, ring)
        except OSError as exc:
            _drop(ring, _secret_name(scope, name))
            raise SecretUnavailable() from exc

    def get(self, scope: SecretScope, name: str) -> tuple[str, tuple[str, ...]] | None:
        ring = self._require()
        raw = _read(ring, _secret_name(scope, name))
        meta_raw = _read(ring, _meta_name(scope, name))
        if raw is None or meta_raw is None:
            return None
        try:
            payload = json.loads(meta_raw.decode("utf-8"))
            agents = payload.get("agents")
            if not isinstance(agents, list) or not all(isinstance(item, str) for item in agents):
                raise SecretUnavailable()
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise SecretUnavailable() from exc
        try:
            value = raw.decode("utf-8")
        except UnicodeError as exc:
            raise SecretUnavailable() from exc
        return value, tuple(agents)

    def remove(self, scope: SecretScope, name: str) -> bool:
        ring = self._require()
        removed_secret = _drop(ring, _secret_name(scope, name))
        removed_meta = _drop(ring, _meta_name(scope, name))
        return removed_secret or removed_meta

    def contains(self, scope: SecretScope, name: str) -> bool:
        ring = self._require()
        return _find(ring, _secret_name(scope, name)) is not None and (
            _find(ring, _meta_name(scope, name)) is not None
        )

    def _require(self) -> int:
        if not self._available or self._keyring is None:
            raise SecretUnavailable()
        return self._keyring


def private_keyring() -> tuple[int, ctypes.CDLL]:
    """Create a process-local keyring for a test. The caller invalidates it."""

    library = _library()
    serial = _add_key(library, b"keyring", b"omne.secrets.test", None, _KEY_SPEC_PROCESS_KEYRING)
    return serial, library


def invalidate_keyring(serial: int) -> None:
    """Destroy a keyring created for a test."""

    _keyctl_invalidate(_library(), serial)


def _secret_name(scope: SecretScope, name: str) -> bytes:
    return f"omne.v1.secret.{scope.value}.{name}".encode("ascii")


def _meta_name(scope: SecretScope, name: str) -> bytes:
    return f"omne.v1.meta.{scope.value}.{name}".encode("ascii")


def _ensure_ring() -> int:
    library = _library()
    found = _search(library, _KEY_SPEC_SESSION_KEYRING, b"keyring", _RING_NAME)
    created = False
    if found is None:
        found = _add_key(library, b"keyring", _RING_NAME, None, _KEY_SPEC_SESSION_KEYRING)
        created = True
    try:
        _probe(library, found)
    except OSError:
        if created:
            _keyctl_invalidate(library, found)
        raise
    return found


def _probe(library: ctypes.CDLL, keyring: int) -> None:
    _add_key(library, b"user", _PROBE_NAME, _PROBE_VALUE, keyring)
    try:
        serial = _search(library, keyring, b"user", _PROBE_NAME)
        if serial is None:
            raise OSError("keyring probe was not visible")
        read = library.keyctl_read
        read.argtypes = [c_int32, c_void_p, c_size_t]
        read.restype = ctypes.c_long
        buffer = ctypes.create_string_buffer(len(_PROBE_VALUE))
        ctypes.set_errno(0)
        written = int(read(serial, buffer, len(_PROBE_VALUE)))
        if written != len(_PROBE_VALUE) or buffer.raw[:written] != _PROBE_VALUE:
            raise OSError(ctypes.get_errno(), "keyring probe was not readable")
    finally:
        unlink = library.keyctl_unlink
        unlink.argtypes = [c_int32, c_int32]
        unlink.restype = ctypes.c_long
        serial = _search(library, keyring, b"user", _PROBE_NAME)
        if serial is not None:
            unlink(serial, keyring)


def _add(description: bytes, payload: bytes, keyring: int) -> None:
    _add_key(_library(), b"user", description, payload, keyring)


def _library() -> ctypes.CDLL:
    path = ctypes.util.find_library("keyutils")
    if not path:
        raise OSError("keyutils is not installed")
    try:
        return ctypes.CDLL(path, use_errno=True)
    except OSError as exc:
        raise OSError("keyutils is not installed") from exc


def _add_key(
    library: ctypes.CDLL,
    key_type: bytes,
    description: bytes,
    payload: bytes | None,
    keyring: int,
) -> int:
    add_key = library.add_key
    add_key.argtypes = [c_char_p, c_char_p, c_void_p, c_size_t, c_int32]
    add_key.restype = c_int32
    if payload is None:
        pointer: c_void_p | None = None
        size = 0
    else:
        buffer = ctypes.create_string_buffer(payload)
        pointer = ctypes.cast(buffer, c_void_p)
        size = len(payload)
    ctypes.set_errno(0)
    serial = int(add_key(key_type, description, pointer, size, keyring))
    if serial < 0:
        raise OSError(ctypes.get_errno(), "keyring update failed")
    return serial


def _search(library: ctypes.CDLL, keyring: int, key_type: bytes, description: bytes) -> int | None:
    search = library.keyctl_search
    search.argtypes = [c_int32, c_char_p, c_char_p, c_int32]
    search.restype = c_int32
    ctypes.set_errno(0)
    serial = int(search(keyring, key_type, description, 0))
    if serial >= 0:
        return serial
    error = ctypes.get_errno()
    if error in {0, _ENOKEY, 2}:
        return None
    raise OSError(error, "keyring search failed")


def _find(keyring: int, description: bytes) -> int | None:
    try:
        return _search(_library(), keyring, b"user", description)
    except OSError as exc:
        raise SecretUnavailable() from exc


def _read(keyring: int, description: bytes) -> bytes | None:
    library = _library()
    try:
        serial = _search(library, keyring, b"user", description)
    except OSError as exc:
        raise SecretUnavailable() from exc
    if serial is None:
        return None
    read = library.keyctl_read
    read.argtypes = [c_int32, c_void_p, c_size_t]
    read.restype = ctypes.c_long
    ctypes.set_errno(0)
    needed = int(read(serial, None, 0))
    if needed < 0:
        raise SecretUnavailable()
    buffer = ctypes.create_string_buffer(needed)
    ctypes.set_errno(0)
    written = int(read(serial, buffer, needed))
    if written < 0:
        raise SecretUnavailable()
    return buffer.raw[:written]


def _drop(keyring: int, description: bytes) -> bool:
    library = _library()
    try:
        serial = _search(library, keyring, b"user", description)
    except OSError as exc:
        raise SecretUnavailable() from exc
    if serial is None:
        return False
    unlink = library.keyctl_unlink
    unlink.argtypes = [c_int32, c_int32]
    unlink.restype = ctypes.c_long
    invalidate = library.keyctl_invalidate
    invalidate.argtypes = [c_int32]
    invalidate.restype = ctypes.c_long
    ctypes.set_errno(0)
    if int(unlink(serial, keyring)) < 0:
        raise SecretUnavailable()
    ctypes.set_errno(0)
    invalidate(serial)
    return True


def _keyctl_invalidate(library: ctypes.CDLL, serial: int) -> None:
    invalidate = library.keyctl_invalidate
    invalidate.argtypes = [c_int32]
    invalidate.restype = ctypes.c_long
    ctypes.set_errno(0)
    invalidate(serial)
