"""Linux installer, system packages, and image scripts."""

from __future__ import annotations

import os
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
    assert "Ubuntu 24.04" in result.stderr
    assert "xorriso" in result.stderr
    assert not (tmp_path / "OMNE-OS.iso").exists()
    assert not (ROOT / "OMNE-OS.iso").exists()


def test_iso_dry_run_writes_nothing(tmp_path: Path) -> None:
    dest = tmp_path / "OMNE-OS.iso"
    result = _run(["bash", "scripts/linux/build-iso.sh", "--dry-run", "--dest", str(dest)])

    assert result.returncode == 0
    assert "ubuntu 24.04 (noble)" in result.stdout
    assert "linux-image-generic" in result.stdout
    assert "systemd-boot" in result.stdout
    assert "labwc" in result.stdout
    assert "systemd-networkd" in result.stdout
    assert "recovery: included" in result.stdout
    assert "physical installation: not performed" in result.stdout
    assert "dry-run: no ISO was written" in result.stdout
    assert "validation passed" not in result.stdout
    assert "ISO written" not in result.stdout
    assert not dest.exists()


def test_iso_refuses_boot_and_block_devices(tmp_path: Path) -> None:
    boot = _run(["bash", "scripts/linux/build-iso.sh", "--dry-run", "--dest", "/boot/OMNE-OS.iso"])
    block = _run(["bash", "scripts/linux/build-iso.sh", "--dest", "/dev/sda"])
    source = _run(
        ["bash", "scripts/linux/build-iso.sh", "--dry-run", "--dest", str(ROOT / "OMNE-OS.iso")]
    )

    assert boot.returncode == 2
    assert "refusing" in boot.stderr
    assert block.returncode == 2
    assert "refusing" in block.stderr
    assert "no image was built" in block.stderr
    assert source.returncode == 2
    assert "source tree" in source.stderr
    assert not Path("/boot/OMNE-OS.iso").exists()
    assert not (tmp_path / "OMNE-OS.iso").exists()
    assert not (ROOT / "OMNE-OS.iso").exists()


def test_iso_detects_an_unsupported_system(tmp_path: Path) -> None:
    dest = tmp_path / "OMNE-OS.iso"
    env = os.environ.copy()
    env["OMNE_ISO_UNAME"] = "Windows_NT"
    result = subprocess.run(
        ["bash", "scripts/linux/build-iso.sh", "--dest", str(dest)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 2
    assert "no image was built" in result.stderr
    assert "Ubuntu 24.04" in result.stderr
    assert "container" in result.stderr.lower()
    assert "workflow_dispatch" in result.stderr
    assert not dest.exists()


def test_iso_script_stays_off_the_host_disk() -> None:
    text = (ROOT / "scripts/linux/build-iso.sh").read_text(encoding="utf-8")
    assert "mktemp" in text
    assert "systemd.volatile=state" in text
    assert "validate-iso.sh" in text
    assert "root=LABEL=${OMNE_ISO_VOLUME_ID}" in text
    assert "grub-install" not in text
    assert "of=/dev" not in text
    assert "bootctl install" not in text


def test_iso_config_pins_image_packages() -> None:
    text = (ROOT / "system/linux/iso.conf").read_text(encoding="utf-8")
    for name in ("labwc", "systemd-boot-efi", "systemd-sysv", "iproute2"):
        assert name in text
    for excluded in ("ubuntu-desktop", "gdm3", "lightdm", "plymouth", "grub-pc"):
        assert excluded not in text


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
    assert "omne-boot.service" in target
    assert "omne-diag.service" in target
    boot = (dest / "etc/systemd/system/omne-boot.service").read_text(encoding="utf-8")
    assert "Conflicts=getty@tty1.service" in boot
    assert "StandardOutput=journal+console" in boot
    assert "DeviceAllow=/dev/ttyS0 rw" in boot
    assert (dest / "usr/bin/omne-boot").is_file()
    assert (dest / "usr/bin/omne-diag").is_file()
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
    assert "./usr/bin/omne-boot" in system
    assert "./usr/bin/omne-diag" in system
    assert "./etc/systemd/system/omne-boot.service" in system
    assert "./etc/systemd/system/omne-diag.service" in system
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


def test_kernel_dry_run_does_not_install(tmp_path: Path) -> None:
    rootfs = tmp_path / "rootfs"
    result = _run(["bash", "scripts/linux/install-kernel.sh", "--dry-run", "--rootfs", str(rootfs)])

    assert result.returncode == 0
    assert "kernel package: linux-image-generic" in result.stdout
    assert "initramfs: initramfs-tools" in result.stdout
    assert "bootloader: not installed" in result.stdout
    assert "desktop: not installed" in result.stdout
    assert "no kernel was installed" in result.stdout
    assert not rootfs.exists()


def test_kernel_refuses_without_root(tmp_path: Path) -> None:
    rootfs = tmp_path / "rootfs"
    rootfs.mkdir()
    result = _run(["bash", "scripts/linux/install-kernel.sh", "--rootfs", str(rootfs)])

    assert result.returncode == 2
    assert "no kernel was installed" in result.stderr


def test_disk_dry_run_writes_nothing(tmp_path: Path) -> None:
    dest = tmp_path / "OMNE-OS.img"
    result = _run(
        [
            "bash",
            "scripts/linux/build-disk.sh",
            "--dry-run",
            "--dest",
            str(dest),
            "--rootfs",
            str(tmp_path),
        ]
    )

    assert result.returncode == 0
    assert "firmware: UEFI" in result.stdout
    assert "bootloader: systemd-boot" in result.stdout
    assert "kernel: linux-image-generic" in result.stdout
    assert "initramfs: initramfs-tools" in result.stdout
    assert "init: systemd" in result.stdout
    assert "default target: multi-user.target" in result.stdout
    assert "desktop: not installed" in result.stdout
    assert "no disk was written" in result.stdout
    assert not dest.exists()


def test_disk_script_installs_systemd_boot_and_init() -> None:
    text = (ROOT / "scripts/linux/build-disk.sh").read_text(encoding="utf-8")
    assert "systemd-sysv" in text
    assert "systemd-boot-efi" in text
    assert "universe" in text


def test_disk_refuses_without_root(tmp_path: Path) -> None:
    dest = tmp_path / "OMNE-OS.img"
    result = _run(
        ["bash", "scripts/linux/build-disk.sh", "--dest", str(dest), "--rootfs", str(tmp_path)]
    )

    assert result.returncode == 2
    assert "no disk was written" in result.stderr
    assert not dest.exists()


def test_disk_refuses_boot_directory() -> None:
    result = _run(["bash", "scripts/linux/build-disk.sh", "--dry-run", "--dest", "/boot/omne.img"])

    assert result.returncode == 2
    assert "refusing" in result.stderr
    assert not Path("/boot/omne.img").exists()


def test_vm_refuses_a_physical_disk(tmp_path: Path) -> None:
    image = tmp_path / "OMNE-OS.iso"
    image.write_bytes(b"not a disk")
    boot = _run(["bash", "scripts/linux/vm-boot.sh", "--dry-run", "/dev/sda"])
    test = _run(["bash", "scripts/linux/vm-test.sh", "--dry-run", "--iso", "/dev/nvme0n1"])
    source = (ROOT / "scripts/linux/vm-boot.sh").read_text(encoding="utf-8")

    assert boot.returncode == 2
    assert "refusing" in boot.stderr
    assert "no virtual machine was started" in boot.stderr
    assert test.returncode == 2
    assert "refusing" in test.stderr
    assert "file=/dev" not in source
    assert "of=/dev" not in source
    assert "virtio-vga" in source
    assert "virtio-net" in source
    assert "usb-kbd" in source
    assert "usb-tablet" in source
    assert "ich9-intel-hda" in source
    assert "-snapshot" in source
    assert not image.exists() or image.read_bytes() == b"not a disk"


def test_vm_test_dry_run_lists_checks_without_booting(tmp_path: Path) -> None:
    image = tmp_path / "OMNE-OS.iso"
    image.write_bytes(b"not an iso")
    result = _run(["bash", "scripts/linux/vm-test.sh", "--dry-run", "--iso", str(image)])

    assert result.returncode == 0
    assert "firmware: UEFI" in result.stdout
    assert "bootloader: systemd-boot" in result.stdout
    assert "desktop: not started" in result.stdout
    assert "iso-boots" in result.stdout
    assert "graphical-session" in result.stdout
    assert "omne-shell" in result.stdout
    assert "recovery" in result.stdout
    assert "ipc" in result.stdout
    assert "BLOCKED" in result.stdout
    assert "OS-ready requires the OMNE desktop" in result.stdout
    assert "dry-run: no virtual machine was started" in result.stdout
    assert "OS-ready: yes" not in result.stdout
    assert "starting virtual machine" not in result.stdout


def test_vm_dry_run_does_not_start(tmp_path: Path) -> None:
    image = tmp_path / "OMNE-OS.img"
    image.write_bytes(b"not a disk")
    result = _run(["bash", "scripts/linux/vm-boot.sh", "--dry-run", str(image)])

    assert result.returncode == 0
    assert "firmware: UEFI" in result.stdout
    assert "bootloader: systemd-boot" in result.stdout
    assert "desktop: not started" in result.stdout
    assert "no virtual machine was started" in result.stdout


def test_base_refuses_boot() -> None:
    result = _run(["bash", "scripts/linux/build-base.sh", "--dry-run", "--dest", "/boot/omne"])

    assert result.returncode == 2
    assert "refusing" in result.stderr
    assert not Path("/boot/omne").exists()


def _deb_listing(path: Path) -> str:
    result = _run(["dpkg-deb", "-c", str(path)])
    assert result.returncode == 0
    return result.stdout


def _iso_tools_ready() -> bool:
    return all(shutil.which(name) for name in ("xorriso", "mkfs.vfat", "mmd", "mcopy"))


def _tiny_iso(tmp_path: Path, *, include_omne: bool = True) -> Path:
    iso = tmp_path / "tiny.iso"
    script = r"""
set -euo pipefail
dest="$1"
include_omne="$2"
work="$(mktemp -d)"
mkdir -p "$work/root/boot" "$work/root/EFI/BOOT" "$work/root/omne" "$work/root/usr/bin" \
  "$work/root/usr/lib/systemd" "$work/root/usr/lib/omne/python/omne/recovery" \
  "$work/root/etc/systemd/network" "$work/root/etc/omne" \
  "$work/esp/EFI/BOOT" "$work/esp/loader/entries" "$work/esp/omne"
printf 'efi' > "$work/esp/EFI/BOOT/BOOTX64.EFI"
printf 'vmlinuz' > "$work/esp/omne/vmlinuz"
printf 'initrd' > "$work/esp/omne/initrd.img"
printf 'default omne.conf\n' > "$work/esp/loader/loader.conf"
printf 'title OMNE\n' > "$work/esp/loader/entries/omne.conf"
cp -a "$work/esp/EFI" "$work/root/"
cp -a "$work/esp/omne/." "$work/root/omne/"
if [[ "$include_omne" == "yes" ]]; then
  printf 'omne\n' > "$work/root/usr/bin/OMNE"
fi
printf 'labwc\n' > "$work/root/usr/bin/labwc"
printf 'systemd\n' > "$work/root/usr/lib/systemd/systemd"
printf 'DHCP=yes\n' > "$work/root/etc/systemd/network/20-omne-dhcp.network"
python3 - "$work/root/etc/omne/image.json" <<'PY'
import json
import sys

payload = {
    "arch": "amd64",
    "base_distribution": "ubuntu 24.04 (noble)",
    "bootloader": "systemd-boot",
    "build_id": "0123456789abcdef",
    "build_timestamp": "2026-09-30T00:00:00Z",
    "compositor": "labwc",
    "kernel_version": "6.8.0",
    "name": "OMNE OS",
    "physical_install": False,
    "version": "0.1.0",
}
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY
cp "$work/root/etc/omne/image.json" "$dest.json"
printf 'recovery\n' > "$work/root/usr/lib/omne/python/omne/recovery/service.py"
truncate -s 16M "$work/efiboot.img"
mkfs.vfat -F 16 -n ESP "$work/efiboot.img" >/dev/null
export MTOOLS_SKIP_CHECK=1
mmd -i "$work/efiboot.img" ::EFI ::EFI/BOOT ::loader ::loader/entries ::omne
mcopy -i "$work/efiboot.img" "$work/esp/EFI/BOOT/BOOTX64.EFI" ::EFI/BOOT/BOOTX64.EFI
mcopy -i "$work/efiboot.img" "$work/esp/omne/vmlinuz" ::omne/vmlinuz
mcopy -i "$work/efiboot.img" "$work/esp/omne/initrd.img" ::omne/initrd.img
mcopy -i "$work/efiboot.img" "$work/esp/loader/loader.conf" ::loader/loader.conf
mcopy -i "$work/efiboot.img" "$work/esp/loader/entries/omne.conf" ::loader/entries/omne.conf
cp "$work/efiboot.img" "$work/root/boot/efiboot.img"
xorriso -as mkisofs -R -J -V OMNE -o "$dest" -e boot/efiboot.img -no-emul-boot \
  -append_partition 2 0xef "$work/root/boot/efiboot.img" "$work/root"
sha256sum "$dest" > "$dest.sha256"
rm -rf "$work"
"""
    flag = "yes" if include_omne else "no"
    result = subprocess.run(
        ["bash", "-c", script, "bash", str(iso), flag],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return iso


def test_validate_iso_rejects_files_that_are_not_images(tmp_path: Path) -> None:
    missing = _run(["bash", "scripts/linux/validate-iso.sh", str(tmp_path / "missing.iso")])
    empty = tmp_path / "empty.iso"
    empty.write_bytes(b"")
    empty_result = _run(["bash", "scripts/linux/validate-iso.sh", str(empty)])
    random = tmp_path / "random.iso"
    random.write_bytes(b"not an iso")
    random_result = _run(["bash", "scripts/linux/validate-iso.sh", str(random)])

    assert missing.returncode == 2
    assert "missing" in missing.stderr
    assert empty_result.returncode == 2
    assert "empty" in empty_result.stderr
    assert random_result.returncode == 2
    assert "magic" in random_result.stderr


def test_validate_iso_checks_structure_and_refuses_a_tiny_os_image(tmp_path: Path) -> None:
    if not _iso_tools_ready():
        pytest.skip("xorriso or mtools is not installed")
    iso = _tiny_iso(tmp_path)
    structure = _run(["bash", "scripts/linux/validate-iso.sh", str(iso)])
    operating_system = _run(["bash", "scripts/linux/validate-iso.sh", "--os", str(iso)])
    broken = iso.with_name("broken.iso")
    broken.write_bytes(iso.read_bytes())
    digest = "0" * 64 + "  " + str(broken) + "\n"
    (tmp_path / "broken.iso.sha256").write_text(digest, encoding="utf-8")
    checksum = _run(["bash", "scripts/linux/validate-iso.sh", str(broken)])
    incomplete_dir = tmp_path / "incomplete"
    incomplete_dir.mkdir()
    incomplete = _tiny_iso(incomplete_dir, include_omne=False)
    missing_omne = _run(["bash", "scripts/linux/validate-iso.sh", str(incomplete)])

    assert structure.returncode == 0, structure.stderr
    assert "validation passed" in structure.stdout
    assert operating_system.returncode == 2
    assert "kernel image is too small" in operating_system.stderr
    assert "validation passed" not in operating_system.stdout
    assert checksum.returncode == 2
    assert "checksum does not match" in checksum.stderr
    assert missing_omne.returncode == 2
    assert "missing path: /usr/bin/OMNE" in missing_omne.stderr
