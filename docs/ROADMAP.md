# Roadmap

## Implemented

| Phase | What is in this revision                                                         |
| ----- | -------------------------------------------------------------------------------- |
| 1     | Configuration, logging, health service, shell, CI                                |
| 2     | Tasks, events, planner, executor, `OMNE execute`                                 |
| 3     | Filesystem, terminal, process, system, git, and browser tools                    |
| 4     | Permission policy, confirmation, audit, fail-closed evaluator                    |
| 5     | Mock, xAI, and local providers, registry, and router                             |
| 6     | Agent manifests, registry, lifecycle, and the four default agents                |
| 7     | Scoped SQLite memory and access checks                                           |
| 8     | Host telemetry, allocation, and model-cache metadata                             |
| 9     | Dependency scheduling, bounded recovery, and result aggregation                  |
| 10    | Desktop shell with launcher, monitors, and notifications                         |
| 11    | Character state driven by health, voice, and task status                         |
| 12    | Voice status that stays silent without permission and a provider                 |
| 13    | User systemd unit, installer, and health command                                 |
| 14    | UEFI ISO with systemd-boot, the Ubuntu kernel, and OMNE                          |
| 15    | VM script that exits when no image is present                                    |
| —     | Missions, world state, intent, decisions, workers, verification                  |
| —     | Ubuntu 24.04 base, system packages, and `omne.target`                            |
| —     | UEFI systemd-boot disk, Ubuntu kernel, and the OMNE console                      |
| —     | Display providers: mock, and labwc diagnostics on Linux                          |
| —     | Security profiles for system, core, agent, worker, model, shell, and application |
| —     | Scoped secrets for models, APIs, browsers, networks, applications, and services  |
| —     | Signed update catalogs, pending slots, and rollback without host installation    |
| —     | Recovery states, safe mode, and startup failure explanations                     |

## Not done

The Linux base is Ubuntu 24.04 LTS. `omne-core`, `omne-shell`, and `omne-system` are Debian
packages, and `omne.target` starts them from `multi-user.target`. `scripts/linux/build-base.sh`
builds a minbase rootfs and does not install a kernel or a bootloader. `scripts/linux/build-disk.sh`
adds Ubuntu's kernel, initramfs, and systemd-boot. Power reaches OMNE login, then the user session
starts OMNE Core, the shell, and the desktop. `omne-boot` remains the checklist. No display manager
is installed, and a terminal is not the login.

Phase 14 writes `OMNE-OS.iso` from `scripts/linux/build-iso.sh` on Ubuntu 24.04 x86-64 as root. The
script exits 2 when that environment is not present, and it does not install the image. See
`docs/ISO_BUILD.md`. The UEFI disk from `scripts/linux/build-disk.sh` remains a separate artifact.

Phase 15 boots the ISO in QEMU with OVMF, a virtual disk, virtio-net, virtio-vga, USB input, a null
audio device, a serial log, and snapshots. `scripts/linux/vm-test.sh` is headless. It exits 0 only
when every check passes, including the OMNE desktop. Without QEMU, OVMF, or an image it exits 2 and
does not start a virtual machine. See `docs/VM_TEST.md`.

Phase 16, physical hardware installation, has not been started. `omne.display` can report whether
labwc, DRM, a render node, a connected monitor, and an input device are present. It does not start a
Wayland session. `omne.windowing` records windows and workspaces for that session and does not
command labwc. `omne.hardware` reads Linux device state, derives a capability registry from that
read, and does not configure it. `omne.network` reads the Linux network stack and does not replace
systemd-networkd. `omne.audio` reads the Linux audio stack and does not open a microphone.
`omne.input` reads configured shortcuts and published keyboards and mice and does not read the
keyboard stream. `omne.storage` reads disks and mounts and does not format them. `omne.applications`
reads desktop entries and does not start a shell. `omne.browser` separates the browser application
from automation, research, and rendering, and it does not import Playwright. `omne.processes` reads
the process table and does not signal a protected process. The shell is still the web desktop.
`docs/GRAPHICS_ARCHITECTURE.md` lists what a VM needs before that session can launch.
`docs/WINDOWING.md` describes the window record. `docs/NETWORK.md` describes the network read.
`docs/AUDIO_ARCHITECTURE.md` describes the audio read and the later voice path.
`docs/INPUT_ARCHITECTURE.md` describes the shortcut configuration and the closed key stream.
`docs/STORAGE.md` describes the disk read and the path classes. `docs/APPLICATIONS.md` describes the
application lookup. `docs/BROWSER.md` describes the four browser layers and the Playwright
dependency. `docs/PROCESSES.md` describes the process table and the closed host signal path.
`docs/WORKERS.md` describes agent definitions and in-memory workers. `docs/MODELS.md` describes
resident model loading. `docs/SECURITY_MODEL.md` describes the profile boundary that sits behind the
permission evaluator. `docs/SECRETS.md` describes scoped credentials and the Linux keyring.
`docs/UPDATE_ARCHITECTURE.md` describes signed catalogs and apt plans. The development host is not
updated. `docs/RECOVERY.md` describes startup checks, safe mode, and recovery commands. User data is
not erased, and the operating system is not reinstalled.

The intelligence layer in this revision is the mission, world state, intent engine, decision engine,
capability registry, worker slots, context builder, verifier, trace ids, command classes, dry-run,
and event replay described in `docs/ARCHITECTURE.md`. This revision records the cortex cycle on each
mission and classifies the model route while the rule-based planner still builds the task graph.
Model loading uses a resident local runtime or
the mock engine and does not download weights. A galaxy animation is not implemented. The ISO build
is documented in `docs/ISO_BUILD.md` and is not a physical install.
