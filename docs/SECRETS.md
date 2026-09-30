# Secrets

OMNE keeps credentials out of source, logs, task events, agent prompts, SQLite task records, and
plain configuration files. A tool call still passes through the permission evaluator. The secret
service is a second check: the grant and the audience both have to allow the caller.

```text
agent or core
      │
      ▼
permission policy          ← secrets:use or secrets:manage
      │
      ▼
SecretService              ← audience, audit, redaction
      │
      ▼
provider                   ← Linux keyring, or an explicit development fallback
```

## Scopes

| Scope       | What it is for       |
| ----------- | -------------------- |
| model       | A model provider     |
| api         | An external API      |
| browser     | A browser session    |
| network     | A network credential |
| application | An application login |
| service     | Another OMNE service |

A name is a short lowercase identifier such as `xai`. The audience is the list of agent ids allowed
to receive that credential. `core` is the id used when the runtime itself needs the value. An empty
audience is rejected.

## Operations

| Operation | Who                                          | Result                                     |
| --------- | -------------------------------------------- | ------------------------------------------ |
| store     | `core`, with confirmation, not in production | Saves a new name. Does not return it.      |
| retrieve  | An agent named in the audience, with `use`   | Returns that one credential.               |
| delete    | `core`, with confirmation, not in production | Removes it. Does not return it.            |
| rotate    | `core`, with confirmation, not in production | Replaces the value and keeps the audience. |
| exists    | An agent named in the audience, with `use`   | True only when that agent may see it.      |

Another agent, a missing grant, a failed permission check, and a store that cannot be reached are
denials. The denial does not include the credential. Production does not manage secrets through this
policy. A secret created in development remains readable later when the audience and the grant still
match.

## Providers

| Provider | When                                                                                 |
| -------- | ------------------------------------------------------------------------------------ |
| linux    | Development and production when the kernel keyring accepts a key                     |
| memory   | Tests. Also development, only when the keyring is unavailable and the fallback is on |
| closed   | The keyring is unavailable and the fallback is off. Every operation is denied.       |

The Linux provider uses `libkeyutils` and a keyring named `omne.secrets` on the session keyring. The
value is kernel memory, not a TOML file. The audience is a separate key in that ring and does not
contain the value. A keyring that cannot be read back is treated as unavailable.

`OMNE_SECRETS_DEV_FALLBACK=allow` is the only switch that enables the memory provider in
development. `true`, `1`, and an omitted variable leave it off. Production ignores the switch.

## xAI

`XAI_API_KEY` is still read in development and testing when `model/xai` is not addressed to `core`.
The variable is not an `OMNE_` setting, is not written to the configuration file, and is not
returned by the HTTP API. Production does not read it. A stored `model/xai` secret addressed to
`core` is used instead of the variable.

## Audit and redaction

Each store, retrieve, delete, rotate, and existence check appends `secrets-audit.jsonl` and
publishes `secret.accessed`. The record has the action, scope, name, agent, and decision. It has no
field for the value.

Once a value has been stored, retrieved, or accepted from `XAI_API_KEY`, later text is scrubbed
before it is written. That covers log lines, exceptions, event payloads, trace views, permission
audit arguments, model context, memory text, mission documents, and SQLite task records. Credential
field names such as `password`, `token`, and `api_key` are replaced even when the value was never
registered. The workspace file a tool writes is the caller's file. The event and the task record do
not keep a copy of a registered secret.

## Residual risk

The session keyring is readable by other processes in the same session. A sandboxed worker is in a
new user namespace, and its seccomp filter denies `add_key`, `request_key`, and `keyctl`. An
in-process agent does not receive that path. It receives a credential only through `retrieve`, and
only when the audience names it. The worker filter is still a denylist. The systemd units keep
`SystemCallFilter=@system-service` for the core and the shell.
