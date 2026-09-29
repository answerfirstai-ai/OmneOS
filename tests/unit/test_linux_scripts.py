"""Linux installer, system packages, and image scripts."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from tests.conftest import ROOT

from core.config.settings import load_settings


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
    unit = prefix / "share" / "systemd" / "user" / "OMNE-core.service"
    assert unit.is_file()
    assert "bootloader" in result.stdout
    assert not Path("/boot/OMNE").exists()


def test_iso_script_does_not_create_an_image(tmp_path: Path) -> None:
    result = _run(["bash", "scripts/linux/build-iso.sh"])

    assert result.returncode == 2
    assert "no image was built" in result.stderr
    assert not (tmp_path / "OMNE-OS.iso").exists()
    assert not (ROOT / "OMNE-OS.iso").exists()


def test_vm_script_does_not_start_a_machine(tmp_path: Path) -> None:
    result = _run(["bash", "scripts/linux/vm-boot.sh", str(tmp_path / "OMNE-OS.iso")])

    assert result.returncode == 2
    assert "no virtual machine was started" in result.stderr


def test_system_config_is_local_production() -> None:
    settings = load_settings(config_path=ROOT / "system" / "linux" / "OMNE.toml")

    assert settings.environment == "production"
    assert settings.execution_mode == "production"
    assert settings.host == "127.0.0.1"
    assert settings.workspace_root == Path("/var/lib/omne/workspace")
    assert settings.data_dir == Path("/var/lib/omne/memory")
    assert settings.agents_dir == Path("/usr/lib/omne/agents")
    assert settings.models_dir == Path("/usr/lib/omne/models/manifests")
    assert "http://127.0.0.1:4173" in settings.cors_origins


def _shell_bundle(tmp_path: Path) -> Path:
    shell = tmp_path / "shell"
    (shell / "dist").mkdir(parents=True)
    (shell / "index.html").write_text("<!doctype html><title>OMNE OS</title>\n", encoding="utf-8")
    (shell / "styles.css").write_text("body{}\n", encoding="utf-8")
    (shell / "dist" / "main.js").write_text("export {}\n", encoding="utf-8")
    return shell


def test_stage_refuses_boot(tmp_path: Path) -> None:
    result = _run(
        [
            "bash",
            "scripts/linux/stage-system.sh",
            "--dest",
            "/boot/omne",
            "--shell-dir",
            str(_shell_bundle(tmp_path)),
        ]
    )

    assert result.returncode == 2
    assert "refusing" in result.stderr
    assert not Path("/boot/omne").exists()


def test_stage_requires_the_shell_bundle(tmp_path: Path) -> None:
    empty = tmp_path / "empty-shell"
    empty.mkdir()
    result = _run(
        [
            "bash",
            "scripts/linux/stage-system.sh",
            "--dest",
            str(tmp_path / "tree"),
            "--package",
            "shell",
            "--shell-dir",
            str(empty),
        ]
    )

    assert result.returncode == 2
    assert "shell bundle is missing" in result.stderr
    assert not (tmp_path / "tree").exists()


def test_stage_places_services_on_the_ubuntu_base(tmp_path: Path) -> None:
    dest = tmp_path / "tree"
    result = _run(
        [
            "bash",
            "scripts/linux/stage-system.sh",
            "--dest",
            str(dest),
            "--shell-dir",
            str(_shell_bundle(tmp_path)),
        ]
    )

    assert result.returncode == 0
    assert "ubuntu 24.04 (noble)" in result.stdout
    assert "no kernel and no bootloader" in result.stdout
    core = (dest / "etc/systemd/system/omne-core.service").read_text(encoding="utf-8")
    shell = (dest / "etc/systemd/system/omne-shell.service").read_text(encoding="utf-8")
    target = (dest / "etc/systemd/system/omne.target").read_text(encoding="utf-8")
    assert "User=omne" in core
    assert "OMNE_CONFIG=/etc/omne/OMNE.toml" in core
    assert "%h" not in core
    assert "--bind 127.0.0.1 4173" in shell
    assert "Requires=omne-core.service" in shell
    assert "WantedBy=multi-user.target" in target
    assert (dest / "usr/lib/omne/agents/coding/agent.toml").is_file()
    assert (dest / "usr/lib/omne/models/manifests/mock-default.toml").is_file()
    assert (dest / "usr/share/omne/shell/dist/main.js").is_file()
    assert (dest / "usr/lib/omne/base").read_text(encoding="utf-8").find(
        "OMNE_BASE_CODENAME=noble"
    ) >= 0
    assert not (dest / "boot").exists()


def test_package_dry_run_writes_nothing(tmp_path: Path) -> None:
    dest = tmp_path / "debs"
    result = _run(["bash", "scripts/linux/build-packages.sh", "--dry-run", "--dest", str(dest)])

    assert result.returncode == 0
    assert "omne-core omne-shell omne-system" in result.stdout
    assert "no packages were built" in result.stdout
    assert not dest.exists()


def test_packages_are_services_without_a_kernel(tmp_path: Path) -> None:
    if shutil.which("dpkg-deb") is None:
        pytest.skip("dpkg-deb is not installed")
    dest = tmp_path / "debs"
    result = _run(
        [
            "bash",
            "scripts/linux/build-packages.sh",
            "--dest",
            str(dest),
            "--shell-dir",
            str(_shell_bundle(tmp_path)),
            "--skip-runtime",
        ]
    )

    assert result.returncode == 0, result.stderr
    names = sorted(path.name for path in dest.glob("*.deb"))
    assert names == [
        "omne-core_0.1.0_all.deb",
        "omne-shell_0.1.0_all.deb",
        "omne-system_0.1.0_all.deb",
    ]
    core = _deb_listing(dest / names[0])
    shell = _deb_listing(dest / names[1])
    system = _deb_listing(dest / names[2])
    assert "./usr/bin/OMNE" in core
    assert "./etc/systemd/system/omne-core.service" in core
    assert "./boot/" not in core
    assert "./usr/lib/omne/python/" not in core
    assert "./usr/share/omne/shell/dist/main.js" in shell
    assert "./etc/systemd/system/omne-shell.service" in shell
    assert "./etc/systemd/system/omne.target" in system
    info = _run(["dpkg-deb", "-I", str(dest / names[2])]).stdout
    assert "omne-core (= 0.1.0)" in info
    assert "omne-shell (= 0.1.0)" in info
    control = tmp_path / "control"
    subprocess.run(
        ["dpkg-deb", "-e", str(dest / names[2]), str(control)],
        check=True,
        cwd=ROOT,
    )
    assert "systemctl enable omne.target" in (control / "postinst").read_text(encoding="utf-8")


def test_base_dry_run_writes_nothing(tmp_path: Path) -> None:
    dest = tmp_path / "rootfs"
    result = _run(["bash", "scripts/linux/build-base.sh", "--dry-run", "--dest", str(dest)])

    assert result.returncode == 0
    assert "ubuntu 24.04 (noble)" in result.stdout
    assert "install: systemd python3" in result.stdout
    assert "exclude: linux-image-generic grub-pc grub-efi-amd64 ubuntu-desktop" in result.stdout
    assert "kernel: not installed" in result.stdout
    assert "bootloader: not installed" in result.stdout
    assert "no rootfs was written" in result.stdout
    assert not dest.exists()


def test_base_refuses_without_root(tmp_path: Path) -> None:
    dest = tmp_path / "rootfs"
    result = _run(["bash", "scripts/linux/build-base.sh", "--dest", str(dest)])

    assert result.returncode == 2
    assert "no rootfs was written" in result.stderr
    assert not dest.exists()


def test_base_refuses_boot() -> None:
    result = _run(["bash", "scripts/linux/build-base.sh", "--dry-run", "--dest", "/boot/omne"])

    assert result.returncode == 2
    assert "refusing" in result.stderr
    assert not Path("/boot/omne").exists()


def _deb_listing(path: Path) -> str:
    result = _run(["dpkg-deb", "-c", str(path)])
    assert result.returncode == 0
    return result.stdout
