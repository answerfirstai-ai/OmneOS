"""Permission-checked secret operations.

An agent receives a credential only when the grant allows use and the record
names that agent. Management is limited to the core and still requires
confirmation outside production. Production management is denied.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, NoReturn

from omne.secrets.audit import SecretAuditEntry, SecretAuditLog, audit_now
from omne.secrets.model import (
    SecretDenied,
    SecretError,
    SecretInvalid,
    SecretScope,
    parse_agents,
    parse_name,
    parse_scope,
    parse_value,
)
from omne.secrets.provider import SecretProvider
from omne.secrets.redact import SecretRedactor, install_redactor

Authorize = Callable[[str, str, Mapping[str, Sequence[str]], str, dict[str, Any]], tuple[str, str]]
EventSink = Callable[[str, dict[str, Any]], None]

_MANAGE = {
    "store": "secret.store",
    "delete": "secret.delete",
    "rotate": "secret.rotate",
}
_USE = {
    "retrieve": "secret.retrieve",
    "exists": "secret.exists",
}


class SecretService:
    """Store and reveal scoped credentials."""

    def __init__(
        self,
        provider: SecretProvider,
        *,
        authorize: Authorize | None = None,
        audit: SecretAuditLog | None = None,
        redactor: SecretRedactor | None = None,
        sink: EventSink | None = None,
    ) -> None:
        self._provider = provider
        self._authorize = authorize or _deny_all
        self._audit = audit or SecretAuditLog()
        self._redactor = redactor or SecretRedactor()
        self._sink = sink
        install_redactor(self._redactor)

    @property
    def redactor(self) -> SecretRedactor:
        return self._redactor

    @property
    def audit(self) -> SecretAuditLog:
        return self._audit

    def store(
        self,
        *,
        scope: str,
        name: str,
        value: str,
        agents: Sequence[str],
        agent_id: str,
        grants: Mapping[str, Sequence[str]],
        environment: str,
        approved: bool = False,
    ) -> None:
        """Save a new credential for ``agents``. An existing name is rejected."""

        parsed = self._reference(scope, name)
        audience = self._audience(agents)
        secret = self._secret(value)
        self._permit(
            "store",
            parsed,
            agent_id,
            grants,
            environment,
            approved=approved,
        )
        if self._present(parsed, agent_id, "store"):
            self._reject(parsed, agent_id, "store", "secret already exists")
        self._write(parsed, secret, audience, agent_id, "store", "secret stored")

    def retrieve(
        self,
        *,
        scope: str,
        name: str,
        agent_id: str,
        grants: Mapping[str, Sequence[str]],
        environment: str,
    ) -> str:
        """Return the one credential this agent is allowed to receive."""

        parsed = self._reference(scope, name)
        self._permit("retrieve", parsed, agent_id, grants, environment, approved=True)
        record = self._read(parsed, agent_id, "retrieve")
        if record is None or agent_id not in record[1]:
            self._reject(parsed, agent_id, "retrieve", "secret is not available to this agent")
        value = record[0]
        self._redactor.register(value)
        self._accept(parsed, agent_id, "retrieve", "secret retrieved")
        return value

    def delete(
        self,
        *,
        scope: str,
        name: str,
        agent_id: str,
        grants: Mapping[str, Sequence[str]],
        environment: str,
        approved: bool = False,
    ) -> None:
        """Remove a credential. The value is not returned."""

        parsed = self._reference(scope, name)
        self._permit("delete", parsed, agent_id, grants, environment, approved=approved)
        try:
            removed = self._provider.remove(parsed[0], parsed[1])
        except SecretError:
            self._reject(parsed, agent_id, "delete", "secret storage failed")
        except Exception:
            self._reject(parsed, agent_id, "delete", "secret storage failed")
        if not removed:
            self._reject(parsed, agent_id, "delete", "secret does not exist")
        self._accept(parsed, agent_id, "delete", "secret deleted")

    def rotate(
        self,
        *,
        scope: str,
        name: str,
        value: str,
        agent_id: str,
        grants: Mapping[str, Sequence[str]],
        environment: str,
        approved: bool = False,
    ) -> None:
        """Replace the credential and keep the existing audience."""

        parsed = self._reference(scope, name)
        secret = self._secret(value)
        self._permit("rotate", parsed, agent_id, grants, environment, approved=approved)
        record = self._read(parsed, agent_id, "rotate")
        if record is None:
            self._reject(parsed, agent_id, "rotate", "secret does not exist")
        self._redactor.register(record[0])
        self._write(parsed, secret, record[1], agent_id, "rotate", "secret rotated")

    def exists(
        self,
        *,
        scope: str,
        name: str,
        agent_id: str,
        grants: Mapping[str, Sequence[str]],
        environment: str,
    ) -> bool:
        """Report a credential this agent is allowed to know about."""

        parsed = self._reference(scope, name)
        self._permit("exists", parsed, agent_id, grants, environment, approved=True)
        record = self._read(parsed, agent_id, "exists")
        visible = False
        if record is not None and agent_id in record[1]:
            self._redactor.register(record[0])
            visible = True
        self._accept(
            parsed,
            agent_id,
            "exists",
            "secret exists" if visible else "secret is not available to this agent",
        )
        return visible

    def _reference(self, scope: str, name: str) -> tuple[SecretScope, str]:
        try:
            return parse_scope(scope), parse_name(name)
        except SecretInvalid as exc:
            self._audit_invalid(exc)
            raise

    def _audience(self, agents: Sequence[str]) -> tuple[str, ...]:
        try:
            return parse_agents(agents)
        except SecretInvalid as exc:
            self._audit_invalid(exc)
            raise

    def _secret(self, value: str) -> str:
        try:
            return parse_value(value)
        except SecretInvalid as exc:
            self._audit_invalid(exc)
            raise

    def _permit(
        self,
        action: str,
        parsed: tuple[SecretScope, str],
        agent_id: str,
        grants: Mapping[str, Sequence[str]],
        environment: str,
        *,
        approved: bool,
    ) -> None:
        tool_id = _MANAGE.get(action) or _USE[action]
        arguments = {"scope": parsed[0].value, "name": parsed[1]}
        try:
            decision, reason = self._authorize(tool_id, agent_id, grants, environment, arguments)
        except Exception:
            self._reject(parsed, agent_id, action, "secret permission check failed")
        if decision == "CONFIRM" and approved:
            return
        if decision != "ALLOW":
            self._reject(parsed, agent_id, action, reason or "secret access is denied")

    def _present(self, parsed: tuple[SecretScope, str], agent_id: str, action: str) -> bool:
        try:
            return self._provider.contains(parsed[0], parsed[1])
        except SecretError:
            self._reject(parsed, agent_id, action, "secret storage failed")
        except Exception:
            self._reject(parsed, agent_id, action, "secret storage failed")

    def _read(
        self, parsed: tuple[SecretScope, str], agent_id: str, action: str
    ) -> tuple[str, tuple[str, ...]] | None:
        try:
            return self._provider.get(parsed[0], parsed[1])
        except SecretError:
            self._reject(parsed, agent_id, action, "secret storage failed")
        except Exception:
            self._reject(parsed, agent_id, action, "secret storage failed")

    def _write(
        self,
        parsed: tuple[SecretScope, str],
        value: str,
        agents: tuple[str, ...],
        agent_id: str,
        action: str,
        reason: str,
    ) -> None:
        try:
            self._provider.put(parsed[0], parsed[1], value, agents)
        except SecretError:
            self._reject(parsed, agent_id, action, "secret storage failed")
        except Exception:
            self._reject(parsed, agent_id, action, "secret storage failed")
        self._redactor.register(value)
        self._accept(parsed, agent_id, action, reason)

    def _accept(
        self,
        parsed: tuple[SecretScope, str],
        agent_id: str,
        action: str,
        reason: str,
    ) -> None:
        self._record(parsed, agent_id, action, "allow", reason)

    def _reject(
        self,
        parsed: tuple[SecretScope, str],
        agent_id: str,
        action: str,
        reason: str,
    ) -> NoReturn:
        self._record(parsed, agent_id, action, "deny", reason)
        raise SecretDenied(reason)

    def _record(
        self,
        parsed: tuple[SecretScope, str],
        agent_id: str,
        action: str,
        decision: str,
        reason: str,
    ) -> None:
        safe_agent = agent_id if agent_id else "unknown"
        entry = SecretAuditEntry(
            timestamp=audit_now(),
            action=action,
            scope=parsed[0].value,
            name=parsed[1],
            agent_id=safe_agent,
            decision=decision,
            reason=reason,
        )
        self._audit.record(entry)
        if self._sink is not None:
            self._sink(
                "secret.accessed",
                {
                    "action": action,
                    "scope": parsed[0].value,
                    "name": parsed[1],
                    "agent_id": safe_agent,
                    "decision": decision,
                    "reason": reason,
                },
            )

    def _audit_invalid(self, exc: SecretInvalid) -> None:
        entry = SecretAuditEntry(
            timestamp=audit_now(),
            action="reject",
            scope="invalid",
            name="invalid",
            agent_id="unknown",
            decision="deny",
            reason=str(exc),
        )
        self._audit.record(entry)
        if self._sink is not None:
            self._sink(
                "secret.accessed",
                {
                    "action": "reject",
                    "scope": "invalid",
                    "name": "invalid",
                    "agent_id": "unknown",
                    "decision": "deny",
                    "reason": str(exc),
                },
            )


def _deny_all(
    tool_id: str,
    agent_id: str,
    grants: Mapping[str, Sequence[str]],
    environment: str,
    arguments: dict[str, Any],
) -> tuple[str, str]:
    del tool_id, agent_id, grants, environment, arguments
    return ("DENY", "secret access is denied")
