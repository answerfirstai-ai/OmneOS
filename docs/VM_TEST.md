# VM test

`scripts/linux/vm-boot.sh` starts an OMNE image in QEMU. `scripts/linux/vm-test.sh` boots that
virtual machine headlessly and records whether it is OS-ready. Neither script opens a physical disk,
a block device, `/dev`, `/boot`, or `/efi`.

The test exits 0 only when every check passes. A build is not OS-ready unless the virtual machine
reaches the OMNE desktop. The current ISO boots to `multi-user.target` and does not start labwc, so
the desktop checks fail closed and the result stays `OS-ready: no`.

## Virtual hardware

| Device               | QEMU                                                          |
| -------------------- | ------------------------------------------------------------- |
| Firmware             | OVMF `OVMF_CODE_4M.fd`, a private variable-store copy         |
| CPU                  | x86-64, `q35`, KVM when it is usable and TCG otherwise        |
| ISO                  | CD-ROM, read-only                                             |
| Disk image           | virtio-blk                                                    |
| Extra disk           | qcow2 virtio-blk, created in the work directory               |
| Network              | user-mode virtio-net                                          |
| GPU                  | virtio-vga                                                    |
| Keyboard and pointer | USB keyboard and tablet                                       |
| Audio                | ICH9 HDA with a null host backend, so no microphone is opened |
| Serial               | a file in the work directory                                  |
| Monitor              | a Unix socket in the work directory                           |
| Snapshot             | `qemu -snapshot` plus a qcow2 snapshot named `baseline`       |

`--snapshot` keeps writes in a temporary overlay. The test checksums the ISO and the qcow2 before
and after the run. A changed backing file is a failure. The OVMF variable copy is allowed to change.
The host firmware files are not.

## Checks

1. The ISO boots (`root=LABEL=OMNE` on the kernel command line).
2. The Linux kernel starts.
3. systemd reaches `multi-user.target`.
4. `omne.target` starts OMNE Core.
5. The boot checklist reports `OMNE READY`.
6. A graphical session starts (`labwc` or `graphical.target`).
7. The OMNE desktop is shown.
8. systemd-networkd reaches `network.target` on virtio-net.
9. The ISO root and local filesystems mount.
10. An application launch is recorded.
11. A safe agent task is recorded.
12. The model runtime reports ready.
13. Ctrl-Alt-Delete makes systemd reach `reboot.target` and the kernel starts again.
14. ACPI power-off makes systemd reach `shutdown.target` and QEMU exits.
15. Recovery mode is observed.

A started unit is not treated as a healthy core, a visible shell, a launched application, or a
finished agent task. Recovery state is not inferred from a missing log line.

## Commands

```bash
bash scripts/linux/vm-boot.sh --dry-run /var/tmp/OMNE-OS.iso
bash scripts/linux/vm-boot.sh --run --headless /var/tmp/OMNE-OS.iso
bash scripts/linux/vm-test.sh --dry-run --iso /var/tmp/OMNE-OS.iso
bash scripts/linux/vm-test.sh --iso /var/tmp/OMNE-OS.iso
```

`--dry-run` writes nothing and does not start QEMU. `--run` is headless unless `--display gtk` is
set. The test prints `OS-ready: yes` or `OS-ready: no` and leaves the serial log in its work
directory under `/var/tmp`.

## CI

The default pull-request suite does not boot QEMU and does not require the ISO. A headless run on an
`ubuntu-24.04` runner is:

```bash
sudo bash scripts/linux/build-iso.sh --dest /var/tmp/OMNE-OS.iso
bash scripts/linux/vm-test.sh --iso /var/tmp/OMNE-OS.iso
```

Run that from `workflow_dispatch`. It needs `qemu-system-x86`, `qemu-utils`, and `ovmf`. KVM is used
when `/dev/kvm` is accessible. TCG is the fallback.
