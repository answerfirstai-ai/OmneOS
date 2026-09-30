"""Read one signed channel catalog from a directory.

The catalog is JSON. ``updates.json.sig`` is the signature. Package paths stay
inside the channel directory.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from pydantic import ValidationError

from omne.updates.model import CHANNELS, OMNE_PACKAGES, ChannelCatalog, ChannelName, PackageRecord
from omne.updates.verify import VerificationError, hashes_match, sha256_file, verify_signature


def load_catalog(root: Path, channel: ChannelName, *, public_key: Path) -> ChannelCatalog:
    """Verify the catalog signature, then parse it. Unsigned input is rejected."""

    document = root / channel / "updates.json"
    signature = root / channel / "updates.json.sig"
    if channel == "omne" and not signature.is_file():
        raise VerificationError("unsigned omne package")
    verify_signature(public_key, document, signature)
    try:
        payload = json.loads(document.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VerificationError("update catalog is invalid") from exc
    if not isinstance(payload, dict):
        raise VerificationError("update catalog is invalid")
    try:
        catalog = ChannelCatalog.model_validate(payload)
    except ValidationError as exc:
        raise VerificationError("update catalog is invalid") from exc
    if catalog.channel != channel:
        raise VerificationError("update catalog channel does not match")
    _require_packages(catalog)
    return catalog


def package_path(root: Path, channel: ChannelName, package: PackageRecord) -> Path:
    """Resolve a package filename inside the channel directory."""

    relative = package.filename
    if relative.startswith("/") or "\\" in relative or "\x00" in relative:
        raise VerificationError("package path is invalid")
    if any(part in {"", ".", ".."} for part in Path(relative).parts):
        raise VerificationError("package path is invalid")
    directory = (root / channel).resolve()
    candidate = (directory / relative).resolve()
    if candidate != directory and directory not in candidate.parents:
        raise VerificationError("package path is invalid")
    if not candidate.is_file():
        raise VerificationError("update package is missing")
    return candidate


def verify_package(path: Path, package: PackageRecord) -> None:
    """Reject a package whose size or digest does not match the catalog."""

    digest, size = sha256_file(path)
    if size != package.size or not hashes_match(package.sha256, digest):
        raise VerificationError("update package is corrupt")
    if path.suffix == ".deb":
        _require_deb(path)


def _require_packages(catalog: ChannelCatalog) -> None:
    if not catalog.packages:
        raise VerificationError("update catalog has no packages")
    names = [item.name for item in catalog.packages]
    if len(names) != len(set(names)):
        raise VerificationError("update catalog repeats a package")
    if catalog.channel == "omne" and any(name not in OMNE_PACKAGES for name in names):
        raise VerificationError("omne package is not a system package")
    if catalog.channel != "model":
        for package in catalog.packages:
            if not package.filename.endswith(".deb"):
                raise VerificationError("update package is not a debian package")


def _require_deb(path: Path) -> None:
    try:
        completed = subprocess.run(
            ["dpkg-deb", "--info", str(path)],
            check=False,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VerificationError("update package is corrupt") from exc
    if completed.returncode != 0:
        raise VerificationError("update package is corrupt")


def known_channels() -> tuple[ChannelName, ...]:
    return CHANNELS
