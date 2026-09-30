# Security

OMNE fails closed. A missing grant, an unknown tool, a policy exception, or an invalid decision is a
denial. The security boundary is a second gate: a permission allow does not open a protected path, a
privileged command, another user's files, or a claim above the profile ceiling. Profiles and the
worker sandbox are described in `docs/SECURITY_MODEL.md`.

## Secrets

Credentials are scoped and audited. The value is not written to source, logs, events, prompts,
SQLite task records, or plain configuration. See `docs/SECRETS.md`.

- `XAI_API_KEY` is read in development and testing when no `model/xai` secret is addressed to
  `core`. Production does not read that variable.
- The key is not an `OMNE_` setting, is not written into the configuration file, and is not returned
  by the HTTP API.
- `.env` is gitignored. The process does not auto-load it.
- Unknown `OMNE_` variables and unknown TOML keys are rejected.
- `OMNE_SECRETS_DEV_FALLBACK` enables the in-memory store only when the value is `allow` and the
  Linux keyring is unavailable. Any other value is a configuration error, except `false`, `deny`,
  and `off`.

## Permissions

Every tool call goes through `ToolGateway`. The default policy:

- Allows workspace filesystem reads, writes, search, and directory creation inside the workspace.
- Denies paths outside the workspace, `.git` paths, and recursive removal.
- Denies `sudo`, `su`, `doas`, `pkexec`, shutdown, disk partitioning, firewall, and bootloader
  commands even when the caller has already approved a confirmation.
- Requires confirmation for `terminal.execute`, `process.start`, `process.stop`, `process.restart`,
  and `git.commit` in development and testing.
- Denies those high-risk tools in production.
- Denies `voice.transmit`.
- Denies signaling pid 1. Shells and protected programs are denied before a process start is
  recorded. `process:command` is required before a command line is returned, and that line is not
  written onto a process event.

Terminal and process-start decisions also record a command class: READ_ONLY, MUTATING, PRIVILEGED,
DESTRUCTIVE, NETWORK, PACKAGE_INSTALL, PROCESS_CONTROL, or SYSTEM_CONFIGURATION. The class does not
replace the deny list. Privileged and destructive commands are denied by the decision engine before
the planner runs, and the gateway still denies them if a caller reaches the tool.

A worker uses the grants on its agent manifest for that call. It does not inherit a broader mission
grant. An agent package that only drops `tools.toml` or `permissions.toml` into `agents/` is not
loaded as a manifest and gains no permissions.

`OMNE execute --dry-run` stores the plan and does not call tools.

Decisions are appended to the audit log. The evaluator turns policy exceptions into DENY with policy
id `fail-closed`. The HTTP API does not return `XAI_API_KEY` or other secrets. `GET /memory`
requires an explicit scope and scope key and rejects unknown scopes.

## Network and process

The default bind address is `127.0.0.1`. A non-loopback bind logs a warning. There is no
authentication on the local API. Do not publish the port to an untrusted network.

CORS stays empty unless `cors_origins` lists the request origin. `POST /health` is method not
allowed. Task routes accept a JSON body up to 1 MB.

Terminal tools run with `shell=False`. The subprocess environment keeps `PATH`, `HOME`, `LANG`,
`LC_ALL`, `TMPDIR`, and `SYSTEMROOT` only. Process start, stop, and restart go through the process
service. The Linux provider does not spawn or signal a process.

## Host changes

`OMNE check` and the installer create directories under the workspace, data directory, or the
requested prefix. The user installer and the system stager refuse `/boot` and do not edit boot
configuration. System packages add an `omne` user and units under `/etc/systemd/system`. They do not
install a kernel. The UEFI disk builder installs Ubuntu's kernel package and systemd-boot, and it
refuses a display manager. Display diagnostics read DRM and input nodes and do not start labwc or
change the host session. Window mutations are not an HTTP route and are not sent to the host
compositor. `window: own` covers windows that agent launched. `window: manage` does not apply in
this revision. Hardware diagnostics only read sysfs and proc. They do not load drivers or write
device configuration, and `POST /hardware` is not a route. Network diagnostics only read sysfs and
proc. Connect, disconnect, enable, and disable require `network:configure` and are not an HTTP
route. A password is not stored on a network record or an event. `POST /network` is not a route.
Audio diagnostics only read the published stack. Volume, mute, and the default device require
`audio:configure` and are not an HTTP route. Microphone audio is not captured or transmitted, and
`voice.transmit` stays denied. `POST /audio` is not a route. Input diagnostics report configured
chords and device names. They do not read keystrokes. `input:bind` does not install a host grab.
`POST /input` is not a route. Storage diagnostics only read sysfs and the mount table. They do not
format a disk, open a raw device, or write a bootloader. Filesystem tools may use an OMNE workspace
path and deny system, boot, and device paths, including a symlink or `..` that reaches one.
`POST /storage` is not a route. Application launch, focus, and close require `application:launch`,
`application:focus`, and `application:close`. The launcher does not accept a shell command, and a
desktop `Exec` line that uses a shell is not launchable. The Linux provider does not spawn a
process. `POST /applications` is not a route. Browser launch, session navigation, inspection,
research, screenshots, user control, and automation each require their own `browser:` grant. The
shipped browser agent holds navigation only. Automation does not accept a secret, and Playwright is
not imported. `POST /browser` is not a route. Process start, stop, and restart require
`process:start`, `process:signal`, and `process:restart`. The Linux provider does not signal pid 1,
a kernel thread, a system service, OMNE Core, a security service, or the desktop session. A command
line requires `process:command` and is omitted from `GET /processes`. `POST /processes` is not a
route. The ISO script does not write `OMNE-OS.iso`. No physical disk installation is performed.
