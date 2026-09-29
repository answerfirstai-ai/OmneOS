"""Grants for window changes.

Listing windows is a diagnostic and does not use this gate. A mutation applies
only when the decision is allow. Confirm is not an apply.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

GRANT_REQUIRED = "window grant is required"
FOREIGN_WINDOW = "this window is not owned by the agent"
PRODUCTION_MANAGE = "managing every window is denied in production"
CONFIRM_REQUIRED = "confirmation is required"

Subject = Literal["launch", "session", "window"]


class WindowAccess(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    CONFIRM = "confirm"


class AccessDecision(BaseModel):
    """Allow, deny, or hold a window mutation for confirmation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    access: WindowAccess
    reason: str


def decide(
    *,
    kind: Subject,
    agent_id: str,
    owner: str | None,
    grants: Mapping[str, Sequence[str]],
    environment: str,
) -> AccessDecision:
    """Decide whether one agent may change the recorded session.

    ``window: own`` covers launch and windows that agent owns.
    ``window: manage`` is the grant that would cover every window. Production
    denies it. Development and testing do not apply it until a confirmation
    flow exists.
    """

    if not agent_id.strip():
        return AccessDecision(access=WindowAccess.DENY, reason=GRANT_REQUIRED)
    granted = grants.get("window", ())
    own = "own" in granted
    manage = "manage" in granted
    if kind in {"launch", "session"}:
        return _session_grant(own=own, manage=manage, environment=environment)
    if not own and not manage:
        return AccessDecision(access=WindowAccess.DENY, reason=GRANT_REQUIRED)
    if owner is not None and owner == agent_id and own:
        return AccessDecision(access=WindowAccess.ALLOW, reason="allowed")
    if not manage:
        if owner is not None and owner == agent_id:
            return AccessDecision(access=WindowAccess.DENY, reason=GRANT_REQUIRED)
        return AccessDecision(access=WindowAccess.DENY, reason=FOREIGN_WINDOW)
    if environment == "production":
        return AccessDecision(access=WindowAccess.DENY, reason=PRODUCTION_MANAGE)
    return AccessDecision(access=WindowAccess.CONFIRM, reason=CONFIRM_REQUIRED)


def _session_grant(*, own: bool, manage: bool, environment: str) -> AccessDecision:
    if own or (manage and environment != "production"):
        return AccessDecision(access=WindowAccess.ALLOW, reason="allowed")
    if manage:
        return AccessDecision(access=WindowAccess.DENY, reason=PRODUCTION_MANAGE)
    return AccessDecision(access=WindowAccess.DENY, reason=GRANT_REQUIRED)
