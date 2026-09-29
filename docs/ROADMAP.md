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

## Not done

The Linux base is Ubuntu 24.04 LTS. `omne-core`, `omne-shell`, and `omne-system` are Debian
packages, and `omne.target` starts them from `multi-user.target`. `scripts/linux/build-base.sh`
builds a minbase rootfs and does not install a kernel or a bootloader. Run it as root when
`debootstrap` is installed. This revision does not claim that rootfs was booted.

Phase 14 does not write `OMNE-OS.iso`. The script exits 2 when it is not root or when `debootstrap`
or `xorriso` is missing, and it still exits 2 when those tools exist because an ISO needs a kernel
and a bootloader.

Phase 15 does not boot a virtual machine. `scripts/linux/vm-boot.sh` exits 2 when the image or
`qemu-system-x86_64` is absent.

Phase 16, physical hardware installation, has not been started. Wayland and a custom session are not
part of this base.

The intelligence layer in this revision is the mission, world state, intent engine, decision engine,
capability registry, worker slots, context builder, verifier, trace ids, command classes, dry-run,
and event replay described in `docs/ARCHITECTURE.md`. Model weight loading, a galaxy animation, and
a bootable image are not implemented.
