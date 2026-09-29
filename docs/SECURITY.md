# Security

Phase 1 has a narrow attack surface: configuration parsing, logging, and a local health service.
This document describes that behavior. It does not claim coverage for agents, tools, or model
providers, which are not implemented.

## Secrets

- Credentials are not required to run the foundation.
- No API keys, tokens, passwords, or private certificates are stored in the repository.
- `.env` is gitignored. `.env.example` contains only documented variable names and local defaults.
- The process does not auto-load `.env`, so placing a secret file next to the code does not publish
  it into the process.

## Startup

Invalid configuration refuses to start and returns exit code 2. Unknown `JARVIS_` environment
variables are rejected. Unknown TOML keys are rejected. The health service does not start when
settings fail validation.

## Network

The default bind address is `127.0.0.1`. A non-loopback bind happens only when `JARVIS_HOST` or the
TOML `host` field sets one, and the server logs a warning.

`/health` and `/` return a fixed JSON document. The health document omits filesystem paths,
environment variable values, and directory listings. Other paths return a JSON `not_found` error.
Methods other than `GET` and `OPTIONS` return `method_not_allowed`.

CORS is fail-closed. When `cors_origins` is empty, responses include no
`Access-Control-Allow-Origin` header. A request origin is echoed only when it is listed. `*` is the
only way to allow every origin, and it cannot be mixed with specific origins.

The development configuration allows the local shell origins `http://127.0.0.1:4173` and
`http://localhost:4173`. The production configuration allows none.

There is no authentication on the health endpoint. The endpoint discloses the service name, version,
environment name, and `status`. Do not publish the development port to an untrusted network. The
Compose file publishes port 8787 for local use and should be treated as a development entry point.

## Host operations

Phase 1 does not install packages on the host, change boot configuration, or execute
operator-supplied shell commands. The only filesystem writes performed by `jarvis check` and
`jarvis serve` are creation of the configured workspace and data directories.

## Container

The container image definition runs the core as a non-root user. The image build itself was not
executed in the Phase 1 development environment because Docker was not installed there. Review the
Dockerfile before relying on it.

## Later phases

Tool execution, model requests, and agent actions are out of scope here. When they arrive, a central
permission check has to run before any host operation. This phase does not weaken that future
requirement: there is no side path that executes host commands.
