"""Login grants the user session and refuses a hand-started stack."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.conftest import ROOT

from omne.login import (
    STARTUP,
    load_operator,
    login_lines,
    login_main,
    manual_start,
    session_grant,
    startup_chain,
    user_session_lines,
    user_session_main,
)


def _enroll(root: Path, payload: object, *, persistent: bool = False) -> None:
    relative = Path("var/lib/omne/operator.json") if persistent else Path("etc/omne/operator.json")
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_startup_is_power_then_desktop() -> None:
    assert startup_chain() == ("power", "login", "user_session", "core", "shell", "desktop")
    assert STARTUP[0] == "power"
    assert STARTUP[-1] == "desktop"


def test_enrolled_operator_receives_the_system_account(tmp_path: Path) -> None:
    _enroll(tmp_path, {"name": "omne", "enrolled": True})

    grant = session_grant(load_operator(tmp_path))

    assert grant is not None
    assert grant.name == "omne"
    assert grant.account == "omne"
    assert login_lines(grant) == ["OMNE LOGIN", "operator omne"]
    assert user_session_lines(grant) == ["USER SESSION", "operator omne"]


def test_persistent_record_wins_and_a_locked_operator_waits(tmp_path: Path) -> None:
    _enroll(tmp_path, {"name": "omne", "enrolled": True})
    _enroll(tmp_path, {"name": "omne", "enrolled": False}, persistent=True)

    assert load_operator(tmp_path) is None
    assert login_lines(None) == ["OMNE LOGIN", "waiting for an operator"]
    assert user_session_lines(None) == []


def test_a_broken_record_does_not_fall_through(tmp_path: Path) -> None:
    _enroll(tmp_path, {"name": "omne", "enrolled": True})
    _enroll(tmp_path, {"name": "root", "command": "python server.py"}, persistent=True)

    assert load_operator(tmp_path) is None


def test_login_exits_when_the_operator_is_enrolled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _enroll(tmp_path, {"name": "omne", "enrolled": True})
    monkeypatch.setenv("OMNE_LOGIN_ROOT", str(tmp_path))

    assert login_main([]) == 0
    assert user_session_main([]) == 0
    text = capsys.readouterr().out
    assert text.splitlines() == [
        "OMNE LOGIN",
        "operator omne",
        "USER SESSION",
        "operator omne",
    ]


def test_login_waits_without_an_operator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OMNE_LOGIN_ROOT", str(tmp_path))

    assert login_main([]) == 1
    assert user_session_main([]) == 1
    assert "USER SESSION" not in capsys.readouterr().out


def test_a_manual_command_does_not_start_the_session(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OMNE_LOGIN_ROOT", "/")
    assert manual_start(["python", "server.py"]) is True
    assert manual_start(["python3", "-m", "http.server"]) is True
    assert manual_start([]) is False

    assert login_main(["python", "server.py"]) == 2
    assert user_session_main(["npm", "start"]) == 2
    assert capsys.readouterr().out == "refusing a manual start\nrefusing a manual start\n"


def test_units_start_core_only_after_the_user_session() -> None:
    linux = ROOT / "system" / "linux"
    login = (linux / "omne-login.service").read_text(encoding="utf-8")
    session = (linux / "omne-user-session.service").read_text(encoding="utf-8")
    desktop = (linux / "omne-session.service").read_text(encoding="utf-8")
    dropin = (linux / "omne-core.service.d" / "user-session.conf").read_text(encoding="utf-8")
    target = (linux / "omne.target").read_text(encoding="utf-8")
    operator = json.loads((linux / "operator.json").read_text(encoding="utf-8"))

    assert "ExecStart=/usr/bin/omne-login" in login
    assert "Conflicts=getty@tty1.service" in login
    assert "Before=omne-user-session.service" in login
    assert "Requires=omne-login.service" in session
    assert "Wants=omne-core.service omne-shell.service" in session
    assert "Before=omne-core.service" in session
    assert "ExecStart=/usr/bin/omne-user-session" in session
    assert "Requires=omne-user-session.service" in dropin
    assert "Requires=omne-user-session.service omne-shell.service" in desktop
    assert "omne-user-session.service" in target
    assert "omne-session.service" not in target
    assert "python server.py" not in login
    assert "python server.py" not in session
    assert operator == {"enrolled": True, "name": "omne"}
