# Processes

OMNE names every process it can see. A record carries the executable, CPU time, RAM, owner, parent,
children, state, start time, and resource limits. The command line stays empty until a caller holds
`process:command`.

```text
enumeration        the process table
ownership          the worker and task that launched a process
lifecycle          start, stop, and restart, each behind a grant
protection         pid 1, kernel, system, core, security, desktop
```

`GET /processes` returns the redacted table. `POST /processes` is not a route. `OMNE processes`
prints the same table and does not start or signal a process.

## Permissions

| Action  | Tool              | Grant             | Host effect                                     |
| ------- | ----------------- | ----------------- | ----------------------------------------------- |
| list    | `process.list`    | `process:list`    | Read only                                       |
| start   | `process.start`   | `process:start`   | Recorded in the mock. Not sent to the host      |
| stop    | `process.stop`    | `process:signal`  | Recorded in the mock when OMNE owns the process |
| restart | `process.restart` | `process:restart` | Recorded in the mock when OMNE owns the process |
| command | `process.command` | `process:command` | Returns one command line. Events stay redacted  |

`process.start`, `process.stop`, and `process.restart` are high risk: confirmation in development
and testing, denied in production. A shell name and a protected program are denied before that
confirmation. Pid 1 is denied for stop and restart.

The shipped system agent holds `process:list`. The coding agent also holds `process:start` and
`process:signal`. Neither holds `process:command` or `process:restart`.

## Protection

These processes cannot be started, stopped, or restarted:

- pid 1
- kernel threads, including children of pid 2
- system services such as systemd, journald, logind, udev, dbus, and cron
- OMNE Core
- security services such as sshd, polkit, auditd, and sudo
- the active desktop session, including labwc, sway, and the display manager

A refusal publishes `process.protected`. The payload names the pid. It does not include a command
line.

## Ownership

A permitted start records the agent, the worker whose current task matches, and the application
whose executable basename matches. Stop and restart succeed only for a process that record owns. The
compute check refuses a start when CPU is at least 95 percent or available memory is below 64 MB.
Unknown telemetry does not invent a denial. The check does not reserve memory.

## Events

`process.started`, `process.stopped`, `process.restarted`, and `process.protected` carry a pid. They
do not carry command-line arguments.

## Linux

The reader uses `/proc`. CPU seconds come from `utime` and `stime`. RAM comes from `VmRSS`. The
owner is the passwd name for the uid, never the password field or the shell. Limits come from the
soft value. The executable is the basename of the `exe` link. Arguments are read only for
`process.command`. Host process control is not installed, so an allowed start is reported and not
spawned, and a stop is not a signal.
