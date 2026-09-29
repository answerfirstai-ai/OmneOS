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
- `GET /desktop` returns the shell panels, including activity, confirmations, questions, and
  project, and does not include a compute sample.
- The same model prompt and cache context reuse one response. A later mission changes the world
  revision, so the same sentence is fetched again. Tool calls are not cached.
- Memory scope checks, provenance columns on older databases, agent manifests, and lifecycle edges.
- Missions, world-state revisions, intent, decisions, capabilities, workers, verification, traces,
  dry-run, command classes, and the new HTTP routes.
- Objective execution, dependency order, retry escalation, parallel work, and voice silence.
- The installer refusing `/boot`, the Ubuntu 24.04 system tree, the three system packages, the
  rootfs and UEFI disk builders refusing to write without root, and the ISO and VM scripts exiting
  without an image or a boot unless `vm-boot.sh --run` is passed.
- Display diagnostics. The testing API uses the mock provider and does not invent a monitor. The
  labwc provider reads a fixture filesystem and does not start a compositor.
- Window records. The testing API uses the mock window provider and starts with no windows. A grant
  is required to launch or close. The labwc window provider reads a fixture snapshot and does not
  run a compositor process. `POST /windowing` stays 404.

TypeScript:

- Health parsing, core URL selection, and the windowing state parser.
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
tree. Window commands are tested against the in-memory record and a snapshot file. The default suite
does not run `debootstrap`, QEMU, or labwc. Live xAI, a physical GPU workload, and hardware
installation are outside the default suite.
