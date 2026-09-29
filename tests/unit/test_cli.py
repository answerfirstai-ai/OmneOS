"""Command-line entry point tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from core import __version__
from core.api.main import main


def test_version_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == __version__


def test_help_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "check" in capsys.readouterr().out


def test_check_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)

    assert main(["check"]) == 0

    captured = capsys.readouterr()
    assert captured.out.strip() == f"jarvis-core {__version__} development ok"
    assert "JARVIS Core check passed" in captured.err
    assert (tmp_path / "workspace").is_dir()
    assert (tmp_path / "memory").is_dir()


def test_invalid_configuration_exits_with_code_2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JARVIS_PORT", "0")

    assert main(["check"]) == 2
    assert "Invalid JARVIS configuration" in capsys.readouterr().err


def test_unknown_command_exits() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["nope"])
    assert exc.value.code == 2


def test_serve_rejects_invalid_port(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    assert main(["serve", "--port", "70000"]) == 2
    assert "port" in capsys.readouterr().err
