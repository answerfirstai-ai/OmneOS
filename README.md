# JARVIS OS

JARVIS OS is an AI-native operating environment for x86-64 workstations. Linux provides the kernel
and hardware interfaces. This GitHub repository is OmneOS. The software in this tree is JARVIS OS.

This revision is the Phase 1 foundation: a Python core that loads configuration, writes logs, and
serves a local health check, plus a TypeScript shell that displays that check.

The core runs without the shell.

## Requirements

- Python 3.12
- Node.js 22
- npm 10

Debian and Ubuntu also need the `python3.12-venv` package.

Verified locally with Python 3.12.3, Node.js 22.14.0, and npm 10.9.7.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
npm install
```

`bash scripts/development/bootstrap.sh` runs the same installation.

## Run

```bash
jarvis check
jarvis serve
```

Development settings listen on `http://127.0.0.1:8787`. The health document is `GET /health`.

In another shell, after the core is running:

```bash
npm run build
python3 -m http.server 4173 --directory shell
```

Open `http://127.0.0.1:4173/`.

## Checks

```bash
bash scripts/testing/run-checks.sh
```

Details and the individual commands are in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) and
[docs/TESTING.md](docs/TESTING.md).

## Layout

```text
core/                 Python core package
configs/              development, testing, and production TOML
shell/                TypeScript status shell
tests/                Python unit and integration tests
docs/                 Architecture, security, development, testing, roadmap
scripts/development/  Local installation
scripts/testing/      Local check sequence
```

## Phase

Phase 1 is the implemented scope. [docs/ROADMAP.md](docs/ROADMAP.md) lists the later phases.
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) records the current boundaries and the decisions that
differ from the long-term tree.

## License

MIT. See [LICENSE](LICENSE).
