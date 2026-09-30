# ISO build

`scripts/linux/build-iso.sh` writes an x86-64 UEFI ISO of OMNE OS. The image is produced only when
the command is root on Ubuntu 24.04 x86-64 and `scripts/linux/validate-iso.sh --os` accepts the
file. A missing tool, a non-Linux host, or a failed check exits 2 and leaves no ISO behind.

Physical installation is not part of this step. The script does not write the host disk, the host
`/boot`, or a block device.

## What the image contains

```text
UEFI
    → systemd-boot
    → Ubuntu linux-image-generic
    → initramfs (iso9660)
    → systemd
    → systemd-networkd
    → labwc (installed, not started)
    → omne-core, omne-shell, omne-system
    → OMNE recovery
```

The ISO 9660 volume id is `OMNE`. Firmware boots an El Torito FAT image that holds
`EFI/BOOT/BOOTX64.EFI`, the loader entry, `/omne/vmlinuz`, and `/omne/initrd.img`. That same image
is appended as an MBR partition of type `0xef`, which is how firmware reads an EFI system partition
larger than the El Torito catalog can size. The kernel command line mounts that volume read-only:

```text
root=LABEL=OMNE rootfstype=iso9660 ro rootwait systemd.unit=multi-user.target systemd.volatile=state
```

`systemd.volatile=state` puts `/var` on a tmpfs, so OMNE state and the recovery journal can be
written in memory and disappear on reboot. Journald storage is volatile for the same reason. The ISO
itself is not modified.

`labwc`, seatd, and the Mesa and libinput libraries are installed from Ubuntu. No display manager is
installed. `ubuntu-desktop`, `gdm3`, `lightdm`, `plymouth`, `grub-pc`, and `grub-efi-amd64` are
refused. `getty@tty1` and `serial-getty@ttyS0` are masked. The default target is
`multi-user.target`. Ethernet names `en*` and `eth*` request DHCP from systemd-networkd.

## Deterministic configuration

`system/linux/iso.conf` pins the architecture (`amd64`), the volume id (`OMNE`), the EFI system
partition size, and the package names. `system/linux/base` pins Ubuntu 24.04 (noble). The kernel
package is `linux-image-generic` and the initramfs tool is `initramfs-tools`.

The build id is the first 16 hex characters of the SHA-256 of that pin: OMNE version, base id, base
version, codename, architecture, kernel package name, initramfs package name, and the sorted package
list. The clock is not part of the build id.

Mirror package versions are whatever noble serves when the build runs. They are recorded in
`/etc/omne/image-packages.txt` and are not hashed into the build id. Two builds match byte for byte
only when the mirror is unchanged and `SOURCE_DATE_EPOCH` is set to the same value. xorriso honors
that epoch.

## Metadata and checksums

`/etc/omne/image.json` is copied to `DEST.json`. Both files carry:

| Field               | Meaning                                      |
| ------------------- | -------------------------------------------- |
| `version`           | OMNE version from `pyproject.toml`           |
| `build_id`          | 16 hex characters from the configuration pin |
| `base_distribution` | `ubuntu 24.04 (noble)`                       |
| `kernel_version`    | Version from the installed `vmlinuz-*` name  |
| `build_timestamp`   | UTC time, or `SOURCE_DATE_EPOCH` when set    |

`physical_install` is false. `DEST.sha256` is the SHA-256 of the ISO. The validator reads metadata
from the ISO and checks the sidecar and checksum against that file.

## Isolated build

The rootfs, package build, and FAT boot image stay under `/var/tmp/omne-iso.*`. Proc, sys, and dev
are unmounted before xorriso runs, so the ISO does not contain the host's live filesystems. apt runs
only inside that rootfs. The destination is required, must not already exist, and is refused under
`/boot`, `/efi`, `/dev`, a block device, or the source tree.

```bash
sudo bash scripts/linux/build-iso.sh --dest /var/tmp/OMNE-OS.iso
```

`--dry-run` prints the plan and writes nothing. Success is printed only after the ISO exists and
`validate-iso.sh --os` exits 0. A failed validation deletes the ISO, the checksum, and the sidecar.

## Validation

`scripts/linux/validate-iso.sh IMAGE` checks the ISO 9660 magic, the `OMNE` volume id, the El Torito
UEFI image, and the kernel, initramfs, systemd, networking, labwc, OMNE, recovery, and metadata
paths. `--os` also requires a kernel and initramfs of at least one megabyte each, a Linux kernel
version, a 16-character build id, a matching checksum, and a matching sidecar. The default test
suite builds a tiny ISO for the structure profile. That fixture is not an operating-system image,
and `--os` rejects it.

## Windows, containers, and CI

The script reads `uname`. A system other than Linux x86-64 exits 2, prints `no image was built`, and
prints the supported path. `OMNE_ISO_UNAME` and `OMNE_ISO_MACHINE`, when set, replace that detection
for tests. They do not skip root, the tool check, or validation.

On Windows, build inside a privileged Ubuntu 24.04 container:

```bash
docker run --privileged --rm -v "$PWD":/src -w /src ubuntu:24.04 \
  bash -c 'apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y debootstrap xorriso gdisk mtools dosfstools python3 python3-pip && bash scripts/linux/build-iso.sh --dest /var/tmp/OMNE-OS.iso'
```

The shell bundle must already exist, or Node must be added to that container so `npm run build` can
create it. A continuous-integration job uses an `ubuntu-24.04` runner with sudo and the same
command, started by `workflow_dispatch`. The image is not built on every pull request. The default
suite does not run debootstrap.

## Not in this step

The ISO is not copied to a disk. QEMU is not started. labwc is not started. User data is not erased,
and the operating system on the host is not reinstalled.
