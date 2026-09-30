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

The scorer walks this dependency chain. A check that did not pass is `BLOCKED` when a dependency is
not `PASS`, instead of being counted as another root failure. `PASS`, `FAIL`, `SKIP`, and `BLOCKED`
are the statuses. `OS-ready: yes` still requires every check to be `PASS`.

1. The ISO boots (`root=LABEL=OMNE` on the kernel command line).
2. The Linux kernel starts.
3. systemd reaches `multi-user.target`.
4. systemd-networkd reaches `network.target` on virtio-net.
5. The ISO root and local filesystems mount.
6. `omne.target` starts OMNE Core.
7. The boot checklist reports `OMNE READY`.
8. IPC works (`ipc ok` after `GET /health`, or that health payload on the serial log).
9. A graphical session starts (`labwc running`, a labwc log line, or `graphical.target`).
10. Wayland reports `wayland display ready`.
11. The OMNE desktop is shown (`OMNE desktop ready`).
12. An application launch is recorded.
13. A safe agent task is recorded.
14. The model runtime reports ready.
15. Recovery mode is observed.
16. Ctrl-Alt-Delete makes systemd reach `reboot.target` and the kernel starts again.
17. ACPI power-off makes systemd reach `poweroff.target` and QEMU exits.

The test waits for `OMNE READY` or `OMNE NOT READY` before it reboots the guest. A started unit is
not treated as a healthy core, a visible shell, a launched application, or a finished agent task.
Recovery state is not inferred from a missing log line.

Each run writes `artifacts/vm-test/<run-id>/` with `summary.json` and one log per stage: `boot.log`,
`systemd.log`, `services.log`, `core.log`, `ipc.log`, `display.log`, `shell.log`,
`applications.log`, `agents.log`, `models.log`, and `recovery.log`. `summary.json` records `name`,
`status`, `exit_code`, `duration_ms`, `dependencies`, `error`, and `evidence` for every check, plus
`first_failure`.

## Commands

```bash
bash scripts/linux/vm-boot.sh --dry-run /var/tmp/OMNE-OS.iso
bash scripts/linux/vm-boot.sh --run --headless /var/tmp/OMNE-OS.iso
bash scripts/linux/vm-test.sh --dry-run --iso /var/tmp/OMNE-OS.iso
bash scripts/linux/vm-test.sh --iso /var/tmp/OMNE-OS.iso
```

`--dry-run` writes nothing and does not start QEMU. `--run` is headless unless `--display gtk` is
set. The test prints `OS-ready: yes` or `OS-ready: no`, leaves the serial log in its work directory
under `/var/tmp`, and writes the scored artifact under `artifacts/vm-test/`.

## CI

The default pull-request suite does not boot QEMU and does not require the ISO. A headless run on an
`ubuntu-24.04` runner is:

```bash
sudo bash scripts/linux/build-iso.sh --dest /var/tmp/OMNE-OS.iso
bash scripts/linux/vm-test.sh --iso /var/tmp/OMNE-OS.iso
```

Run that from `workflow_dispatch`. It needs `qemu-system-x86`, `qemu-utils`, and `ovmf`. KVM is used
when `/dev/kvm` is accessible. TCG is the fallback.
