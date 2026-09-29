# Development

Python 3.12 and Node.js 22. Debian and Ubuntu need the `python3.12-venv` package before
`python3 -m venv` can create `.venv`.

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
JARVIS does not load that file on startup.

`configs/development/jarvis.toml` is the default file in a checkout. `JARVIS_ENVIRONMENT=testing`
selects `configs/testing/jarvis.toml`. `JARVIS_ENVIRONMENT=production` selects
`configs/production/jarvis.toml`.

Set `XAI_API_KEY` in the environment only when you intend to call xAI. Leave
`JARVIS_LOCAL_MODEL_BASE_URL` empty to keep the local provider disconnected. Leave
`JARVIS_BROWSER_COMMAND` empty to keep browser tools unavailable.

## Run

```bash
jarvis check
jarvis serve
jarvis execute "write file notes.txt with content hello"
jarvis compute
```

`jarvis serve` listens on `http://127.0.0.1:8787` in the development configuration. Stop it with
Ctrl-C or SIGTERM.

Build the shell and serve it after the core is running:

```bash
npm run build
python3 -m http.server 4173 --directory shell
```

Open `http://127.0.0.1:4173/`. `?core=http://127.0.0.1:9000` points the page at another core.

A user-level install that does not touch the bootloader:

```bash
bash scripts/linux/install.sh --dry-run --prefix "$HOME/.local"
```

## Checks

```bash
bash scripts/testing/run-checks.sh
```

The script runs Ruff, mypy, pytest, `jarvis check`, Prettier, ESLint, the TypeScript tests, and the
shell build. When `.venv` exists, the script activates it.

## Docker

Docker is optional and was not available when this revision was verified, so the image was not built
here.

```bash
docker compose up --build
```
