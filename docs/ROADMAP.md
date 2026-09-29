# Roadmap

## Implemented

| Phase | What is in this revision                                          |
| ----- | ----------------------------------------------------------------- |
| 1     | Configuration, logging, health service, shell, CI                 |
| 2     | Tasks, events, planner, executor, `jarvis execute`                |
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

## Not done

Phase 14 does not write `JARVIS-OS.iso`. The script exits 2 when it is not root or when
`debootstrap` or `xorriso` is missing, and it still exits 2 when those tools exist because this
revision does not download a base image.

Phase 15 does not boot a virtual machine. `scripts/linux/vm-boot.sh` exits 2 when the image or
`qemu-system-x86_64` is absent.

Phase 16, physical hardware installation, has not been started.
