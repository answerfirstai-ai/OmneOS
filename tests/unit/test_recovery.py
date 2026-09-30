"""Failure injection for startup, safe mode, and recovery commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.support import runtime_settings

from core.api.main import main
from core.api.routes import route_get, route_post
from core.api.runtime import build_OMNE
from omne.recovery.model import CHECK_REASONS, CHECKS, CheckName
from omne.recovery.probe import LinuxRecoveryProbe
from omne.recovery.service import RecoveryRefused, RecoveryService


def test_healthy_start_is_normal(tmp_path: Path) -> None:
    notes = _notes(tmp_path)
    status = RecoveryService(tmp_path / "recovery", updates_dir=tmp_path / "updates").assess()

    assert status.state == "NORMAL"
    assert status.explanation == "startup checks passed"
    assert status.diagnostics_available is True
    assert status.data_erased is False
    assert status.os_reinstalled is False
    assert status.third_party_agents_enabled is True
    assert status.optional_models_enabled is True
    assert status.shell_reduced is False
    assert [item.name for item in status.checks] == list(CHECKS)
    assert "erase" in status.refused_actions
    assert "reinstall" in status.refused_actions
    assert notes.read_text(encoding="utf-8") == "keep\n"


def test_core_crash_is_explained_and_repeated_failures_enter_safe_mode(tmp_path: Path) -> None:
    notes = _notes(tmp_path)
    service = RecoveryService(tmp_path / "recovery", updates_dir=tmp_path / "updates")
    service.begin_boot()
    once = service.begin_boot()

    assert once.state == "RECOVERY"
    assert once.startup_failures == 1
    assert "normal startup failed" in once.explanation
    assert "core stopped before it was ready" in once.explanation
    assert once.minimal_services is False

    status = once
    for _ in range(2):
        status = service.begin_boot()

    assert status.state == "SAFE_MODE"
    assert status.startup_failures == 3
    assert status.minimal_services is True
    assert status.third_party_agents_enabled is False
    assert status.optional_models_enabled is False
    assert status.shell_reduced is True
    assert status.diagnostics_available is True
    assert "startup failed 3 consecutive times" in status.explanation
    assert service.disabled_agent_ids(["system", "coding", "plugin"]) == ["plugin"]
    assert service.disabled_model_ids([("mock-default", "mock"), ("xai-default", "xai")]) == [
        "xai-default"
    ]
    assert notes.read_text(encoding="utf-8") == "keep\n"
    assert status.data_erased is False
    assert status.os_reinstalled is False


def test_clean_shutdown_does_not_count_as_a_crash(tmp_path: Path) -> None:
    service = RecoveryService(tmp_path / "recovery")
    service.begin_boot()
    service.mark_ready()
    service.mark_stopped()
    status = service.begin_boot()

    assert status.state == "NORMAL"
    assert status.startup_failures == 0
    assert status.previous_failure == ""


def test_shell_crash_degrades_without_erasing_data(tmp_path: Path) -> None:
    notes = _notes(tmp_path)
    service = RecoveryService(tmp_path / "recovery")
    status = service.inject(kind="shell", reason="shell stopped")

    assert status.state == "DEGRADED"
    assert status.shell_reduced is True
    assert "shell stopped" in status.explanation
    assert status.data_erased is False
    assert notes.read_text(encoding="utf-8") == "keep\n"


def test_model_crash_disables_that_model(tmp_path: Path) -> None:
    service = RecoveryService(tmp_path / "recovery")
    status = service.inject(
        kind="model", reason="model xai-default crashed", model_id="xai-default"
    )

    assert status.state == "DEGRADED"
    assert status.disabled_models == ["xai-default"]
    assert status.optional_models_enabled is True
    assert service.disabled_model_ids(
        [("mock-default", "mock"), ("local-default", "local"), ("xai-default", "xai")]
    ) == ["xai-default"]
    assert "model xai-default crashed" in status.explanation


def test_graphics_failure_reduces_the_shell(tmp_path: Path) -> None:
    service = RecoveryService(tmp_path / "recovery")
    status = service.inject(check="graphics", reason=CHECK_REASONS["graphics"])

    assert status.state == "DEGRADED"
    assert status.shell_reduced is True
    assert "graphics are unavailable" in status.explanation
    assert status.third_party_agents_enabled is True


def test_runaway_agent_enters_safe_mode(tmp_path: Path) -> None:
    notes = _notes(tmp_path)
    service = RecoveryService(tmp_path / "recovery")
    status = service.inject(kind="runaway", reason="", agent_id="plugin", ram_mb=9000, limit_mb=256)

    assert status.state == "SAFE_MODE"
    assert status.disabled_agents == ["plugin"]
    assert "plugin" in status.explanation
    assert "9000" in status.explanation
    assert service.disabled_agent_ids(["system", "plugin"]) == ["plugin"]
    assert notes.read_text(encoding="utf-8") == "keep\n"


def test_failed_update_is_explained_and_rollback_does_not_reinstall(tmp_path: Path) -> None:
    notes = _notes(tmp_path)
    updates = tmp_path / "updates"
    _update_state(updates, phase="installing", version="0.2.0")
    service = RecoveryService(tmp_path / "recovery", updates_dir=updates)
    status = service.assess()

    assert status.state == "RECOVERY"
    assert "is interrupted" in status.explanation
    assert status.os_reinstalled is False
    with pytest.raises(RecoveryRefused, match="rollback is not available"):
        service.rollback_update()
    assert notes.read_text(encoding="utf-8") == "keep\n"
    assert json.loads((updates / "state.json").read_text(encoding="utf-8"))["boot_slot"] == "A"


def test_staged_rollback_leaves_user_data(tmp_path: Path) -> None:
    notes = _notes(tmp_path)
    updates = tmp_path / "updates"
    _update_state(updates, phase="staged", version="0.2.0")
    service = RecoveryService(tmp_path / "recovery", updates_dir=updates)

    status = service.rollback_update()

    assert status.os_reinstalled is False
    assert status.data_erased is False
    assert notes.read_text(encoding="utf-8") == "keep\n"
    saved = json.loads((updates / "state.json").read_text(encoding="utf-8"))
    assert saved["boot_slot"] == "A"
    assert saved["pending_generation"] is None


def test_invalid_configuration_is_explained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "OMNE.toml"
    config.write_text('port = "nope"\n', encoding="utf-8")
    notes = tmp_path / "notes.txt"
    notes.write_text("keep\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert main(["--config", str(config), "recover", "explain"]) == 2

    captured = capsys.readouterr()
    assert "configuration is invalid" in captured.out
    assert "normal startup failed" in captured.out
    assert config.read_text(encoding="utf-8") == 'port = "nope"\n'
    assert notes.read_text(encoding="utf-8") == "keep\n"


def test_erase_and_reinstall_are_refused(tmp_path: Path) -> None:
    notes = _notes(tmp_path)
    service = RecoveryService(tmp_path / "recovery", updates_dir=tmp_path / "updates")

    with pytest.raises(RecoveryRefused, match="erase"):
        service.execute("erase")
    with pytest.raises(RecoveryRefused, match="reinstall"):
        service.execute("reinstall")

    assert notes.read_text(encoding="utf-8") == "keep\n"
    assert not (tmp_path / "recovery" / "journal.json").exists()


def test_normal_stays_refused_while_storage_is_unusable(tmp_path: Path) -> None:
    notes = _notes(tmp_path)
    service = RecoveryService(tmp_path / "recovery")
    service.inject(check="storage", reason=CHECK_REASONS["storage"])

    with pytest.raises(RecoveryRefused, match="storage is not usable"):
        service.request_normal()

    assert service.assess().state == "RECOVERY"
    assert notes.read_text(encoding="utf-8") == "keep\n"


@pytest.mark.parametrize("name", CHECKS)
def test_each_health_check_can_fail(tmp_path: Path, name: CheckName) -> None:
    service = RecoveryService(tmp_path / "recovery")
    status = service.inject(check=name, reason=CHECK_REASONS[name])

    assert status.state != "NORMAL"
    assert CHECK_REASONS[name] in status.explanation
    assert any(item.name == name and item.ok is False for item in status.checks)
    if name in {"graphics", "network"}:
        assert status.state == "DEGRADED"
    else:
        assert status.state == "RECOVERY"


def test_linux_fixture_is_read_without_starting_units(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "host"
    _linux_fixture(root)
    calls: list[list[str]] = []

    def spy(args: list[str], **kwargs: object) -> None:
        del kwargs
        calls.append(list(args))
        raise AssertionError(args)

    monkeypatch.setattr("omne.recovery.probe.subprocess.run", spy)
    report = LinuxRecoveryProbe(root).probe(data_dir=tmp_path, port=8787)

    assert calls == []
    assert all(item.ok for item in report.checks)
    _linux_fixture(root, graphics="unavailable", shell="failed")
    failed = LinuxRecoveryProbe(root).probe(data_dir=tmp_path, port=8787)
    graphics = next(item for item in failed.checks if item.name == "graphics")
    assert graphics.ok is False
    assert failed.shell_failed is True
    source = Path("omne/recovery/probe.py").read_text(encoding="utf-8")
    assert "systemctl start" not in source
    assert "apt-get" not in source
    assert "is-active" in source


def test_safe_mode_keeps_diagnostics_and_the_mock_model(tmp_path: Path) -> None:
    notes = tmp_path / "memory" / "notes.txt"
    notes.parent.mkdir(parents=True)
    notes.write_text("keep\n", encoding="utf-8")
    RecoveryService(tmp_path / "memory" / "recovery").enter_safe("operator requested safe mode")
    omne = build_OMNE(runtime_settings(tmp_path))
    status, body = route_get(omne, "/recovery", {})
    posted, payload = route_post(omne, "/recovery", {"command": "reinstall"})

    assert status.value == 200
    record = body["recovery"]
    assert isinstance(record, dict)
    assert record["state"] == "SAFE_MODE"
    assert record["diagnostics_available"] is True
    assert record["data_erased"] is False
    assert record["os_reinstalled"] is False
    assert record["optional_models_enabled"] is False
    enabled = {str(agent["id"]): agent["enabled"] for agent in omne.agent_views()}
    assert enabled["system"] is True
    assert enabled["coding"] is True
    model_ids = {str(model["id"]) for model in omne.model_views()}
    assert "mock-default" in model_ids
    assert "xai-default" not in model_ids
    assert "local-default" not in model_ids
    assert posted.value == 404
    assert payload["error"] == "not_found"
    assert notes.read_text(encoding="utf-8") == "keep\n"
    kinds = [event.type for event in omne.list_events()]
    assert "recovery.assessed" in kinds


def test_recovery_commands_report_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OMNE_ENVIRONMENT", "testing")
    assert main(["recover"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["state"] == "NORMAL"
    assert status["data_erased"] is False
    assert status["os_reinstalled"] is False
    assert main(["recover", "explain"]) == 0
    assert "startup checks passed" in capsys.readouterr().out


def _notes(tmp_path: Path) -> Path:
    path = tmp_path / "notes.txt"
    path.write_text("keep\n", encoding="utf-8")
    return path


def _update_state(directory: Path, *, phase: str, version: str) -> None:
    directory.mkdir(parents=True)
    (directory / "state.json").write_text(
        json.dumps(
            {
                "boot_slot": "A",
                "booted_generation": "boot-1",
                "pending_generation": "pending-1",
                "generations": [
                    {
                        "id": "boot-1",
                        "channel": "omne",
                        "version": "0.1.0",
                        "phase": "installed",
                        "slot": "A",
                        "reboot_required": False,
                        "packages": ["omne-core"],
                        "booted": True,
                    },
                    {
                        "id": "pending-1",
                        "channel": "omne",
                        "version": version,
                        "phase": phase,
                        "slot": "B",
                        "reboot_required": False,
                        "packages": ["omne-core"],
                        "booted": False,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def _linux_fixture(root: Path, **overrides: str) -> None:
    values = {
        "version": "Linux version 6.8",
        "comm": "systemd\n",
        "service": "active",
        "shell": "active",
        "core": "up",
        "ipc": "up",
        "graphics": "ready",
        "network": "ready",
        "storage": "ready",
    }
    values.update(overrides)
    (root / "proc" / "1").mkdir(parents=True, exist_ok=True)
    (root / "run" / "omne").mkdir(parents=True, exist_ok=True)
    (root / "proc" / "version").write_text(values["version"], encoding="utf-8")
    (root / "proc" / "1" / "comm").write_text(values["comm"], encoding="utf-8")
    omne = root / "run" / "omne"
    (omne / "omne-core.state").write_text(values["service"], encoding="utf-8")
    (omne / "omne-shell.state").write_text(values["shell"], encoding="utf-8")
    (omne / "core.state").write_text(values["core"], encoding="utf-8")
    (omne / "ipc.state").write_text(values["ipc"], encoding="utf-8")
    (omne / "graphics.state").write_text(values["graphics"], encoding="utf-8")
    (omne / "network.state").write_text(values["network"], encoding="utf-8")
    (omne / "storage.state").write_text(values["storage"], encoding="utf-8")
