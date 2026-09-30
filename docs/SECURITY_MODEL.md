# Security model

OMNE agents do not receive the Linux system. A tool call is admitted only when the permission policy
allows it and the caller's security profile allows it. Either denial stops the call. A failure
inside either check is a denial.

## Assets

- The bootloader and `/boot` or `/efi`.
- The kernel, its modules, firmware, and kernel memory devices.
- System configuration under `/etc`.
- Credentials: account databases, sudoers, and SSH host material.
- Other users' homes and `/root`.
- OMNE security configuration under `/etc/omne`.
- Raw devices under `/dev`.
- System processes: pid 1, kernel threads, system services, security services, the desktop session,
  and OMNE Core.

## Adversaries

The boundary assumes an agent, worker, model, or application will ask for more than its task needs.
A mistaken permission grant, a path that walks out of the workspace, and a command that tries to
change uid or mount the host are in scope. The host kernel and the administrator who installs the
systemd units are outside this boundary.

## Profiles

| Profile     | User       | Host spawn | Network  | What it is                                             |
| ----------- | ---------- | ---------- | -------- | ------------------------------------------------------ |
| SYSTEM      | root       | no         | host     | The machine. OMNE cannot select this profile.          |
| CORE        | omne       | no         | loopback | The core service.                                      |
| AGENT       | omne-agent | no         | none     | An agent definition. It does not run host code.        |
| WORKER      | omne-agent | sandboxed  | none     | One in-memory worker. Read-only host commands.         |
| MODEL       | omne-agent | no         | loopback | A resident model. No host spawn.                       |
| SHELL       | omne       | no         | loopback | The static shell.                                      |
| APPLICATION | omne-app   | no         | none     | A desktop application record. The host is not started. |

SYSTEM has a zero ceiling so it cannot be used by asking for a small claim. Every other profile has
a hard ceiling for RAM, VRAM, CPU threads, process count, and file size. A claim above the ceiling
is denied before a reservation is taken. The compute ledger still applies underneath that ceiling.

## Defense in depth

1. The permission policy and its fail-closed evaluator.
2. This profile boundary. A permissive permission result does not open a protected path, a
   privileged command, a closed network, or an oversized claim.
3. The worker sandbox for a host command that both gates allowed. It is a new user namespace, then
   mount, network, UTS, IPC, and PID namespaces. System directories that the loader needs are
   remounted read-only. Boot, firmware, credentials, other homes, OMNE configuration, and unsafe
   device nodes are covered. `no_new_privs` is set. On x86_64 a seccomp denylist kills `mount`,
   `umount`, `pivot_root`, `unshare`, `setns`, `ptrace`, module loading, `kexec`, `bpf`, `reboot`,
   and related calls. Any other architecture refuses to exec.
4. systemd for the installed core and shell. The unit files carry the profile directives:
   `ProtectSystem=strict`, `PrivateDevices`, `NoNewPrivileges`, an empty capability set,
   `SystemCallFilter=@system-service`, loopback-only addresses, and inaccessible boot and credential
   paths. Memory, task, and CPU ceilings are cgroup settings on those units. This process has no
   writable cgroup, so it does not pretend to apply one. Worker commands use `RLIMIT_AS`,
   `RLIMIT_CPU`, `RLIMIT_NOFILE`, and `RLIMIT_FSIZE` instead.
5. Linux providers for applications, processes, network, storage, and hardware still do not spawn,
   signal, or format the host. The profile does not add that ability.

`omne`, `omne-agent`, and `omne-app` are separate system users with `nologin`. The core unit runs as
`omne`. A worker command in this process cannot change its host uid, because that requires
`CAP_SETUID` on the host. The user namespace maps the current uid to root only inside the sandbox,
which drops host capabilities. The command does not receive `HOME` or credential paths.

## Fail closed

An unknown profile, the SYSTEM profile, a missing sandbox limit, a limit above the worker ceiling, a
namespace or mount that cannot be applied, or a seccomp filter that cannot be installed exits the
launcher with status 126 and does not exec. The gateway turns a boundary denial into `tool.denied`
and does not call the tool. Permission is still evaluated first and recorded in the audit log.

## Residual risk

The worker seccomp filter is a denylist of escape and privilege syscalls, not systemd's
`@system-service` allowlist. glibc calls `personality` during startup, so that call is not on the
denylist. The systemd units apply the allowlist to CORE and SHELL. A worker can still use ordinary
read and write syscalls inside the namespace. The mounts, the closed network namespace, and the
permission gate are what keep those calls off the bootloader, credentials, and other users.

The packaged core sets `RestrictNamespaces=true`. A host command that needs the worker sandbox
cannot be started from that service. Production already denies `terminal.execute`. The denial stays
a denial.

The worker denylist also includes `add_key`, `request_key`, and `keyctl`. Credentials live in the
kernel keyring described in `docs/SECRETS.md`. A sandbox that cannot call those syscalls cannot read
that ring.
