"""Run one command inside a worker sandbox.

The process enters a user namespace, then a mount, network, UTS, IPC, and PID
namespace. Protected paths are covered. no_new_privs and a syscall denylist
are installed before the command runs. A failure exits 126 and does not exec.
"""

from __future__ import annotations

import ctypes
import os
import resource
import sys
from pathlib import Path
from typing import NoReturn

from core.security.profiles import ProfileName, profile_for

_PREFIX = "omne-sandbox:"
_MS_RDONLY = 1
_MS_NOSUID = 2
_MS_NODEV = 4
_MS_NOEXEC = 8
_MS_REMOUNT = 32
_MS_BIND = 4096
_MS_REC = 16384
_MS_PRIVATE = 1 << 18
_MASK_FLAGS = _MS_NOSUID | _MS_NODEV | _MS_NOEXEC
_PR_SET_NO_NEW_PRIVS = 38
_PR_SET_SECCOMP = 22
_SECCOMP_MODE_FILTER = 2
_AUDIT_ARCH_X86_64 = 0xC000003E
_BPF_LD = 0x00
_BPF_W = 0x00
_BPF_ABS = 0x20
_BPF_JMP = 0x05
_BPF_JEQ = 0x10
_BPF_K = 0x00
_BPF_RET = 0x06
_SECCOMP_RET_KILL_PROCESS = 0x80000000
_SECCOMP_RET_ALLOW = 0x7FFF0000
_DENIED_SYSCALLS = (
    101,
    155,
    163,
    165,
    166,
    167,
    168,
    169,
    175,
    176,
    246,
    248,
    249,
    250,
    272,
    298,
    304,
    308,
    310,
    311,
    312,
    313,
    320,
    321,
    323,
)
_READONLY = ("/usr", "/lib", "/lib64", "/bin", "/sbin")
_COVER_DIRS = (
    "/boot",
    "/efi",
    "/root",
    "/lib/modules",
    "/usr/lib/modules",
    "/sys/firmware",
    "/etc/ssh",
    "/etc/sudoers.d",
    "/etc/security",
    "/etc/omne",
)
_COVER_FILES = ("/etc/shadow", "/etc/gshadow", "/etc/sudoers")
_REQUIRED_DEVICES = ("null", "zero", "urandom")
_OPTIONAL_DEVICES = ("full", "random", "tty")


class _Filter(ctypes.Structure):
    _fields_ = (
        ("code", ctypes.c_uint16),
        ("jt", ctypes.c_uint8),
        ("jf", ctypes.c_uint8),
        ("k", ctypes.c_uint32),
    )


class _Program(ctypes.Structure):
    _fields_ = (("len", ctypes.c_uint16), ("filter", ctypes.POINTER(_Filter)))


def main(argv: list[str] | None = None) -> None:
    """Replace this process with a confined command."""

    args = list(sys.argv if argv is None else argv)
    if len(args) < 3:
        _fail("command is missing")
    workspace = args[1]
    command = args[2:]
    _exec_confined(workspace, command)


def _exec_confined(workspace: str, command: list[str]) -> None:
    if os.name != "posix":
        _fail("sandbox requires Linux")
    if not command or any("\x00" in item for item in command):
        _fail("command is invalid")
    root = Path(workspace)
    if not root.is_dir():
        _fail("workspace is not a directory")
    limits = _limits()
    host_uid = os.getuid()
    host_gid = os.getgid()
    blank = Path("/tmp") / f"omne-blank-{os.getpid()}"
    try:
        _enter_namespaces(host_uid, host_gid)
        _isolate_mounts(root, blank)
        _apply_limits(limits)
        _no_new_privileges()
        pid = os.fork()
    except Exception as exc:
        _fail(str(exc))
    if pid != 0:
        _wait_child(pid)
    try:
        if libc_mount(b"proc", b"/proc", b"proc", _MASK_FLAGS, None) != 0:
            _fail("proc mount failed")
        _install_seccomp()
        os.chdir(root)
        os.execvpe(command[0], command, _child_env())
    except OSError as exc:
        _fail(str(exc))


def _limits() -> dict[str, int]:
    profile = profile_for(ProfileName.WORKER.value)
    if profile is None:
        _fail("worker profile is missing")
    ceiling = profile.ceiling
    raw = {
        "as": os.environ.get("OMNE_SANDBOX_AS", ""),
        "cpu": os.environ.get("OMNE_SANDBOX_CPU", ""),
        "nofile": os.environ.get("OMNE_SANDBOX_NOFILE", ""),
        "fsize": os.environ.get("OMNE_SANDBOX_FSIZE", ""),
    }
    if any(not item for item in raw.values()):
        _fail("sandbox limits are incomplete")
    try:
        parsed = {key: int(value) for key, value in raw.items()}
    except ValueError:
        _fail("sandbox limits are invalid")
    caps = {
        "as": ceiling.ram_mb * 1024 * 1024,
        "cpu": ceiling.cpu_seconds,
        "nofile": ceiling.nofile,
        "fsize": ceiling.file_mb * 1024 * 1024,
    }
    for key, cap in caps.items():
        if parsed[key] <= 0 or parsed[key] > cap:
            _fail("sandbox limit exceeds the worker ceiling")
    for key in ("OMNE_SANDBOX_AS", "OMNE_SANDBOX_CPU", "OMNE_SANDBOX_NOFILE", "OMNE_SANDBOX_FSIZE"):
        os.environ.pop(key, None)
    return parsed


def _enter_namespaces(uid: int, gid: int) -> None:
    os.unshare(os.CLONE_NEWUSER)
    _write("/proc/self/setgroups", b"deny")
    _write("/proc/self/uid_map", f"0 {uid} 1\n".encode())
    _write("/proc/self/gid_map", f"0 {gid} 1\n".encode())
    flags = os.CLONE_NEWNS | os.CLONE_NEWNET | os.CLONE_NEWUTS | os.CLONE_NEWIPC | os.CLONE_NEWPID
    os.unshare(flags)


def _isolate_mounts(workspace: Path, blank: Path) -> None:
    if libc_mount(b"none", b"/", None, _MS_REC | _MS_PRIVATE, None) != 0:
        _fail("mount namespace could not be made private")
    saved = Path("/tmp") / f"omne-ws-{os.getpid()}"
    if _contains(workspace, saved) or _contains(workspace, blank):
        _fail("workspace cannot contain the sandbox state")
    saved.mkdir(parents=True, exist_ok=True)
    if _mount_bind(str(workspace), str(saved)) != 0:
        _fail("workspace could not be saved")
    _readonly_tree()
    _cover_directories(workspace)
    _cover_files(blank)
    _cover_other_homes(workspace)
    _hide_unsafe_devices()
    if _mount_bind(str(saved), str(workspace)) != 0:
        _fail("workspace could not be restored")


def _readonly_tree() -> None:
    flags = _MS_BIND | _MS_REC
    remount = flags | _MS_REMOUNT | _MS_RDONLY | _MS_NOSUID | _MS_NODEV
    for raw in _READONLY:
        if not Path(raw).is_dir():
            continue
        bound = _mount_bind(raw, raw)
        remounted = libc_mount(raw.encode(), raw.encode(), None, remount, None)
        if bound != 0 or remounted != 0:
            _fail(f"could not make {raw} read-only")


def _cover_directories(workspace: Path) -> None:
    for raw in _COVER_DIRS:
        path = Path(raw)
        if not path.exists():
            continue
        if _contains(path, workspace) or _contains(workspace, path):
            continue
        if libc_mount(b"tmpfs", raw.encode(), b"tmpfs", _MASK_FLAGS, None) != 0:
            _fail(f"could not cover {raw}")


def _cover_files(blank: Path) -> None:
    blank.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(blank, os.O_CREAT | os.O_RDWR, 0o600)
    os.close(fd)
    for raw in _COVER_FILES:
        if not Path(raw).exists():
            continue
        if _mount_bind(str(blank), raw) != 0:
            _fail(f"could not cover {raw}")


def _cover_other_homes(workspace: Path) -> None:
    home = Path("/home")
    if not home.is_dir():
        return
    if not _contains(home, workspace):
        if libc_mount(b"tmpfs", b"/home", b"tmpfs", _MASK_FLAGS, None) != 0:
            _fail("could not cover /home")
        return
    try:
        names = sorted(home.iterdir())
    except OSError as exc:
        _fail(f"could not read /home: {exc}")
    for path in names:
        if _contains(path, workspace):
            continue
        if libc_mount(b"tmpfs", os.fsencode(path), b"tmpfs", _MASK_FLAGS, None) != 0:
            _fail(f"could not cover {path}")


def _hide_unsafe_devices() -> None:
    fresh = Path("/tmp") / f"omne-dev-{os.getpid()}"
    fresh.mkdir(parents=True, exist_ok=True)
    for name in (*_REQUIRED_DEVICES, *_OPTIONAL_DEVICES):
        source = Path("/dev") / name
        if not source.exists():
            if name in _REQUIRED_DEVICES:
                _fail(f"/dev/{name} is missing")
            continue
        target = fresh / name
        target.touch()
        if _mount_bind(str(source), str(target)) != 0:
            _fail(f"could not preserve /dev/{name}")
    if _mount_bind(str(fresh), "/dev") != 0:
        _fail("could not replace /dev")


def _apply_limits(limits: dict[str, int]) -> None:
    resource.setrlimit(resource.RLIMIT_AS, (limits["as"], limits["as"]))
    resource.setrlimit(resource.RLIMIT_CPU, (limits["cpu"], limits["cpu"]))
    resource.setrlimit(resource.RLIMIT_NOFILE, (limits["nofile"], limits["nofile"]))
    resource.setrlimit(resource.RLIMIT_FSIZE, (limits["fsize"], limits["fsize"]))


def _no_new_privileges() -> None:
    if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        _fail("no_new_privs could not be set")


def _install_seccomp() -> None:
    if os.uname().machine != "x86_64":
        _fail("seccomp denylist is not verified for this architecture")
    denied = _DENIED_SYSCALLS
    filters: list[_Filter] = [
        _stmt(_BPF_LD | _BPF_W | _BPF_ABS, 4),
        _jump(_BPF_JMP | _BPF_JEQ | _BPF_K, _AUDIT_ARCH_X86_64, 1, 0),
        _stmt(_BPF_RET | _BPF_K, _SECCOMP_RET_KILL_PROCESS),
        _stmt(_BPF_LD | _BPF_W | _BPF_ABS, 0),
    ]
    count = len(denied)
    for index, number in enumerate(denied):
        filters.append(_jump(_BPF_JMP | _BPF_JEQ | _BPF_K, number, count - index, 0))
    filters.append(_stmt(_BPF_RET | _BPF_K, _SECCOMP_RET_ALLOW))
    filters.append(_stmt(_BPF_RET | _BPF_K, _SECCOMP_RET_KILL_PROCESS))
    table = (_Filter * len(filters))(*filters)
    program = _Program(len(filters), table)
    if libc.prctl(_PR_SET_SECCOMP, _SECCOMP_MODE_FILTER, ctypes.byref(program), 0, 0) != 0:
        _fail("seccomp filter could not be installed")


def _wait_child(pid: int) -> None:
    _pid, status = os.waitpid(pid, 0)
    if os.WIFEXITED(status):
        os._exit(os.WEXITSTATUS(status))
    if os.WIFSIGNALED(status):
        os._exit(128 + os.WTERMSIG(status))
    os._exit(126)


def _child_env() -> dict[str, str]:
    kept = {}
    for key in ("PATH", "LANG", "LC_ALL"):
        value = os.environ.get(key)
        if value:
            kept[key] = value
    kept["HOME"] = "/tmp"
    kept["TMPDIR"] = "/tmp"
    return kept


def _contains(parent: Path, child: Path) -> bool:
    return child == parent or parent in child.parents


def _write(path: str, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY)
    os.write(fd, data)
    os.close(fd)


def _mount_bind(source: str, target: str) -> int:
    return libc_mount(source.encode(), target.encode(), None, _MS_BIND, None)


def _stmt(code: int, value: int) -> _Filter:
    return _Filter(code, 0, 0, value)


def _jump(code: int, value: int, yes: int, no: int) -> _Filter:
    return _Filter(code, yes, no, value)


def _fail(message: str) -> NoReturn:
    sys.stderr.write(f"{_PREFIX} {message}\n")
    sys.stderr.flush()
    os._exit(126)


def libc_mount(
    source: bytes | None,
    target: bytes,
    fstype: bytes | None,
    flags: int,
    data: bytes | None,
) -> int:
    return int(libc.mount(source, target, fstype, flags, data))


libc = ctypes.CDLL(None, use_errno=True)
libc.mount.argtypes = [
    ctypes.c_char_p,
    ctypes.c_char_p,
    ctypes.c_char_p,
    ctypes.c_ulong,
    ctypes.c_char_p,
]
libc.mount.restype = ctypes.c_int
libc.prctl.argtypes = [
    ctypes.c_int,
    ctypes.c_ulong,
    ctypes.c_void_p,
    ctypes.c_ulong,
    ctypes.c_ulong,
]
libc.prctl.restype = ctypes.c_int


if __name__ == "__main__":
    main()
