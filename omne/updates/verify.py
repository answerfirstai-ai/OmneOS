"""Verify a catalog signature and a package hash.

OpenSSL checks the signature. A missing tool, a bad key, or a mismatch is a
failure. The package bytes are not returned in the error.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path


class VerificationError(Exception):
    """A catalog or package failed verification."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.code = "rejected"


def verify_signature(public_key: Path, document: Path, signature: Path) -> None:
    """Require an Ed25519 signature over the catalog bytes."""

    if not public_key.is_file() or not document.is_file() or not signature.is_file():
        raise VerificationError("update signature is missing")
    try:
        completed = subprocess.run(
            [
                "openssl",
                "pkeyutl",
                "-verify",
                "-pubin",
                "-inkey",
                str(public_key),
                "-rawin",
                "-in",
                str(document),
                "-sigfile",
                str(signature),
            ],
            check=False,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VerificationError("update signature could not be checked") from exc
    if completed.returncode != 0:
        raise VerificationError("update signature is invalid")


def sha256_file(path: Path) -> tuple[str, int]:
    """Return the hex digest and size of one file."""

    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as handle:
            while True:
                block = handle.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
                size += len(block)
    except OSError as exc:
        raise VerificationError("update package could not be read") from exc
    return digest.hexdigest(), size


def hashes_match(expected: str, actual: str) -> bool:
    """Compare two digests without stopping at the first differing character."""

    if len(expected) != len(actual):
        return False
    mismatch = 0
    for left, right in zip(expected, actual, strict=True):
        mismatch |= ord(left) ^ ord(right)
    return mismatch == 0
