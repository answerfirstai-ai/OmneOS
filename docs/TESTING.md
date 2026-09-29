# Testing

The default suite is offline. It does not call external APIs, and it does not need a GPU, a browser
binary, or a Docker daemon.

## Commands

```bash
source .venv/bin/activate
python -m ruff format --check core tests
python -m ruff check core tests
python -m mypy
python -m pytest
jarvis check

npm run format:check
npm run lint
npm run typecheck
npm test
npm run build
```

`bash scripts/testing/run-checks.sh` runs the same sequence.

## What the tests cover

Python:

- Default settings, TOML loading, environment overrides, and path resolution.
- Rejection of unknown variables, unknown keys, invalid TOML, and invalid ports.
- Shipped configuration files under `configs/`.
- Text and JSON logging, including handler replacement.
- Health, not-found, and method responses.
- CORS allow and deny behavior.
- Health documents excluding configured filesystem paths.
- CLI `check`, `--version`, help, and invalid configuration.
- A subprocess that runs `python -m core serve` and answers `/health`.

TypeScript:

- Health payload parsing.
- Core URL construction.
- Query-string core URL selection.
- Fetch success and failure handling with a stubbed fetch implementation.

## Continuous integration

`.github/workflows/ci.yml` runs the Python and Node sequences on Ubuntu with Python 3.12 and
Node.js 22. The workflow is part of the repository. It has not been executed by a GitHub-hosted
runner as part of the Phase 1 local verification.

## Out of scope

Live model providers, browsers, GPUs, virtual machines, and hardware tests are not part of this
phase. Add those later as optional suites that the default `pytest` and `npm test` commands do not
require.
