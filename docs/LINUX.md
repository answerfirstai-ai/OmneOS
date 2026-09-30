# Linux base

Ubuntu 24.04 LTS (noble) is the development base. Debian packages install on that userspace and on
other systems that provide Python 3.12. Linux stays the kernel. This layer does not compile one. The
ISO and disk builders install Ubuntu's kernel and systemd-boot into an isolated image. They do not
change the host bootloader. See `docs/ISO_BUILD.md`.

```text
Ubuntu 24.04
    → omne-core, omne-shell, omne-system
    → systemd services
    → OMNE Shell
```

The pin lives in `system/linux/base`.

## Packages

`scripts/linux/build-packages.sh` builds three `all` packages with `dpkg-deb`.

| Package     | What it installs                                                                         |
| ----------- | ---------------------------------------------------------------------------------------- |
| omne-core   | `/usr/bin/OMNE`, `/etc/omne/OMNE.toml`, agents, model manifests, and `omne-core.service` |
| omne-shell  | The built shell in `/usr/share/omne/shell` and `omne-shell.service`                      |
| omne-system | `omne.target`, enabled from `multi-user.target`                                          |

`omne-core` depends on `python3 (>= 3.12)`. A normal package build also vendors the core and
pydantic under `/usr/lib/omne/python`. `--skip-runtime` leaves that tree out for layout tests.

The core service runs as the system user `omne`, reads `/etc/omne/OMNE.toml`, and binds to
`127.0.0.1:8787`. State is `/var/lib/omne`. The shell service starts after the core and serves
`127.0.0.1:4173`. Both units drop capabilities, use `SystemCallFilter=@system-service`, and keep
boot and credential paths inaccessible. `omne-agent` and `omne-app` are separate `nologin` users.
The target wants both services, so a boot reaches OMNE without a user launching it. Credentials use
the kernel keyring through `libkeyutils` and are not written into `OMNE.toml`. See
`docs/SECURITY_MODEL.md` and `docs/SECRETS.md`. Later package changes stay with apt and dpkg.
`omne.updates` checks a signed catalog and records a pending slot. It does not run `apt-get` on the
development host. See `docs/UPDATE_ARCHITECTURE.md`. Recovery reads Linux, systemd, and the OMNE
units and does not start them. Safe mode does not erase `/var/lib/omne`. See `docs/RECOVERY.md`.

`scripts/linux/install.sh` is still the user unit for a checkout. It is not the system install.

## Rootfs

`scripts/linux/build-base.sh` needs root and `debootstrap`. It builds an Ubuntu noble minbase,
installs `systemd` and `python3`, then installs the three packages. It refuses
`linux-image-generic`, `grub-pc`, `grub-efi-amd64`, and `ubuntu-desktop`. Ubuntu's own base files
include an empty `/boot` directory; the builder still rejects a kernel image and kernel modules. It
exits 2 when it is not root, when `debootstrap` is missing, or when a package is missing, and it
does not write the rootfs in those cases.

```bash
npm run build
bash scripts/linux/build-packages.sh --dest build/linux
sudo bash scripts/linux/build-base.sh --dest /var/tmp/omne-rootfs --packages build/linux
```

`--dry-run` prints the plan and writes nothing. `scripts/linux/stage-system.sh --dest DIR` writes
the same tree without packing it. Both refuse `/boot`.

## Boot

The machine firmware is UEFI. OMNE does not build a kernel. `scripts/linux/build-disk.sh` installs
Ubuntu's `linux-image-generic` and the initramfs that package generates, then writes a GPT disk:

```text
UEFI
    → systemd-boot
    → Ubuntu kernel
    → initramfs
    → systemd
    → omne-boot, OMNE Core, OMNE Shell
```

The disk installs `systemd-sysv`, so `/sbin/init` is systemd. `systemd-boot` is Ubuntu's
`systemd-boot-efi` package from universe. When the build machine cannot mount FAT, `mtools` writes
that EFI system partition. The bootloader waits zero seconds and loads one entry, titled OMNE. The
default target is `multi-user.target`. `ubuntu-desktop`, `gdm3`, `lightdm`, and `plymouth` are
refused, and `getty@tty1` and `serial-getty@ttyS0` are masked on the disk so a login prompt does not
replace the console. Ethernet matches `en*` and `eth*` and requests DHCP through systemd-networkd. A
link that stays down is reported as network down. OMNE does not replace that stack. `omne.network`
reads the interfaces, addresses, DNS, and routes systemd-networkd already published. A later image
can use iwd for Wi-Fi association and leave addressing with systemd-networkd, and only after an
explicit grant. This image does not scan a radio or write a network unit. See `docs/NETWORK.md`.
Audio on a later image is PipeWire with WirePlumber. OMNE reads that session and does not replace
it. This image does not open a microphone. See `docs/AUDIO_ARCHITECTURE.md`. Input chords are
configuration. The image does not grab the keyboard. See `docs/INPUT_ARCHITECTURE.md`. Storage is
the layout Linux already published. The image does not format a disk. See `docs/STORAGE.md`.
Installed applications are the desktop entries Linux already published. The image does not start
those programs from the application reader. See `docs/APPLICATIONS.md`. Browser automation is not
installed with the image. Playwright is documented and not imported. See `docs/BROWSER.md`. Process
inspection reads `/proc` and does not signal a running process. See `docs/PROCESSES.md`.

`omne-boot` is the tty1 program. It prints Hardware, Storage, Network, GPU, Core, and Models from
the live machine and from `GET /health` and `GET /models`. A check is printed only when that probe
succeeds. An unavailable GPU stays unavailable. `OMNE READY` requires hardware, storage, and the
core. Network, GPU, and models are shown either way.

```bash
sudo bash scripts/linux/build-disk.sh --rootfs /var/tmp/omne-rootfs --dest /var/tmp/OMNE-OS.img
bash scripts/linux/vm-boot.sh --dry-run /var/tmp/OMNE-OS.img
bash scripts/linux/vm-boot.sh --run /var/tmp/OMNE-OS.img
bash scripts/linux/vm-test.sh --iso /var/tmp/OMNE-OS.iso
```

`--dry-run` writes nothing and does not start QEMU. `--run` needs `qemu-system-x86_64` and OVMF.
`vm-test.sh` is the headless ISO boot test. It exits 0 only when the guest reaches the OMNE desktop.
See `docs/VM_TEST.md`. `scripts/linux/build-iso.sh` writes a bootable ISO in a temporary directory
when it is root on Ubuntu 24.04 x86-64. The build is described in `docs/ISO_BUILD.md`. The graphical
session is labwc, described in `docs/GRAPHICS_ARCHITECTURE.md`. The ISO installs labwc and does not
start it. A physical install is later.
