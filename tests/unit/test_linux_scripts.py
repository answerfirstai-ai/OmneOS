"""Linux installer and image scripts refuse unsafe or incomplete operations."""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests.conftest import ROOT


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_install_dry_run_refuses_boot() -> None:
    result = _run(["bash", "scripts/linux/install.sh", "--dry-run", "--prefix", "/boot"])

    assert result.returncode == 2
    assert "refusing" in result.stderr


def test_install_dry_run_writes_nothing(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    result = _run(["bash", "scripts/linux/install.sh", "--dry-run", "--prefix", str(prefix)])

    assert result.returncode == 0
    assert "dry-run" in result.stdout
    assert not prefix.exists()


def test_install_copies_user_unit_without_touching_boot(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    result = _run(["bash", "scripts/linux/install.sh", "--prefix", str(prefix)])

    assert result.returncode == 0
    unit = prefix / "share" / "systemd" / "user" / "jarvis-core.service"
    assert unit.is_file()
    assert "bootloader" in result.stdout
    assert not Path("/boot/jarvis").exists()


def test_iso_script_does_not_create_an_image(tmp_path: Path) -> None:
    result = _run(["bash", "scripts/linux/build-iso.sh"])

    assert result.returncode == 2
    assert "no image was built" in result.stderr
    assert not (tmp_path / "JARVIS-OS.iso").exists()
    assert not (ROOT / "JARVIS-OS.iso").exists()


def test_vm_script_does_not_start_a_machine(tmp_path: Path) -> None:
    result = _run(["bash", "scripts/linux/vm-boot.sh", str(tmp_path / "JARVIS-OS.iso")])

    assert result.returncode == 2
    assert "no virtual machine was started" in result.stderr
