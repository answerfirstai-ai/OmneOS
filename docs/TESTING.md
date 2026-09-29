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
- `GET /desktop` returns the shell panels and does not include a compute sample.
- Identical model prompts reuse the response cache. Tool calls are not cached.
- Memory scope checks, agent manifests, and lifecycle edges.
- Objective execution, dependency order, retry escalation, parallel work, and voice silence.
- The installer refusing `/boot`, and the image and VM scripts exiting without an ISO or a boot.

TypeScript:

- Health parsing and core URL selection.
- Character states, including a missing asset.
- Voice control staying disabled unless permission, provider, and hardware are all available.
- Task, agent, model, and notification lines, and one `/desktop` document.

## Not claimed

`scripts/linux/build-iso.sh` and `scripts/linux/vm-boot.sh` are tested for their refusal. They do
not produce `OMNE-OS.iso` and do not start a virtual machine. Live xAI, a physical GPU workload, and
hardware installation are outside the default suite.
