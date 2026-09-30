"""Scoped secrets stay out of logs, events, prompts, and task records."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

from core.config.errors import ConfigurationError
from core.config.settings import Settings, load_settings
from core.context.builder import build_context
from core.events.bus import EventBus
from core.logging_config import configure_logging, get_logger
from core.models.credentials import xai_api_key
from core.orchestrator.store import TaskStore
from core.orchestrator.task import Task, TaskErrorRecord
from core.permissions.audit import AuditEntry, AuditLog, audit_now
from core.permissions.evaluator import PermissionEvaluator
from core.permissions.policies import PermissionRequest
from core.tools import build_registry
from core.tools.base import ToolContext
from core.tools.gateway import ToolGateway
from omne.secrets.audit import SecretAuditLog
from omne.secrets.model import REDACTED, SecretDenied, SecretInvalid, SecretScope
from omne.secrets.providers.closed import ClosedSecretProvider
from omne.secrets.providers.linux import LinuxSecretProvider, invalidate_keyring, private_keyring
from omne.secrets.providers.memory import MemorySecretProvider
from omne.secrets.redact import SecretRedactor
from omne.secrets.select import select_provider
from omne.secrets.service import SecretService

_VALUE = "omne-test-credential-value"
_OTHER = "omne-rotated-credential-value"
_ENV = "xai-development-key-0123456789"
_MANAGE = {"secrets": ["manage", "use"]}
_USE = {"secrets": ["use"]}


def _authorize(
    tool_id: str,
    agent_id: str,
    grants: Mapping[str, Sequence[str]],
    environment: str,
    arguments: dict[str, Any],
) -> tuple[str, str]:
    result = PermissionEvaluator().evaluate(
        PermissionRequest(
            tool_id=tool_id,
            arguments=arguments,
            grants={key: list(value) for key, value in grants.items()},
            environment=environment,
            workspace_root="/tmp/omne-secrets",
            agent_id=agent_id,
        )
    )
    return result.decision.value, result.reason


def _service(
    provider: object | None = None,
    *,
    sink: Any = None,
    path: Path | None = None,
    authorize: Any = None,
) -> SecretService:
    return SecretService(
        provider if provider is not None else MemorySecretProvider(),
        authorize=authorize or _authorize,
        audit=SecretAuditLog(path),
        redactor=SecretRedactor(),
        sink=sink,
    )


def _store(
    service: SecretService, *, agents: Sequence[str] = ("coding",), value: str = _VALUE
) -> None:
    service.store(
        scope="api",
        name="billing",
        value=value,
        agents=agents,
        agent_id="core",
        grants=_MANAGE,
        environment="testing",
        approved=True,
    )


def test_scoped_operations_and_audience() -> None:
    service = _service()
    _store(service, agents=("coding", "core"))

    assert service.exists(
        scope="api",
        name="billing",
        agent_id="coding",
        grants=_USE,
        environment="testing",
    )
    assert (
        service.retrieve(
            scope="api",
            name="billing",
            agent_id="coding",
            grants=_USE,
            environment="testing",
        )
        == _VALUE
    )
    assert (
        service.exists(
            scope="api",
            name="billing",
            agent_id="research",
            grants=_USE,
            environment="testing",
        )
        is False
    )
    with pytest.raises(SecretDenied):
        service.retrieve(
            scope="api",
            name="billing",
            agent_id="research",
            grants=_USE,
            environment="testing",
        )

    service.rotate(
        scope="api",
        name="billing",
        value=_OTHER,
        agent_id="core",
        grants=_MANAGE,
        environment="testing",
        approved=True,
    )
    assert (
        service.retrieve(
            scope="api",
            name="billing",
            agent_id="coding",
            grants=_USE,
            environment="testing",
        )
        == _OTHER
    )
    service.delete(
        scope="api",
        name="billing",
        agent_id="core",
        grants=_MANAGE,
        environment="testing",
        approved=True,
    )
    assert (
        service.exists(
            scope="api",
            name="billing",
            agent_id="coding",
            grants=_USE,
            environment="testing",
        )
        is False
    )


def test_missing_grant_wrong_agent_and_production_are_denied() -> None:
    service = _service()
    with pytest.raises(SecretDenied):
        service.store(
            scope="model",
            name="xai",
            value=_VALUE,
            agents=("core",),
            agent_id="coding",
            grants=_MANAGE,
            environment="testing",
            approved=True,
        )
    with pytest.raises(SecretDenied):
        service.store(
            scope="model",
            name="xai",
            value=_VALUE,
            agents=("core",),
            agent_id="core",
            grants=_USE,
            environment="testing",
            approved=True,
        )
    with pytest.raises(SecretDenied):
        service.store(
            scope="model",
            name="xai",
            value=_VALUE,
            agents=("core",),
            agent_id="core",
            grants=_MANAGE,
            environment="testing",
            approved=False,
        )
    with pytest.raises(SecretDenied):
        service.store(
            scope="model",
            name="xai",
            value=_VALUE,
            agents=("core",),
            agent_id="core",
            grants=_MANAGE,
            environment="production",
            approved=True,
        )
    assert service.audit.entries()
    rendered = json.dumps([entry.model_dump(mode="json") for entry in service.audit.entries()])
    assert _VALUE not in rendered


def test_permission_failure_does_not_record_the_value() -> None:
    def explode(*_args: object) -> tuple[str, str]:
        raise RuntimeError(_VALUE)

    service = _service(authorize=explode)
    with pytest.raises(SecretDenied, match="permission check failed"):
        service.store(
            scope="service",
            name="mail",
            value=_VALUE,
            agents=("core",),
            agent_id="core",
            grants=_MANAGE,
            environment="testing",
            approved=True,
        )
    rendered = json.dumps([entry.model_dump(mode="json") for entry in service.audit.entries()])
    assert _VALUE not in rendered
    assert "permission check failed" in rendered


def test_invalid_value_is_rejected_without_being_copied() -> None:
    service = _service()
    with pytest.raises(SecretInvalid):
        service.store(
            scope="browser",
            name="session",
            value="short",
            agents=("core",),
            agent_id="core",
            grants=_MANAGE,
            environment="testing",
            approved=True,
        )
    rendered = json.dumps([entry.model_dump(mode="json") for entry in service.audit.entries()])
    assert "short" not in rendered


def test_permissive_permission_does_not_widen_the_audience() -> None:
    def allow_all(*_args: object) -> tuple[str, str]:
        return ("ALLOW", "granted")

    service = _service(authorize=allow_all)
    service.store(
        scope="network",
        name="wifi",
        value=_VALUE,
        agents=("coding",),
        agent_id="research",
        grants={},
        environment="production",
        approved=True,
    )
    with pytest.raises(SecretDenied):
        service.retrieve(
            scope="network",
            name="wifi",
            agent_id="research",
            grants={},
            environment="production",
        )


def test_closed_provider_fails_closed() -> None:
    service = _service(ClosedSecretProvider())
    with pytest.raises(SecretDenied, match="secret storage failed"):
        service.store(
            scope="application",
            name="editor",
            value=_VALUE,
            agents=("core",),
            agent_id="core",
            grants=_MANAGE,
            environment="testing",
            approved=True,
        )


def test_development_fallback_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    class Unavailable:
        available = False

    monkeypatch.setattr("omne.secrets.select.LinuxSecretProvider", lambda: Unavailable())

    assert isinstance(select_provider("testing"), MemorySecretProvider)
    assert isinstance(select_provider("development"), ClosedSecretProvider)
    assert isinstance(select_provider("development", dev_fallback=True), MemorySecretProvider)
    assert isinstance(select_provider("production", dev_fallback=True), ClosedSecretProvider)
    assert isinstance(select_provider("staging", dev_fallback=True), ClosedSecretProvider)


def test_fallback_setting_accepts_only_allow(tmp_path: Path) -> None:
    enabled = load_settings(environ={"OMNE_SECRETS_DEV_FALLBACK": "allow"}, cwd=tmp_path)
    disabled = load_settings(environ={"OMNE_SECRETS_DEV_FALLBACK": "false"}, cwd=tmp_path)

    assert enabled.secrets_dev_fallback is True
    assert disabled.secrets_dev_fallback is False
    with pytest.raises(ConfigurationError, match="secrets_dev_fallback"):
        load_settings(environ={"OMNE_SECRETS_DEV_FALLBACK": "yes"}, cwd=tmp_path)


def test_linux_keyring_round_trip() -> None:
    serial, _library = private_keyring()
    try:
        provider = LinuxSecretProvider(keyring=serial)
        service = _service(provider)
        _store(service, agents=("coding",))
        assert (
            service.retrieve(
                scope="api",
                name="billing",
                agent_id="coding",
                grants=_USE,
                environment="testing",
            )
            == _VALUE
        )
        service.delete(
            scope="api",
            name="billing",
            agent_id="core",
            grants=_MANAGE,
            environment="testing",
            approved=True,
        )
        assert provider.get(SecretScope.API, "billing") is None
    finally:
        invalidate_keyring(serial)


def test_default_linux_provider_can_store_and_delete() -> None:
    from omne.secrets.model import SecretScope

    provider = LinuxSecretProvider()
    assert provider.available is True
    service = _service(provider)
    service.store(
        scope="service",
        name="probe",
        value=_VALUE,
        agents=("core",),
        agent_id="core",
        grants=_MANAGE,
        environment="testing",
        approved=True,
    )
    try:
        assert provider.get(SecretScope.SERVICE, "probe") is not None
        assert _VALUE not in json.dumps(provider.get(SecretScope.SERVICE, "probe")[1])
    finally:
        provider.remove(SecretScope.SERVICE, "probe")
    assert provider.get(SecretScope.SERVICE, "probe") is None


def test_secrets_do_not_leak_into_logs_events_context_or_tasks(tmp_path: Path) -> None:
    bus = EventBus(persist_path=tmp_path / "events.jsonl")
    audit_path = tmp_path / "secrets-audit.jsonl"
    service = _service(
        sink=lambda event_type, payload: bus.publish(event_type, payload=payload),
        path=audit_path,
    )
    _store(service)
    buffer = StringIO()
    configure_logging(Settings(log_format="text", log_level="INFO"), stream=buffer)
    get_logger("secrets").info("provider returned %s", _VALUE)
    try:
        raise RuntimeError(f"upstream rejected {_VALUE}")
    except RuntimeError:
        get_logger("secrets").exception("call failed")
    bus.publish(
        "trace.note",
        trace_id="trace-1",
        payload={"note": _VALUE, "api_key": _VALUE, "password": "other-password-value"},
    )
    now = datetime.now(UTC)
    task = Task(
        id="task-secret",
        objective=f"call the api with {_VALUE}",
        created_at=now,
        updated_at=now,
        result={"stdout": _VALUE},
        errors=[TaskErrorRecord(code="provider", message=f"rejected {_VALUE}")],
    )
    store = TaskStore(tmp_path / "tasks.sqlite")
    saved = store.save(task)
    context = build_context(
        request=f"use {_VALUE}",
        memories=[{"content": f"token {_VALUE}", "source": "memory", "scope": "task"}],
        project_name="demo",
        world_revision=1,
        item_limit=4,
        char_limit=1000,
    )
    rendered = "\n".join(
        [
            buffer.getvalue(),
            (tmp_path / "events.jsonl").read_text(encoding="utf-8"),
            audit_path.read_text(encoding="utf-8"),
            (tmp_path / "tasks.sqlite").read_bytes().decode("utf-8", errors="ignore"),
            json.dumps(saved.model_dump(mode="json")),
            context.render(char_limit=1000),
            json.dumps([event.model_dump(mode="json") for event in bus.list_events()]),
        ]
    )

    assert _VALUE not in rendered
    assert REDACTED in buffer.getvalue()
    assert REDACTED in saved.objective
    assert saved.result is not None
    assert saved.result["stdout"] == REDACTED
    assert REDACTED in context.render(char_limit=1000)
    trace = next(event for event in bus.list_events() if event.trace_id == "trace-1")
    assert trace.payload["note"] == REDACTED
    assert trace.payload["api_key"] == REDACTED
    assert trace.payload["password"] == REDACTED


def test_gateway_audit_and_events_do_not_keep_a_registered_secret(tmp_path: Path) -> None:
    service = _service()
    _store(service)
    bus = EventBus()
    audit = AuditLog(tmp_path / "audit.jsonl")
    gateway = ToolGateway(build_registry(), PermissionEvaluator(), audit, bus)
    result = gateway.invoke(
        tool_id="filesystem.write",
        arguments={"path": "notes.txt", "content": _VALUE},
        context=ToolContext(
            task_id="task",
            agent_id="coding",
            user="local",
            workspace_root=tmp_path,
            timeout_seconds=5,
        ),
        grants={"filesystem": ["workspace"]},
        environment="testing",
    )

    assert result.ok is True
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == _VALUE
    rendered = json.dumps([event.model_dump(mode="json") for event in bus.list_events()])
    rendered += (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert _VALUE not in rendered
    assert REDACTED in rendered


def test_permission_audit_redacts_arguments(tmp_path: Path) -> None:
    service = _service()
    _store(service)
    audit = AuditLog(tmp_path / "audit.jsonl")
    audit.record(
        AuditEntry(
            timestamp=audit_now(),
            decision="ALLOW",
            policy_id="default",
            reason=f"saw {_VALUE}",
            tool_id="filesystem.write",
            task_id="task",
            agent_id="coding",
            user="local",
            arguments={"content": _VALUE, "token": "plain-token-value"},
        )
    )
    rendered = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert _VALUE not in rendered
    assert "plain-token-value" not in rendered


def test_development_keeps_xai_environment_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XAI_API_KEY", _ENV)
    service = _service()
    settings = Settings(environment="development", secrets_dev_fallback=False)

    assert xai_api_key(settings, service) == _ENV
    assert _ENV not in json.dumps(settings.model_dump(mode="json"))


def test_stored_xai_secret_replaces_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XAI_API_KEY", _ENV)
    service = _service()
    service.store(
        scope="model",
        name="xai",
        value=_VALUE,
        agents=("core",),
        agent_id="core",
        grants=_MANAGE,
        environment="development",
        approved=True,
    )
    settings = Settings(environment="development")

    assert xai_api_key(settings, service) == _VALUE


def test_production_ignores_xai_environment_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XAI_API_KEY", _ENV)
    service = _service()
    settings = Settings(environment="production")

    assert xai_api_key(settings, service) is None
    rendered = json.dumps(settings.model_dump(mode="json"))
    assert _ENV not in rendered
    assert "xai_api_key" not in rendered


def test_log_without_a_registered_secret_stays_literal() -> None:
    logging.getLogger("OMNE").handlers.clear()
    buffer = StringIO()
    configure_logging(Settings(log_format="json", log_level="INFO"), stream=buffer)
    get_logger("core").info("core ready")
    payload = json.loads(buffer.getvalue())
    assert payload["message"] == "core ready"
