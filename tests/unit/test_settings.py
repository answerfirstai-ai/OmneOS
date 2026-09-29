"""Configuration loading tests."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from tests.conftest import ROOT

from core import __version__
from core.config.errors import ConfigurationError
from core.config.settings import (
    KNOWN_ENVIRONMENT_VARIABLES,
    load_settings,
    prepare_runtime_directories,
)


def test_defaults_when_no_file_is_present(tmp_path: Path) -> None:
    settings = load_settings(environ={}, cwd=tmp_path)

    assert settings.environment == "development"
    assert settings.log_level == "INFO"
    assert settings.log_format == "text"
    assert settings.host == "127.0.0.1"
    assert settings.port == 8787
    assert settings.cors_origins == []
    assert settings.workspace_root == (tmp_path / "workspace").resolve()
    assert settings.data_dir == (tmp_path / "memory").resolve()


def test_environment_overrides_file(tmp_path: Path) -> None:
    config = tmp_path / "OMNE.toml"
    config.write_text(
        "\n".join(
            [
                'environment = "development"',
                'log_level = "INFO"',
                "port = 1111",
                'host = "127.0.0.1"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    settings = load_settings(
        environ={"OMNE_PORT": "2222", "OMNE_LOG_LEVEL": "debug"},
        config_path=config,
        cwd=tmp_path,
    )

    assert settings.port == 2222
    assert settings.log_level == "DEBUG"
    assert settings.environment == "development"


def test_discovers_config_for_selected_environment(tmp_path: Path) -> None:
    path = tmp_path / "configs" / "testing" / "OMNE.toml"
    path.parent.mkdir(parents=True)
    path.write_text('log_level = "ERROR"\n', encoding="utf-8")

    settings = load_settings(environ={"OMNE_ENVIRONMENT": "testing"}, cwd=tmp_path)

    assert settings.environment == "testing"
    assert settings.log_level == "ERROR"


def test_missing_explicit_config_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="not found"):
        load_settings(config_path=tmp_path / "missing.toml", environ={}, cwd=tmp_path)


def test_invalid_toml_is_an_error(tmp_path: Path) -> None:
    config = tmp_path / "OMNE.toml"
    config.write_text("port = [\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="Invalid TOML"):
        load_settings(config_path=config, environ={}, cwd=tmp_path)


def test_unknown_file_key_is_rejected(tmp_path: Path) -> None:
    config = tmp_path / "OMNE.toml"
    config.write_text('theme = "blue"\n', encoding="utf-8")

    with pytest.raises(ConfigurationError, match="theme"):
        load_settings(config_path=config, environ={}, cwd=tmp_path)


def test_unknown_environment_variable_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="OMNE_NOT_A_SETTING"):
        load_settings(environ={"OMNE_NOT_A_SETTING": "1"}, cwd=tmp_path)


def test_invalid_port_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="port"):
        load_settings(environ={"OMNE_PORT": "0"}, cwd=tmp_path)


def test_empty_cors_override_clears_file_origins(tmp_path: Path) -> None:
    config = tmp_path / "OMNE.toml"
    config.write_text('cors_origins = ["http://127.0.0.1:4173"]\n', encoding="utf-8")

    settings = load_settings(
        environ={"OMNE_CORS_ORIGINS": ""},
        config_path=config,
        cwd=tmp_path,
    )

    assert settings.cors_origins == []


def test_wildcard_cors_cannot_be_combined(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="CORS"):
        load_settings(
            environ={"OMNE_CORS_ORIGINS": "*,http://127.0.0.1:4173"},
            cwd=tmp_path,
        )


def test_absolute_data_dir_is_preserved(tmp_path: Path) -> None:
    target = tmp_path / "state"
    settings = load_settings(environ={"OMNE_DATA_DIR": str(target)}, cwd=tmp_path)

    assert settings.data_dir == target.resolve()


def test_prepare_runtime_directories_creates_paths(tmp_path: Path) -> None:
    settings = load_settings(
        environ={
            "OMNE_WORKSPACE_ROOT": "workspace",
            "OMNE_DATA_DIR": "memory",
        },
        cwd=tmp_path,
    )

    prepare_runtime_directories(settings)

    assert settings.workspace_root.is_dir()
    assert settings.data_dir.is_dir()


def test_shipped_configs_load(repo_root: Path) -> None:
    for name in ("development", "testing", "production"):
        settings = load_settings(
            environ={},
            config_path=repo_root / "configs" / name / "OMNE.toml",
            cwd=repo_root,
        )
        assert settings.environment == name


def test_repository_discovery_uses_development_config(repo_root: Path) -> None:
    settings = load_settings(environ={}, cwd=repo_root)

    assert settings.cors_origins == [
        "http://127.0.0.1:4173",
        "http://localhost:4173",
    ]


def test_env_example_documents_known_variables() -> None:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    keys = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        keys.add(stripped.split("=", 1)[0])

    assert keys <= KNOWN_ENVIRONMENT_VARIABLES
    assert "OMNE_ENVIRONMENT" in keys
    assert "OMNE_CONFIG" in KNOWN_ENVIRONMENT_VARIABLES


def test_package_version_matches_project_metadata() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == __version__

    from importlib.metadata import version

    assert version("OMNE-os") == __version__
