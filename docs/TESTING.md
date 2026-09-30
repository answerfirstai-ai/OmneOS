# Testing

The default suite is offline. It does not call xAI, and it does not need a GPU, a browser binary,
Docker, QEMU, or root.

## Commands

```bash
source .venv/bin/activate
python -m ruff format --check core tests
python -m ruff check core tests
python -m mypy
python -m pytest
OMNE check

npm run format:check
npm run lint
npm run typecheck
npm test
npm run build
```

`bash scripts/testing/run-checks.sh` runs the same sequence.

## What the tests cover

Python:

- Settings, logging, health responses, CORS, and the serve process.
- Task transitions, events, and the scheduler.
- Filesystem boundaries, terminal confirmation, denied `sudo`, and an unconfigured browser.
- Permission allow, deny, confirm, audit, and fail-closed evaluation.
- Mock responses, xAI with a fake transport, a missing xAI key, and a local provider that does not
  connect.
- Routing to the mock model, live host telemetry, a reused snapshot, allocator decisions, and a
  model cache that does not load weights.
- Security profiles. Path traversal, privilege changes, pid 1, a closed network, protected files,
  and a claim above the profile ceiling are denied. A permissive permission result does not bypass
  the boundary. The worker sandbox covers boot, credentials, other homes, and raw devices, and it
  does not remove host `/dev/null`.
- Secrets. A credential addressed to one agent is not returned to another. Store, delete, and rotate
  stay with `core` and are denied in production. A registered value is absent from logs, events,
  traces, model context, and the SQLite task record. `XAI_API_KEY` still supplies development and is
  not copied into settings.
- Resource reservations. A fixed snapshot lets a 4-CPU, 4 GB worker run beside a GPU worker that
  needs 8 GB of VRAM. A second claim that does not fit waits until release. A request larger than
  the machine is denied and does not hold capacity. Unknown GPU, CPU, disk, and thermal readings
  stay unknown and do not name a vendor.
- `GET /desktop` returns the shell panels, including activity, confirmations, questions, and
  project, and does not include a compute sample.
- The same model prompt and cache context reuse one response. A later mission changes the world
  revision, so the same sentence is fetched again. Tool calls are not cached.
- Memory scope checks, provenance columns on older databases, agent manifests, and lifecycle edges.
- Missions, world-state revisions, intent, decisions, capabilities, workers, verification, traces,
  dry-run, command classes, and the new HTTP routes.
- Worker lifecycle, reuse, cancellation, failure, resource limits, and concurrent slot limits. A
  hundred workers stay in-process records.
- Model runtime. The mock engine loads, infers, streams, and cancels in memory. A local adapter with
  an empty URL does not connect. A configured adapter loads only names the runtime already lists and
  does not request a download. Memory and video-memory refusals leave the model unloaded. The health
  record does not invent a GPU vendor.
- Objective execution, dependency order, retry escalation, parallel work, and voice silence.
- The installer refusing `/boot`, the Ubuntu 24.04 system tree, the three system packages, the
  rootfs and UEFI disk builders refusing to write without root, and the ISO and VM scripts exiting
  without an image or a boot unless `vm-boot.sh --run` is passed.
- Display diagnostics. The testing API uses the mock provider and does not invent a monitor. The
  labwc provider reads a fixture filesystem and does not start a compositor.
- Window records. The testing API uses the mock window provider and starts with no windows. A grant
  is required to launch or close. The labwc window provider reads a fixture snapshot and does not
  run a compositor process. `POST /windowing` stays 404.
- Hardware discovery. The testing API uses an empty mock inventory. A Linux fixture supplies CPU,
  memory, GPU, VRAM, monitors, input, USB, PCI, storage, Ethernet, Wi-Fi, Bluetooth, audio, a
  camera, and power. Missing VRAM and unrelated thermal zones stay null. `POST /hardware` stays 404.
- Network reads. The testing API uses an empty mock session. A Linux fixture supplies Ethernet,
  loopback, Wi-Fi signal, DNS, and a default route. A password in a supplicant file is not part of
  the record. `POST /network` stays 404.
- Audio diagnostics. The testing API uses an empty mock session and keeps voice denied. A Linux
  fixture supplies a PipeWire dump with speakers, a microphone, Bluetooth audio, volume, mute,
  defaults, and a capture stream. An ALSA fixture leaves volume null. `POST /audio` stays 404.
- Input bindings. The testing API uses an empty mock device list and no configured chord. A Linux
  fixture supplies a keyboard and a mouse and drops the key bitmap. `POST /input` stays 404.
- Storage inspection. The testing API uses an empty mock layout. A Linux fixture supplies disks,
  partitions, mounts, read-only state, and removable media, and it does not gain files during the
  read. Filesystem tools deny traversal, symlinks, unauthorized paths, inaccessible paths, and
  protected system locations. `POST /storage` stays 404.
- Application lookup. The testing API uses Firefox and Files from the mock catalog. A Linux fixture
  reads desktop files, a process name, and a window snapshot, and it does not spawn a process. A
  shell `Exec` line is not launchable. `POST /applications` stays 404.
- Browser layers. The testing API uses a simulated Firefox session and does not fetch a page. A
  Linux fixture reads a browser desktop entry and a process name, and it does not spawn a process.
  `browser.open` stays unavailable when no browser command is configured. `POST /browser` stays 404.
- Process inspection. The testing API uses a mock table. A Linux fixture reads CPU time, RAM, the
  owner, parent, children, start time, and limits, and it does not signal a process. Command lines
  stay out of the snapshot. Protected and unowned processes cannot be stopped. `POST /processes`
  stays 404.

TypeScript:

- Health parsing, core URL selection, the windowing state parser, and the network, audio, input, and
  application launcher parsers.
- Character states, including a missing asset and mission-driven analyzing, verifying, and waiting.
- Environment state, lifecycle stages, mission inspection, permission copy, verification evidence,
  error summaries, notifications, graph layout, the current-mission graph, command copy, detail
  levels, resource lines, and keyboard shortcuts.
- Voice control staying disabled unless permission, provider, and hardware are all available.
- Task, agent, model, and notification lines, and one `/desktop` document.
- Desktop windows open, come to the front, hide, minimize, maximize, and stay within resize bounds.

## Not claimed

`scripts/linux/build-iso.sh` is tested for its refusal. It does not produce `OMNE-OS.iso`.
`scripts/linux/vm-boot.sh` does not start a virtual machine unless `--run` is passed.
`scripts/linux/build-base.sh` and `scripts/linux/build-disk.sh` are tested for their plans and for
refusing to write when not root. The boot checklist is tested against a fixture machine and a local
core: an unavailable GPU is not a check. Display launch readiness is tested against a fixture DRM
tree. Window commands are tested against the in-memory record and a snapshot file. Hardware
discovery is tested against a fixture sysfs tree. Network state is tested against an in-memory
session and a fixture route table. Audio state is tested against an in-memory mixer and fixture ALSA
and PipeWire records. Input bindings are tested against configuration, an in-memory device list, and
a fixture device table that includes a key bitmap the record must drop. The default suite does not
run `debootstrap`, QEMU, or labwc. Live xAI, a physical GPU workload, and hardware installation are
outside the default suite.
