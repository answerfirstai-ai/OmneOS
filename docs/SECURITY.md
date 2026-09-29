# Security

OMNE fails closed. A missing grant, an unknown tool, a policy exception, or an invalid decision is a
denial.

## Secrets

- `XAI_API_KEY` is read from the process environment when the xAI provider is constructed.
- The key is not a `OMNE_` setting, is not written to disk by the core, and is not returned by the
  HTTP API.
- `.env` is gitignored. The process does not auto-load it.
- Unknown `OMNE_` variables and unknown TOML keys are rejected.

## Permissions

Every tool call goes through `ToolGateway`. The default policy:

- Allows workspace filesystem reads, writes, search, and directory creation inside the workspace.
- Denies paths outside the workspace, `.git` paths, and recursive removal.
- Denies `sudo`, `su`, `doas`, `pkexec`, shutdown, disk partitioning, firewall, and bootloader
  commands even when the caller has already approved a confirmation.
- Requires confirmation for `terminal.execute`, `process.start`, `process.stop`, and `git.commit` in
  development and testing.
- Denies those high-risk tools in production.
- Denies `voice.transmit`.
- Denies signaling pid 1. The process tool also rejects pid 1 before a signal is sent.

Decisions are appended to the audit log. The evaluator turns policy exceptions into DENY with policy
id `fail-closed`.

## Network and process

The default bind address is `127.0.0.1`. A non-loopback bind logs a warning. There is no
authentication on the local API. Do not publish the port to an untrusted network.

CORS stays empty unless `cors_origins` lists the request origin. `POST /health` is method not
allowed. Task routes accept a JSON body up to 1 MB.

Terminal and process tools run with `shell=False`. The subprocess environment keeps `PATH`, `HOME`,
`LANG`, `LC_ALL`, `TMPDIR`, and `SYSTEMROOT` only.

## Host changes

`OMNE check` and the installer create directories under the workspace, data directory, or the
requested prefix. The installer refuses `/boot` and does not edit boot configuration. The image
script does not write `OMNE-OS.iso`. No physical disk installation is performed.
