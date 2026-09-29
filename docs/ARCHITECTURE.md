# Architecture

JARVIS OS is an AI-native operating environment for x86-64 workstations. Linux remains the kernel
and the owner of hardware, process, memory, networking, filesystem, device, security, and graphics
infrastructure. JARVIS is the orchestration layer and user-facing environment above that platform.

Phase 1 implements only the foundation required to install, configure, log, test, and start that
layer. Later subsystems stay behind the boundaries below and are not present in this revision.

## Phase 1 runtime

```text
HUMAN
  |
  v
SHELL (TypeScript, static page)
  |
  |  HTTP GET /health
  v
JARVIS CORE (Python)
  |
  +-- configuration
  +-- logging
  +-- local health service
  |
  v
workspace/ and memory/ directories
```

The core process is usable without the shell. The shell is a separate program that reads the public
health document. It does not import Python and it does not execute host commands.

## Process entry

- `jarvis check` loads configuration, creates the runtime directories, emits a log record, and
  exits.
- `jarvis serve` binds a local HTTP server. `GET /health` returns the public status document.
  `GET /` returns a short service description.
- `python -m core` uses the same command parser.

The programmatic entry for this phase is `core.api.main.main`. A task execution API is part of Phase
2 and is intentionally absent.

## Configuration

Settings are a typed pydantic model. `load_settings` merges sources in this order:

1. Built-in defaults.
2. A TOML file, when one is selected.
3. `JARVIS_` environment variables, which override the file.

File selection:

- `--config` or `JARVIS_CONFIG` when either is set. A missing file is an error.
- Otherwise `configs/<JARVIS_ENVIRONMENT>/jarvis.toml` relative to the working directory, when that
  file exists.
- Otherwise defaults only.

Relative `workspace_root` and `data_dir` values resolve against the process working directory. The
supported environment names are `development`, `testing`, and `production`. Unknown `JARVIS_`
variables and unknown TOML keys are errors, so a misspelled setting refuses startup.

JARVIS does not read `.env` files. `.env.example` documents the variables an operator can export.
This keeps secrets out of an implicit loader.

## Logging

Logs are emitted on the `jarvis` logger hierarchy. The format is `text` or `json`, selected by
configuration. Configuring logging again replaces the previous handler. Library code does not
configure logging on import; the command entry point does.

## HTTP service

The server uses the Python standard library. It binds to `127.0.0.1` and port `8787` unless
configuration overrides those values. Binding `0.0.0.0` or `::` is allowed only by explicit
configuration and produces a warning.

Responses are JSON. The health document contains `status`, `service`, `version`, and `environment`.
It does not include filesystem paths. Browser origins are echoed only when they appear in
`cors_origins`. An empty list sends no CORS header. The value `*` allows any origin and cannot be
combined with other entries.

## Shell

The TypeScript project in `shell/` compiles to ES modules. `shell/index.html` loads the built module
and requests `/health`. The core base URL defaults to `http://127.0.0.1:8787` and can be overridden
with `?core=`.

## Packaging

`Dockerfile` and `docker-compose.yml` describe a reproducible core process. They are not an
operating-system image. Image generation belongs to a later phase. The container listens on all
interfaces inside its network namespace because the process must accept connections published by
Compose. The image runs as the unprivileged `jarvis` user.

## Decisions that differ from the target tree

The target repository diagram includes protocol documents and packages for agents, tools, models,
memory services, permissions, and compute. Those files are omitted until the phase that implements
them. Creating them now would describe behavior the process does not have.

The Python package lives at `core/` and imports as `core`, matching the diagram. The shell stays in
`shell/` and is built by the root `package.json`.

The license is MIT. The specification requires a license file and does not name one.

## Boundaries reserved for later phases

These concerns stay separate as their implementations arrive:

- Core orchestration
- Models and model providers
- Agents
- Tools
- Permissions
- Memory beyond the on-disk data directory
- Events
- Compute management
- The full desktop shell
- Linux integration
- Image generation

No model provider is wired into core. No tool can execute host commands in this phase because no
tool interface exists. Adding those paths later must go through the permission system required by
the specification.
