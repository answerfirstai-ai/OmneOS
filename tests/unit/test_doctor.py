"""OMNE doctor reports the boot checks without calling NVIDIA."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.support import runtime_settings

from core.api.main import main
from core.api.runtime import build_OMNE
from core.models.providers.nvidia.provider import NvidiaProvider
from omne.doctor import diagnose, render

_SHELL = '<div class="desktop" id="desktop"></div>\n'


def test_doctor_command_prints_a_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)

    code = main(["doctor"])
    report = capsys.readouterr().out

    assert report.startswith("OMNE SYSTEM DIAGNOSTIC\n")
    assert "[PASS] Kernel\n" in report or "[FAIL] Kernel\n" in report
    assert "SYSTEM STATUS: READY\n" in report or "SYSTEM STATUS: NOT READY\n" in report
    assert "nvapi-" not in report
    if "SYSTEM STATUS: READY\n" in report:
        assert code == 0
    else:
        assert code == 1


def test_ready_machine_matches_the_boot_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    calls = {"probe": 0}

    async def _probe(self: NvidiaProvider, model: str) -> dict[str, object]:
        del self, model
        calls["probe"] += 1
        raise AssertionError("doctor must not call NVIDIA")

    monkeypatch.setattr(NvidiaProvider, "probe", _probe)
    root = tmp_path / "machine"
    _booted_machine(root)
    runtime = build_OMNE(runtime_settings(tmp_path))

    report = diagnose(
        runtime,
        root=root,
        data_dir=runtime_settings(tmp_path).data_dir,
        workspace=runtime_settings(tmp_path).workspace_root,
        shell_text=_SHELL,
    )
    text = render(report)

    assert calls["probe"] == 0
    assert text == _READY
    assert report.ready is True


def test_missing_graphics_keeps_the_machine_offline(tmp_path: Path) -> None:
    root = tmp_path / "machine"
    _booted_machine(root)
    drm = root / "sys" / "class" / "drm"
    for child in drm.iterdir():
        child.rmdir()
    drm.rmdir()
    runtime = build_OMNE(runtime_settings(tmp_path))
    settings = runtime_settings(tmp_path)

    report = diagnose(
        runtime,
        root=root,
        data_dir=settings.data_dir,
        workspace=settings.workspace_root,
        shell_text=_SHELL,
    )
    text = render(report)

    assert "[FAIL] Graphics\n" in text
    assert "SYSTEM STATUS: NOT READY\n" in text
    assert report.ready is False


def _booted_machine(root: Path) -> None:
    (root / "proc").mkdir(parents=True)
    (root / "proc" / "version").write_text("Linux version 6.8.0-omne\n", encoding="utf-8")
    (root / "proc" / "mounts").write_text("rootfs / ext4 rw 0 0\n", encoding="utf-8")
    eth = root / "sys" / "class" / "net" / "eth0"
    eth.mkdir(parents=True)
    (eth / "operstate").write_text("up\n", encoding="utf-8")
    (root / "sys" / "class" / "drm" / "card0").mkdir(parents=True)
    (root / "proc" / "asound").mkdir(parents=True)
    (root / "proc" / "asound" / "cards").write_text(
        " 0 [ICH9 ]: HDA-Intel - ICH9\n", encoding="utf-8"
    )
    devices = root / "proc" / "bus" / "input"
    devices.mkdir(parents=True)
    (devices / "devices").write_text("H: Handlers=sysrq kbd event0\n", encoding="utf-8")


_READY = """OMNE SYSTEM DIAGNOSTIC

[PASS] Kernel
[PASS] Filesystem
[PASS] Network
[PASS] Graphics
[PASS] Audio
[PASS] Input
[PASS] OMNE Core
[PASS] Cortex
[PASS] Memory
[PASS] Agent Runtime
[PASS] Model Router
[PASS] NVIDIA Provider
[PASS] Desktop
[PASS] Browser
[PASS] Recovery

SYSTEM STATUS: READY
"""
