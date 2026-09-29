# Architecture

OMNE OS is a user-space runtime on Linux. Linux owns the kernel, hardware, processes, and devices.
OMNE plans work, checks permission, and calls a small set of tools. It is not a bootable operating
system in this revision. Models do not receive a shell.

```text
USER
  |
  v
INTENT ENGINE ---- WORLD STATE ---- CONTEXT BUILDER
  |                      |                  |
  +----------------------+------------------+
                         |
                         v
                  DECISION ENGINE
                         |
                         v
                      MISSION
                         |
                         v
                     OBJECTIVE
                         |
                         v
                       PLAN
                         |
                         v
                    TASK GRAPH
                         |
                         v
                 RESOURCE MANAGER
                         |
            +------------+------------+
            v            v            v
         WORKER       WORKER       WORKER
            |            |            |
          AGENT        AGENT        AGENT
            |            |            |
          MODEL        MODEL        MODEL
            |            |            |
          TOOLS        TOOLS        TOOLS
            |            |            |
       PERMISSIONS  PERMISSIONS  PERMISSIONS
            +------------+------------+
                         v
                     VERIFIER
                         |
                         v
                    WORLD STATE
                         |
                         v
                      MEMORY
                         |
                         v
                      RESULT
```

The shell talks to OMNE Core over HTTP. `core.api.runtime.build_OMNE` assembles the process. Missing
agent or model directories leave those registries empty.

## Commands

`OMNE check` validates configuration and creates the workspace and data directories. It does not
build the runtime. `OMNE serve` exposes the local HTTP API. `OMNE execute` creates a mission for one
objective and runs it. `OMNE execute --dry-run` stores the plan and does not call tools.
`OMNE compute` prints one resource snapshot. Inspection commands print JSON: `mission list`,
`mission show`, `world`, `agents`, `workers`, `models`, `capabilities`, `trace`, `events`, and
`memory`.

## Mission

A mission sits above the task graph. It is stored in `memory/missions.sqlite` and moves through
CREATED, ANALYZING, PLANNING, READY, RUNNING, WAITING, VERIFYING, COMPLETED, FAILED, CANCELLED,
PAUSED, and RECOVERING. Each change publishes a `mission.*` event. `OMNE execute` creates one
mission for the objective. An ambiguous request such as "delete the project" becomes WAITING and
records a question. A privileged or destructive terminal command is denied before any tool runs.

## World state

`WorldStateService` keeps a revision and rebuilds from registries, the task store, missions,
workers, a cached telemetry snapshot, and the workspace project. The cache lasts
`world_state_ttl_seconds` unless an important event invalidates it. `GET /world` returns that
document. GPU stays unavailable when `nvidia-smi` is absent. Configuration in the document does not
include secrets.

## Intent and decision

`IntentEngine` parses known commands locally. It calls no model. A caller can pass model text when a
model was already consulted. Unknown text falls back to a conversation intent. Ambiguous deletes and
bare "fix it" / "do it" requests become questions.

`DecisionEngine` chooses DIRECT_TOOL, LOCAL_MODEL, CLOUD_MODEL, HYBRID, DEFER, WAIT, ASK_USER, or
DENY from the intent, execution mode, and declared availability. It does not map a task id to a
model id. The existing planner still builds the task graph for requests that are allowed to run.
`select()` remains priority-first so development and testing keep the mock route. `choose()` drops
mock in production and drops cloud models in offline and local modes. A local model with an empty
URL is UNAVAILABLE. `load()` does not download or map weights and does not emit `model.loaded`.

Execution mode is `OMNE_EXECUTION_MODE`. When it is omitted, development, testing, and production
follow `OMNE_ENVIRONMENT`.

## Agents and workers

An agent is a manifest: identity, capabilities, tools, permissions, and `max_workers` (default 1).
The coding agent allows two workers. A worker is one running slot with a task, mission, model, and
trace. `admit_worker` denies a start at `max_workers` and waits when a measured CPU percent is at
least 95. Unknown CPU does not count as free or busy capacity. Discovery loads `agent.toml` and
`manifest.toml` only, so `tools.toml` and `permissions.toml` cannot grant anything by existing.

## Capabilities, context, memory, and verification

The capability registry lists tools, agents, and models. `GET /capabilities` returns it.

The context builder ranks a few memory notes and the project name, then stops at the configured item
and character limits. It does not send the memory database to a model. Memory rows gained `trace_id`
and `source` columns. Older databases keep their rows. Context uses the task and project scopes
only.

The verifier checks file writes and HTML produced by `model_then_write`. Other results are
INCONCLUSIVE. A FAIL blocks completion when `verification_required` is true, which is the default.
An agent saying the work is done is not evidence.

## Trace, events, and recovery

`trace_id` is stored on the mission and copied onto events published in that context.
`GET /traces/{trace_id}` returns the matching events and missions. Event replay folds those events
into a state document and does not call tools.

Recovery classifies failures and chooses retry, backoff, a different model, a different agent,
replan, ask-user, or abort. Destructive tool failures are not retried. Retries stop at
`task_retry_limit`. Replan and a different tool stop the current attempt and record the decision. A
different model or agent is used only when another enabled candidate exists.

## Permissions

The gateway is still the only execution path. Command classes (READ_ONLY, MUTATING, PRIVILEGED,
DESTRUCTIVE, NETWORK, PACKAGE_INSTALL, PROCESS_CONTROL, SYSTEM_CONFIGURATION) are attached to
terminal and process decisions. The deny list is unchanged. Workers use the agent manifest grants
for that call. They do not receive extra permissions because a mission exists.

## Model cache

The text cache key includes provider, model, model version, system text, prompt, tool definitions,
world revision, context revision, and generation settings. A new mission changes the world revision,
so the same sentence in a later mission is a miss. Tool results, permission decisions, and live
telemetry are not cached. The cache emits hit, miss, bypass, and invalidation records.
`cache_ttl_seconds` of 0 means the key, not the clock, decides freshness.

## API and shell

Existing routes stay in place. Added routes: missions, world, capabilities, workers, traces, memory,
verification, graph, and questions. `GET /desktop` returns tasks, agents, models, events, voice,
missions, and workers. It also returns child activity, pending confirmations, questions, and project
identity. It does not include a compute sample. The shell polls `GET /compute` on its own.

The desktop is a windowed environment. A core mark shows idle, listening, understanding, planning,
routing, working, waiting, verifying, success, and error from health, voice, mission status, and a
real `decision.selected` event. Routing is not shown unless that event is present. No character
asset is shipped. A later renderer can replace the mark without a backend change. Listen stays
disabled.

Command input posts an objective. The command window then shows understanding, planning, working,
and verification in plain language. The recorded lifecycle stays under technical details. Allow and
deny post to the existing confirm route. The shell does not run tools itself. Notifications stay in
the notices window. The system graph, while open, shows the active mission neighborhood, or only the
core when nothing is active. Inspect and debug reveal provider names, idle workers, and identifiers.
Unknown resource values stay unknown, and an unavailable GPU stays unavailable.

`GET /graph` lists nodes and edges that exist in the current stores. It does not invent nodes.

## Linux integration

Ubuntu 24.04 LTS is the development base. OMNE packages and systemd units sit on that userspace.
`multi-user.target` wants `omne.target`, which starts OMNE Core and the shell. The system user is
`omne`. State stays under `/var/lib/omne`. The core still binds to `127.0.0.1`.

`scripts/linux/install.sh` remains the user-level unit for a checkout and still refuses `/boot`. It
does not change the bootloader. The system tree, packages, and rootfs builder are described in
`docs/LINUX.md`. The base rootfs does not install a kernel. `scripts/linux/build-disk.sh` adds
Ubuntu's kernel, an initramfs, and systemd-boot on a UEFI disk, and the console is `omne-boot`
rather than a display manager. `scripts/linux/build-iso.sh` still exits 2. `vm-boot.sh` starts QEMU
only when `--run` is passed and OVMF is installed.
