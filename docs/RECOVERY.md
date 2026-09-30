# Recovery

OMNE stays recoverable when Core crashes, the shell crashes, an update fails, a model crashes,
configuration is invalid, graphics fail, or an agent uses more memory than it was allowed. The
recovery layer explains that failure. It does not erase user data, and it does not reinstall the
operating system.

```text
health checks
      │
      ▼
boot journal
      │
      ▼
NORMAL | DEGRADED | SAFE_MODE | RECOVERY
      │
      ▼
diagnostics stay available
```

`GET /recovery` and `OMNE recover` report the state. `POST /recovery` is 404. Recovery commands do
not call `apt-get`, `systemctl start`, or a disk formatter.

## States

| State     | When it is used                                                                         |
| --------- | --------------------------------------------------------------------------------------- |
| NORMAL    | Required checks passed and no open failure is recorded.                                 |
| DEGRADED  | Core can run, and graphics, network, the shell, or one model failed.                    |
| SAFE_MODE | Three startups in a row never became ready, an agent ran away, or the operator asked.   |
| RECOVERY  | A required check failed, configuration is invalid, an update failed, or Core just died. |

`explanation` says why normal startup is not in effect. After a later healthy start, `explain` still
names the last failed start.

## Checks

| Check    | Required | Failure                                                          |
| -------- | -------- | ---------------------------------------------------------------- |
| linux    | yes      | The kernel is not Linux.                                         |
| systemd  | yes      | PID 1 is not systemd.                                            |
| service  | yes      | `omne-core.service` is not active. The check does not start it.  |
| core     | yes      | The core process is not up.                                      |
| ipc      | yes      | Nothing accepts the core's localhost port.                       |
| graphics | no       | The display probe cannot launch a session. The shell is reduced. |
| network  | no       | No default route is published.                                   |
| storage  | yes      | The data directory is missing or not writable. It is not wiped.  |

On a fixture root the probe reads files and does not run `systemctl`. On the host it uses
`systemctl is-active` and does not start, stop, or isolate a unit. Graphics and network reuse the
existing read-only probes.

## Safe mode

Safe mode is how Core starts after repeated startup failures.

- Third-party agents are disabled. Shipped agents stay: `system`, `coding`, `research`, `browser`,
  and `browser-worker`. `system` stays even when it is the agent that ran away, so diagnostics
  remain.
- Optional models are disabled. The mock model stays. `xai` and `local` do not load.
- The shell keeps the diagnostics and recovery surfaces and hides tasks, agents, models, missions,
  and voice.
- A single crashed model is disabled without turning the other optional models off.

The operator can request the same mode with `OMNE recover safe`. `OMNE recover normal` leaves it
only when required checks pass and no failed update or invalid configuration is still open.

## Startup failures

Each `OMNE serve` records a boot. A start that is still `starting` on the next boot is a crash
before ready. A boot left `ready` without `stopped` is a crash after the process accepted
connections. Three of those in a row select safe mode. A clean stop does not count. The threshold is
the journal, not a deleted data directory.

## Commands

| Command                 | What it does                                                      |
| ----------------------- | ----------------------------------------------------------------- |
| `OMNE recover`          | Print the state, checks, and explanation.                         |
| `OMNE recover check`    | Read the checks again.                                            |
| `OMNE recover explain`  | Print why normal startup failed.                                  |
| `OMNE recover safe`     | Record safe mode. User files stay.                                |
| `OMNE recover normal`   | Leave safe mode when the required checks pass.                    |
| `OMNE recover rollback` | Roll the update slot record back. This does not reinstall the OS. |

`erase` and `reinstall` are refused. An invalid configuration is reported from the existing error
and the configuration file is left as it was. A failed, interrupted, or rejected update is a
recovery explanation. Rollback uses the update layer's slot record and does not call apt.

## What this revision does not do

The development host is not restarted. systemd units are not started or stopped. Disks are not
formatted. User files under the data directory are not deleted. Recovery commands do not write an
ISO. Image creation is `scripts/linux/build-iso.sh`, and it does not install onto a disk.
