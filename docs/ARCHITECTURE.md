# Architecture

OMNE OS is an orchestration layer above Linux. Linux owns the kernel, hardware, processes, and
devices. OMNE plans work, checks permission, and calls a small set of tools. Models do not receive a
shell.

## Runtime

```text
HUMAN
  |
  v
SHELL (TypeScript) -- HTTP --> OMNE CORE (Python)
                                 |
                                 +-- planner
                                 +-- scheduler and executor
                                 +-- permission evaluator and audit
                                 +-- tool gateway
                                 +-- model router
                                 +-- memory, events, compute
```

`OMNE check` validates configuration and creates the workspace and data directories. `OMNE serve`
exposes the local HTTP API. `OMNE execute` plans one objective and runs it. `OMNE compute` prints
one resource snapshot from the host.

The programmatic entry is `core.api.main.main`. `core.api.runtime.build_OMNE` assembles the process.
Missing agent or model directories leave those registries empty instead of inventing entries.

## Tasks

An objective becomes a parent task and one child task per plan node. Status changes go through the
table in `core/orchestrator/task.py`. Dependencies run first. Independent children run together only
when each has a free agent, the step is not exclusive, and the allocator returns ALLOW. A failed
child moves to RECOVERING. While `retry_count` is below `retry_limit` it returns to QUEUED. After
that it becomes FAILED with error code `escalated`.

High-risk tools return CONFIRM in development and testing. The task waits. `confirm` with approval
runs the stored arguments. Denial fails the task and does not execute the tool. Production denies
those tools.

## Tools and models

The gateway validates arguments, evaluates policy, writes an audit record, then executes. Tools do
not run on the way into validation. Filesystem paths must stay inside the workspace. Commands use
`shell=False`.

The mock provider is the default route. xAI is called only with `XAI_API_KEY` from the environment.
A local provider with an empty base URL reports unavailable and does not open a socket. The model
cache stores metadata and does not load weights. `model.loaded` is not emitted.

## Memory, voice, and compute

Memory records are scoped to conversation, task, project, long_term, or system. A caller cannot read
a scope it was not granted. Retrieval is a bounded SQLite query, not a dump of the database.

Voice listen returns without opening a device unless the permission decision is ALLOW. The default
policy denies `voice.transmit`, and no voice provider is configured.

CPU, memory, disk, and network come from the host. GPU telemetry uses `nvidia-smi` when it exists
and otherwise reports `available: false`. Unknown values stay null.

## Linux integration

`scripts/linux/install.sh` installs a user systemd unit under the chosen prefix. It refuses `/boot`
and does not change the bootloader. The image and VM scripts exit 2 without creating an ISO or
starting QEMU.
