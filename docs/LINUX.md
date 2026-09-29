# Linux base

Ubuntu 24.04 LTS (noble) is the development base. Debian packages install on that userspace and on
other systems that provide Python 3.12. Linux stays the kernel. This layer does not build one, and
it does not write a bootloader or an ISO.

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
`127.0.0.1:4173`. The target wants both services, so a boot reaches OMNE without a user launching
it.

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

## Later

A kernel, a bootloader, an ISO, a virtual machine, Wayland, and physical installation are later
layers. `scripts/linux/build-iso.sh` and `scripts/linux/vm-boot.sh` still exit 2.
