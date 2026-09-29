"""Typed OMNE Core settings.

Application code should load settings through :func:`load_settings`. That
function merges a TOML file with ``OMNE_`` environment variables, validates
the result, and resolves relative paths against the working directory.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from core.config.errors import ConfigurationError

EnvironmentName = Literal["development", "testing", "production"]
LogLevelName = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
LogFormatName = Literal["text", "json"]

ENV_TO_FIELD: dict[str, str] = {
    "OMNE_ENVIRONMENT": "environment",
    "OMNE_LOG_LEVEL": "log_level",
    "OMNE_LOG_FORMAT": "log_format",
    "OMNE_HOST": "host",
    "OMNE_PORT": "port",
    "OMNE_WORKSPACE_ROOT": "workspace_root",
    "OMNE_DATA_DIR": "data_dir",
    "OMNE_CORS_ORIGINS": "cors_origins",
    "OMNE_MAX_PARALLEL_TASKS": "max_parallel_tasks",
    "OMNE_TASK_RETRY_LIMIT": "task_retry_limit",
    "OMNE_TOOL_TIMEOUT_SECONDS": "tool_timeout_seconds",
    "OMNE_XAI_BASE_URL": "xai_base_url",
    "OMNE_XAI_MODEL": "xai_model",
    "OMNE_XAI_TIMEOUT_SECONDS": "xai_timeout_seconds",
    "OMNE_XAI_MAX_RETRIES": "xai_max_retries",
    "OMNE_LOCAL_MODEL_BASE_URL": "local_model_base_url",
    "OMNE_BROWSER_COMMAND": "browser_command",
    "OMNE_AGENTS_DIR": "agents_dir",
    "OMNE_MODELS_DIR": "models_dir",
}

KNOWN_ENVIRONMENT_VARIABLES: frozenset[str] = frozenset(ENV_TO_FIELD) | {"OMNE_CONFIG"}


class Settings(BaseModel):
    """Validated runtime settings for OMNE Core."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    environment: EnvironmentName = "development"
    log_level: LogLevelName = "INFO"
    log_format: LogFormatName = "text"
    host: str = "127.0.0.1"
    port: int = Field(default=8787, ge=1, le=65535)
    workspace_root: Path = Path("workspace")
    data_dir: Path = Path("memory")
    cors_origins: list[str] = Field(default_factory=list)
    max_parallel_tasks: int = Field(default=2, ge=1, le=32)
    task_retry_limit: int = Field(default=2, ge=0, le=10)
    tool_timeout_seconds: int = Field(default=15, ge=1, le=120)
    xai_base_url: str = "https://api.x.ai/v1"
    xai_model: str = "grok-4"
    xai_timeout_seconds: int = Field(default=30, ge=1, le=300)
    xai_max_retries: int = Field(default=2, ge=0, le=5)
    local_model_base_url: str = ""
    browser_command: str = ""
    agents_dir: Path = Path("agents")
    models_dir: Path = Path("models/manifests")

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: object) -> object:
        if isinstance(value, str):
            return value.upper()
        return value

    @field_validator("host")
    @classmethod
    def _validate_host(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("host must not be empty")
        return stripped

    @field_validator("cors_origins")
    @classmethod
    def _validate_cors_origins(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(item == "" for item in cleaned):
            raise ValueError("CORS origins must not be empty")
        if "*" in cleaned and cleaned != ["*"]:
            raise ValueError("CORS origin * cannot be combined with other origins")
        return cleaned

    @field_validator("xai_base_url")
    @classmethod
    def _validate_xai_base_url(cls, value: str) -> str:
        stripped = value.strip().rstrip("/")
        if not stripped.startswith("https://"):
            raise ValueError("xai_base_url must start with https://")
        return stripped

    @field_validator("xai_model")
    @classmethod
    def _validate_xai_model(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("xai_model must not be empty")
        return stripped

    @field_validator("local_model_base_url", "browser_command")
    @classmethod
    def _strip_optional(cls, value: str) -> str:
        return value.strip()

    @field_validator("local_model_base_url")
    @classmethod
    def _validate_local_model_url(cls, value: str) -> str:
        if value and not (value.startswith("http://") or value.startswith("https://")):
            raise ValueError("local_model_base_url must start with http:// or https://")
        return value.rstrip("/")


def load_settings(
    *,
    environ: Mapping[str, str] | None = None,
    config_path: Path | None = None,
    cwd: Path | None = None,
) -> Settings:
    """Load, validate, and resolve settings.

    ``environ`` defaults to the process environment. Relative filesystem paths
    are resolved against ``cwd``, which defaults to the process working directory.
    """

    env = environ if environ is not None else _process_environ()
    working_directory = (cwd or Path.cwd()).resolve()
    _reject_unknown_variables(env)

    payload: dict[str, Any] = {}
    resolved_config = _resolve_config_path(env, config_path, working_directory)
    if resolved_config is not None:
        payload.update(_read_config(resolved_config))
    payload.update(_environment_overrides(env))

    try:
        settings = Settings.model_validate(payload)
    except ValidationError as exc:
        raise ConfigurationError(_format_validation_error(exc)) from exc

    return settings.model_copy(
        update={
            "workspace_root": _resolve_path(working_directory, settings.workspace_root),
            "data_dir": _resolve_path(working_directory, settings.data_dir),
            "agents_dir": _resolve_path(working_directory, settings.agents_dir),
            "models_dir": _resolve_path(working_directory, settings.models_dir),
        }
    )


def override_settings(settings: Settings, updates: Mapping[str, object]) -> Settings:
    """Return a validated copy of ``settings`` with ``updates`` applied.

    Path fields are left as provided. :func:`load_settings` is the call that
    resolves relative paths.
    """

    if not updates:
        return settings
    data = settings.model_dump()
    data.update(dict(updates))
    try:
        return Settings.model_validate(data)
    except ValidationError as exc:
        raise ConfigurationError(_format_validation_error(exc)) from exc


def prepare_runtime_directories(settings: Settings) -> None:
    """Create the workspace and data directories when they are absent."""

    for path in (settings.workspace_root, settings.data_dir):
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ConfigurationError(
                f"Unable to create runtime directory {path}: {exc.strerror}"
            ) from exc


def _process_environ() -> Mapping[str, str]:
    import os

    return os.environ


def _reject_unknown_variables(environ: Mapping[str, str]) -> None:
    unknown = sorted(
        key for key in environ if key.startswith("OMNE_") and key not in KNOWN_ENVIRONMENT_VARIABLES
    )
    if unknown:
        names = ", ".join(unknown)
        raise ConfigurationError(f"Unknown OMNE environment variable: {names}")


def _resolve_config_path(
    environ: Mapping[str, str],
    config_path: Path | None,
    cwd: Path,
) -> Path | None:
    if config_path is not None:
        path = config_path if config_path.is_absolute() else cwd / config_path
        if not path.is_file():
            raise ConfigurationError(f"Configuration file not found: {path}")
        return path

    configured = environ.get("OMNE_CONFIG", "").strip()
    if configured:
        path = Path(configured)
        if not path.is_absolute():
            path = cwd / path
        if not path.is_file():
            raise ConfigurationError(f"Configuration file not found: {path}")
        return path

    environment = environ.get("OMNE_ENVIRONMENT", "development").strip() or "development"
    candidate = cwd / "configs" / environment / "OMNE.toml"
    if candidate.is_file():
        return candidate
    return None


def _read_config(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigurationError(
            f"Unable to read configuration file {path}: {exc.strerror}"
        ) from exc
    try:
        loaded = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError(f"Invalid TOML in {path}: {exc}") from exc
    return dict(loaded)


def _environment_overrides(environ: Mapping[str, str]) -> dict[str, Any]:
    overrides: dict[str, object] = {}
    for env_name, field_name in ENV_TO_FIELD.items():
        if env_name not in environ:
            continue
        raw = environ[env_name]
        if env_name == "OMNE_CORS_ORIGINS":
            stripped = raw.strip()
            overrides[field_name] = (
                [] if stripped == "" else [part.strip() for part in raw.split(",")]
            )
            continue
        overrides[field_name] = raw.strip()
    return overrides


def _resolve_path(cwd: Path, value: Path) -> Path:
    if value.is_absolute():
        return value
    return (cwd / value).resolve()


def _format_validation_error(exc: ValidationError) -> str:
    parts: list[str] = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error["loc"]) or "settings"
        parts.append(f"{location}: {error['msg']}")
    details = "; ".join(parts) if parts else str(exc)
    return f"Invalid OMNE configuration: {details}"
