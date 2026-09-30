"""A machine install keeps the operator after reboot and does not format a disk."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.conftest import ROOT

from core.api.runtime import build_OMNE
from core.orchestrator.task import TaskStatus
from omne.display.providers.mock import DESKTOP_URI
from omne.install.machine import InstallError, boot_settings, install_machine


def test_install_refuses_the_host_disk(tmp_path: Path) -> None:
    for dest in (
        Path("/"),
        Path("/boot"),
        Path("/boot/omne"),
        Path("/efi"),
        Path("/dev/sda"),
        Path("/proc"),
        Path("/sys"),
        Path("/run/omne"),
        ROOT,
        ROOT / "build",
    ):
        with pytest.raises(InstallError, match="refusing"):
            install_machine(ROOT, dest)
        assert not (tmp_path / "machine").exists()
    assert not Path("/boot/omne").exists()


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    dest = tmp_path / "machine"
    record = install_machine(ROOT, dest, dry_run=True)

    assert record["persistent_state"] is True
    assert record["volatile_state"] is False
    assert record["nvidia_boot_dependency"] is False
    assert record["disk_format"] is False
    assert record["bootloader_written"] is False
    assert record["block_device"] is False
    assert not dest.exists()


def test_installed_machine_keeps_the_operator_after_reboot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    root = tmp_path / "machine"
    install_machine(ROOT, root)
    installed = json.loads((root / "etc" / "omne" / "install.json").read_text(encoding="utf-8"))
    config = (root / "etc" / "omne" / "OMNE.toml").read_text(encoding="utf-8")
    session = (root / "usr" / "bin" / "omne-session").read_text(encoding="utf-8")
    shell = (root / "usr" / "share" / "omne" / "shell" / "index.html").read_text(encoding="utf-8")
    wants = root / "etc" / "systemd" / "system" / "multi-user.target.wants"

    assert installed["nvidia_boot_dependency"] is False
    assert installed["persistent_state"] is True
    assert installed["disk_format"] is False
    assert 'model_route = "auto"' in config
    assert "nvapi-" not in config
    assert "api_key" not in config
    assert "surface=desktop" in session
    assert 'id="desktop"' in shell
    assert (wants / "omne.target").is_symlink()
    assert (wants / "omne-session.service").is_symlink()
    assert (wants / "omne-doctor.service").is_symlink()
    assert (root / "usr" / "bin" / "omne-prove").is_file()
    assert not (root / "boot").exists()
    assert "network.scan" in (
        root / "usr" / "lib" / "omne" / "agents" / "coding" / "agent.toml"
    ).read_text(encoding="utf-8")

    settings = boot_settings(root)
    assert settings.environment == "production"
    assert settings.model_route == "auto"
    assert settings.data_dir == root / "var" / "lib" / "omne" / "memory"
    assert settings.workspace_root == root / "var" / "lib" / "omne" / "workspace"
    notes = settings.workspace_root / "notes.txt"
    notes.write_text("kept\n", encoding="utf-8")

    first = build_OMNE(settings)
    read = first.execute_sync("read file notes.txt")
    child = next(item for item in first.list_tasks() if item.parent_task == read.id)
    mission = next(item for item in first.list_missions() if item.objective == read.objective)
    assert read.status is TaskStatus.COMPLETED
    assert child.observations[0]["tools"] == ["filesystem.read"]
    assert first.verification_view(child.id)["status"] == "PASS"
    assert all(
        event.payload.get("provider") == "mock"
        for event in first.list_events()
        if event.type == "model.completed"
    )

    install_machine(ROOT, root)
    assert notes.read_text(encoding="utf-8") == "kept\n"
    assert (root / "var" / "lib" / "omne" / "memory" / "missions.sqlite").is_file()

    second = build_OMNE(boot_settings(root))
    restored = second.get_mission(mission.id)
    restored_child = second.verification_view(child.id)
    display = second.execute_sync("inspect the display")
    display_child = next(item for item in second.list_tasks() if item.parent_task == display.id)
    scan = second.execute_sync("scan wifi")
    launch = second.execute_sync("launch application Files")

    assert restored.status.value == "COMPLETED"
    assert restored_child["status"] == "PASS"
    assert display.status is TaskStatus.COMPLETED
    assert display_child.observations[0]["tools"] == ["display.inspect"]
    assert display_child.observations[0]["outputs"][0]["output"]["surface"]["uri"] == DESKTOP_URI
    assert any(
        item["decision"]["tools"] == ["display.inspect"]
        for item in second.desktop_view()["activity"]
        if item["decision"]
    )
    assert any(
        event.type == "permission.granted" and event.tool_id == "network.scan"
        for event in second.list_events()
    )
    assert not any(event.type == "network.connected" for event in second.list_events())
    scan_child = next(item for item in second.list_tasks() if item.parent_task == scan.id)
    if scan.status is TaskStatus.COMPLETED:
        state = scan_child.observations[0]["outputs"][0]["output"]["state"]
        assert state["stack_commanded"] is False
    else:
        assert scan.status is TaskStatus.FAILED
        assert any("radio" in error.message for error in scan_child.errors)
    launch_child = next(item for item in second.list_tasks() if item.parent_task == launch.id)
    assert launch.status is TaskStatus.FAILED
    assert any("high-risk" in error.message for error in launch_child.errors)
    assert not any(event.type == "application.launched" for event in second.list_events())
    assert all(
        event.payload.get("provider") == "mock"
        for event in second.list_events()
        if event.type == "model.completed"
    )
