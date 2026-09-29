# Development

Commands below match the Phase 1 toolchain: Python 3.12 and Node.js 22. Debian and Ubuntu need the
`python3.12-venv` package before `python3 -m venv` can create `.venv`.

## Install

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
npm install
```

`scripts/development/bootstrap.sh` runs those steps.

## Configuration

Export variables yourself when you need to override a file. A starting point is `.env.example`.

```bash
set -a
source .env.example
set +a
```

`source .env.example` is an operator action. JARVIS will not do it on startup.

The default file for a repository checkout is `configs/development/jarvis.toml`.
`JARVIS_ENVIRONMENT=testing` selects `configs/testing/jarvis.toml`. `JARVIS_ENVIRONMENT=production`
selects `configs/production/jarvis.toml`.

## Run the core

```bash
jarvis check
jarvis serve
```

`jarvis check` prints a status line and exits 0 when configuration is valid. `jarvis serve` listens
on `http://127.0.0.1:8787` in the development configuration. `GET /health` returns JSON.

Stop the server with Ctrl-C or SIGTERM.

## Run the shell

Build the TypeScript, start the core, then serve the shell directory:

```bash
npm run build
python3 -m http.server 4173 --directory shell
```

Open `http://127.0.0.1:4173/`. The page requests `http://127.0.0.1:8787/health`. A different core
URL can be passed as `http://127.0.0.1:4173/?core=http://127.0.0.1:9000`.

## Checks

```bash
bash scripts/testing/run-checks.sh
```

The script runs Ruff, mypy, pytest, `jarvis check`, Prettier, ESLint, the TypeScript tests, and the
shell build. Run it from an environment where the Python package and npm dependencies are installed.
When `.venv` exists, the script activates it.

## Docker

Docker is optional. The Compose service builds the core image and publishes port 8787. The Phase 1
environment used to write this repository did not have a Docker client, so the image was not built
here. When Docker is available:

```bash
docker compose up --build
```

That command is documented and not part of the verified Phase 1 command list.
