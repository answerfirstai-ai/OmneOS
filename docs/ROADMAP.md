# Roadmap

## Implemented

| Phase | What is in this revision                                          |
| ----- | ----------------------------------------------------------------- |
| 1     | Configuration, logging, health service, shell, CI                 |
| 2     | Tasks, events, planner, executor, `OMNE execute`                  |
| 3     | Filesystem, terminal, process, system, git, and browser tools     |
| 4     | Permission policy, confirmation, audit, fail-closed evaluator     |
| 5     | Mock, xAI, and local providers, registry, and router              |
| 6     | Agent manifests, registry, lifecycle, and the four default agents |
| 7     | Scoped SQLite memory and access checks                            |
| 8     | Host telemetry, allocation, and model-cache metadata              |
| 9     | Dependency scheduling, bounded recovery, and result aggregation   |
| 10    | Desktop shell with launcher, monitors, and notifications          |
| 11    | Character state driven by health, voice, and task status          |
| 12    | Voice status that stays silent without permission and a provider  |
| 13    | User systemd unit, installer, and health command                  |
| 14    | Image script that exits when it cannot build                      |
| 15    | VM script that exits when no image is present                     |
| —     | Missions, world state, intent, decisions, workers, verification   |
| —     | Ubuntu 24.04 base, system packages, and `omne.target`             |
| —     | UEFI systemd-boot disk, Ubuntu kernel, and the OMNE console       |
| —     | Display providers: mock, and labwc diagnostics on Linux           |

## Not done

The Linux base is Ubuntu 24.04 LTS. `omne-core`, `omne-shell`, and `omne-system` are Debian
packages, and `omne.target` starts them from `multi-user.target`. `scripts/linux/build-base.sh`
builds a minbase rootfs and does not install a kernel or a bootloader. `scripts/linux/build-disk.sh`
adds Ubuntu's kernel, initramfs, and systemd-boot. The console program is `omne-boot`. No display
manager is installed.

Phase 14 does not write `OMNE-OS.iso`. The script exits 2. The bootable artifact is the UEFI disk
from `scripts/linux/build-disk.sh`.

Phase 15 starts a virtual machine only with `scripts/linux/vm-boot.sh --run` when the disk, QEMU,
and OVMF are all present. Without them it exits 2 and does not start QEMU.

Phase 16, physical hardware installation, has not been started. `omne.display` can report whether
labwc, DRM, a render node, a connected monitor, and an input device are present. It does not start a
Wayland session. `omne.windowing` records windows and workspaces for that session and does not
command labwc. `omne.hardware` reads Linux device state and does not configure it. `omne.network`
reads the Linux network stack and does not replace systemd-networkd. `omne.audio` reads the Linux
audio stack and does not open a microphone. `omne.input` reads configured shortcuts and published
keyboards and mice and does not read the keyboard stream. `omne.storage` reads disks and mounts and
does not format them. `omne.applications` reads desktop entries and does not start a shell.
`omne.browser` separates the browser application from automation, research, and rendering, and it
does not import Playwright. `omne.processes` reads the process table and does not signal a protected
process. The shell is still the web desktop. `docs/GRAPHICS_ARCHITECTURE.md` lists what a VM needs
before that session can launch. `docs/WINDOWING.md` describes the window record. `docs/NETWORK.md`
describes the network read. `docs/AUDIO_ARCHITECTURE.md` describes the audio read and the later
voice path. `docs/INPUT_ARCHITECTURE.md` describes the shortcut configuration and the closed key
stream. `docs/STORAGE.md` describes the disk read and the path classes. `docs/APPLICATIONS.md`
describes the application lookup. `docs/BROWSER.md` describes the four browser layers and the
Playwright dependency. `docs/PROCESSES.md` describes the process table and the closed host signal
path. `docs/WORKERS.md` describes agent definitions and in-memory workers.

The intelligence layer in this revision is the mission, world state, intent engine, decision engine,
capability registry, worker slots, context builder, verifier, trace ids, command classes, dry-run,
and event replay described in `docs/ARCHITECTURE.md`. Model weight loading and a galaxy animation
are not implemented. An ISO is not produced.
