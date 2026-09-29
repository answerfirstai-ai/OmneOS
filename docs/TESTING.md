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
- The installer refusing `/boot`, and the image and VM scripts exiting without an ISO or a boot.

TypeScript:

- Health parsing and core URL selection.
- Character states, including a missing asset and mission-driven analyzing, verifying, and waiting.
- Environment state, lifecycle stages, mission inspection, permission copy, verification evidence,
  error summaries, notifications, graph layout, resource lines, and keyboard shortcuts.
- Voice control staying disabled unless permission, provider, and hardware are all available.
- Task, agent, model, and notification lines, and one `/desktop` document.
- Desktop windows open, come to the front, hide, minimize, maximize, and stay within resize bounds.

## Not claimed

`scripts/linux/build-iso.sh` and `scripts/linux/vm-boot.sh` are tested for their refusal. They do
not produce `OMNE-OS.iso` and do not start a virtual machine. Live xAI, a physical GPU workload, and
hardware installation are outside the default suite.
