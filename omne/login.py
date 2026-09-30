"""Grant the user session that starts OMNE.

Power reaches this program from systemd. It does not open a terminal, and it
does not start Python, the shell, or an agent by hand. An enrolled operator
gets a session. That session is what starts the core, the shell, and the
desktop.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

STARTUP: tuple[str, ...] = ("power", "login", "user_session", "core", "shell", "desktop")
SESSION_ACCOUNT = "omne"
_NAME = re.compile(r"[a-z][a-z0-9_-]{0,31}")
_MANUAL = (
    "python server.py",
    "python3 server.py",
    "python -m http.server",
    "python3 -m http.server",
    "npm start",
    "npm run dev",
)


class Operator(BaseModel):
    """One enrolled person. The file carries no credential and no command."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    enrolled: bool

    @field_validator("name")
    @classmethod
    def _session_name(cls, value: str) -> str:
        if _NAME.fullmatch(value) is None:
            raise ValueError("operator name is not a session name")
        return value


class SessionGrant(BaseModel):
    """The session account is the system user. The operator name is not a login shell."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    account: str


def startup_chain() -> tuple[str, ...]:
    """Power, login, user session, core, shell, desktop. In that order."""

    return STARTUP


def manual_start(argv: list[str]) -> bool:
    """True when the words are someone starting the stack by hand."""

    text = " ".join(argv).strip().lower()
    return any(item in text for item in _MANUAL)


def operator_file(root: Path) -> Path | None:
    """Prefer the persistent record. The image record survives a volatile /var."""

    persistent = root / "var" / "lib" / "omne" / "operator.json"
    image = root / "etc" / "omne" / "operator.json"
    if persistent.is_file():
        return persistent
    if image.is_file():
        return image
    return None


def load_operator(root: Path) -> Operator | None:
    """Return the enrolled operator. A broken record grants nothing."""

    path = operator_file(root)
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        operator = Operator.model_validate(payload)
    except (OSError, json.JSONDecodeError, UnicodeError, ValidationError):
        return None
    if not operator.enrolled:
        return None
    return operator


def session_grant(operator: Operator | None) -> SessionGrant | None:
    """Map an enrolled operator onto the system account. Never onto a shell user."""

    if operator is None:
        return None
    return SessionGrant(name=operator.name, account=SESSION_ACCOUNT)


def login_lines(grant: SessionGrant | None) -> list[str]:
    """Console lines for the login stage. Waiting does not name a session."""

    if grant is None:
        return ["OMNE LOGIN", "waiting for an operator"]
    return ["OMNE LOGIN", f"operator {grant.name}"]


def user_session_lines(grant: SessionGrant | None) -> list[str]:
    """Console lines once the granted session is the one systemd started."""

    if grant is None:
        return []
    return ["USER SESSION", f"operator {grant.name}"]


def login_main(argv: list[str] | None = None) -> int:
    """Print OMNE LOGIN. Exit 0 only when the operator receives a session."""

    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        print("refusing a manual start", flush=True)
        return 2
    grant = session_grant(load_operator(_root()))
    for line in login_lines(grant):
        print(line, flush=True)
    return 0 if grant is not None else 1


def user_session_main(argv: list[str] | None = None) -> int:
    """Print USER SESSION after login. Exit 1 when no operator was granted."""

    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        print("refusing a manual start", flush=True)
        return 2
    grant = session_grant(load_operator(_root()))
    lines = user_session_lines(grant)
    if not lines:
        print("waiting for an operator", flush=True)
        return 1
    for line in lines:
        print(line, flush=True)
    return 0


def _root() -> Path:
    raw = os.environ.get("OMNE_LOGIN_ROOT", "").strip()
    return Path(raw) if raw else Path("/")
