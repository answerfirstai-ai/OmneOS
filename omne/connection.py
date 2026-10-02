"""Connect intelligence without blocking the desktop.

An API key goes to the secret store. A local model is an id, not a weight
file. Neither value is written into the theme document.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from omne.secrets.model import SecretError
from omne.secrets.service import SecretService

ProviderName = Literal["xai", "nvidia"]
_OS_ROOTS = (
    Path("/boot"),
    Path("/efi"),
    Path("/usr"),
    Path("/etc"),
    Path("/lib"),
    Path("/bin"),
    Path("/sbin"),
    Path("/opt"),
)
_OFF = "Intelligence is off until an API key or a local model is connected."


class ConnectionPathError(Exception):
    """Intelligence state would leave the data directory."""

    def __init__(self) -> None:
        super().__init__("refusing a path outside OMNE state")


class IntelligenceRecord(BaseModel):
    """What is connected. The API key is not a field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: ProviderName | None = None
    local_model: str | None = None


def intelligence_view(
    data_dir: Path,
    *,
    secrets: SecretService | None,
    environment: str,
) -> dict[str, object]:
    """Desktop status. ``desktop`` stays true when intelligence is off."""

    record = _load(data_dir)
    key = _key_present(secrets, environment, record.provider)
    enabled = key or bool(record.local_model)
    return {
        "enabled": enabled,
        "desktop": True,
        "provider": record.provider if key else None,
        "local_model": record.local_model,
        "reason": "ready" if enabled else _OFF,
    }


def connect_api_key(
    data_dir: Path,
    secrets: SecretService,
    *,
    environment: str,
    provider: str,
    key: str,
) -> dict[str, object]:
    """Store the key in the secret service, then remember only the provider name."""

    if provider not in {"xai", "nvidia"}:
        raise ValueError("provider is not supported")
    chosen: ProviderName = "xai" if provider == "xai" else "nvidia"
    if not key.strip() or "\n" in key:
        raise ValueError("key is empty")
    secrets.store(
        scope="model",
        name=chosen,
        value=key,
        agents=["core"],
        agent_id="core",
        grants={"secrets": ["manage"]},
        environment=environment,
        approved=True,
    )
    current = _load(data_dir)
    _write(data_dir, IntelligenceRecord(provider=chosen, local_model=current.local_model))
    return intelligence_view(data_dir, secrets=secrets, environment=environment)


def select_local_model(
    data_dir: Path,
    model_id: str,
    *,
    secrets: SecretService | None,
    environment: str,
) -> dict[str, object]:
    """Remember a local model id. This does not download weights."""

    if not _model_id(model_id):
        raise ValueError("model id is not a catalog id")
    current = _load(data_dir)
    _write(
        data_dir,
        IntelligenceRecord(provider=current.provider, local_model=model_id),
    )
    return intelligence_view(data_dir, secrets=secrets, environment=environment)


def _key_present(secrets: SecretService | None, environment: str, provider: str | None) -> bool:
    if secrets is None or provider is None:
        return False
    try:
        return secrets.exists(
            scope="model",
            name=provider,
            agent_id="core",
            grants={"secrets": ["use"]},
            environment=environment,
        )
    except SecretError:
        return False


def _load(data_dir: Path) -> IntelligenceRecord:
    path = _state_file(data_dir)
    if not path.is_file():
        return IntelligenceRecord()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return IntelligenceRecord.model_validate(payload)
    except (OSError, json.JSONDecodeError, UnicodeError, ValidationError):
        return IntelligenceRecord()


def _write(data_dir: Path, record: IntelligenceRecord) -> None:
    path = _state_file(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(".intelligence.json.tmp")
    text = json.dumps(record.model_dump(), indent=2, sort_keys=True) + "\n"
    if "key" in record.model_dump():
        raise ConnectionPathError()
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _state_file(data_dir: Path) -> Path:
    root = data_dir.resolve()
    _refuse(root)
    path = (root / "intelligence.json").resolve()
    if path.parent != root or path.name != "intelligence.json":
        raise ConnectionPathError()
    _refuse(path)
    return path


def _model_id(value: str) -> bool:
    if len(value) < 2 or len(value) > 64:
        return False
    if not value[0].isalpha():
        return False
    return all(
        character.islower() or character.isdigit() or character == "-" for character in value
    )


def _refuse(path: Path) -> None:
    resolved = path.resolve()
    for root in _OS_ROOTS:
        if resolved == root or root in resolved.parents:
            raise ConnectionPathError()
