"""Read the process table without signaling a process.

``/proc`` supplies the executable, owner, parent, children, state, start time,
and limits. Command-line arguments are omitted unless a request sets
``reveal``. This module does not spawn a process and does not send a signal.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from omne.processes.model import (
    ProcessEvent,
    ProcessOutcome,
    ProcessRecord,
    ProcessRequest,
    ProcessSnapshot,
    ProcessStateName,
    ResourceLimits,
)
from omne.processes.protect import protection_for, protection_reason, refused_program

HOST_CONTROL = "host process control is not installed"
_NOT_OWNED = "process is not owned by an OMNE worker"
_MISSING = "process was not found"
_HZ = 100
_STATES: dict[str, ProcessStateName] = {
    "R": "running",
    "S": "sleeping",
    "D": "disk_sleep",
    "Z": "zombie",
    "T": "stopped",
    "t": "tracing",
    "I": "idle",
    "X": "dead",
}
_LIMITS = {
    "max cpu time": "cpu_seconds",
    "max address space": "address_bytes",
    "max open files": "open_files",
    "max processes": "processes",
}


class LinuxProcessProvider:
    """Report processes from one filesystem root."""

    def __init__(self, *, root: Path | None = None, core_pid: int | None = None) -> None:
        self._root = root if root is not None else Path("/")
        self._core_pid = os.getpid() if core_pid is None and self._root == Path("/") else core_pid

    def snapshot(self) -> ProcessSnapshot:
        if not (self._root / "proc").is_dir():
            return ProcessSnapshot(provider="linux", observed=False, gaps=["proc", HOST_CONTROL])
        processes = _processes(self._root, self._core_pid, reveal=False)
        return ProcessSnapshot(
            provider="linux",
            observed=True,
            processes=processes,
            gaps=[HOST_CONTROL],
        )

    def apply(self, request: ProcessRequest) -> ProcessOutcome:
        if request.action == "start":
            return self._start(request)
        if request.action == "command":
            return self._command(request)
        return self._lifecycle(request)

    def _start(self, request: ProcessRequest) -> ProcessOutcome:
        refusal = refused_program(request.argv)
        if refusal is not None:
            return self._refuse(refusal, None)
        if not request.argv:
            return self._refuse("process start requires a program", None)
        return ProcessOutcome(
            applied=False,
            permitted=True,
            reason=HOST_CONTROL,
            state=self.snapshot(),
        )

    def _lifecycle(self, request: ProcessRequest) -> ProcessOutcome:
        if request.pid is None:
            return self._refuse(_MISSING, None)
        record = _one(self._root, request.pid, self._core_pid, reveal=False)
        if record is None:
            return self._refuse(_MISSING, request.pid)
        if record.protection is not None:
            return self._refuse(protection_reason(record.protection), request.pid)
        return self._refuse(_NOT_OWNED, request.pid)

    def _command(self, request: ProcessRequest) -> ProcessOutcome:
        if request.pid is None:
            return self._refuse(_MISSING, None)
        record = _one(self._root, request.pid, self._core_pid, reveal=request.reveal)
        if record is None:
            return self._refuse(_MISSING, request.pid)
        line = record.command_line if request.reveal else None
        permitted = "command line is permitted"
        hidden = "command line is not permitted"
        return ProcessOutcome(
            applied=line is not None,
            permitted=request.reveal,
            reason=permitted if request.reveal else hidden,
            state=self.snapshot(),
            command_line=line,
        )

    def _refuse(self, reason: str, pid: int | None) -> ProcessOutcome:
        events: list[ProcessEvent] = []
        if "protected" in reason:
            payload: dict[str, object] = {}
            if pid is not None:
                payload["pid"] = pid
            events.append(ProcessEvent(type="process.protected", payload=payload))
        return ProcessOutcome(
            applied=False,
            permitted=False,
            reason=reason,
            state=self.snapshot(),
            events=events,
        )


def _processes(root: Path, core_pid: int | None, *, reveal: bool) -> list[ProcessRecord]:
    proc = root / "proc"
    found: list[ProcessRecord] = []
    owners = _owners(root)
    boot = _boot_time(root)
    try:
        entries = list(proc.iterdir())
    except OSError:
        return []
    for entry in entries:
        if not entry.name.isdecimal():
            continue
        record = _read(entry, core_pid, owners, boot, reveal=reveal)
        if record is None:
            continue
        found.append(record)
        if len(found) >= 400:
            break
    return _with_children(found)


def _one(root: Path, pid: int, core_pid: int | None, *, reveal: bool) -> ProcessRecord | None:
    entry = root / "proc" / str(pid)
    if not entry.is_dir():
        return None
    return _read(entry, core_pid, _owners(root), _boot_time(root), reveal=reveal)


def _read(
    entry: Path,
    core_pid: int | None,
    owners: dict[int, str],
    boot: int | None,
    *,
    reveal: bool,
) -> ProcessRecord | None:
    parsed = _stat(entry / "stat")
    if parsed is None:
        return None
    name, uid, rss = _status(entry / "status")
    shown = name or parsed.name
    owner = owners.get(int(uid), uid) if uid is not None else "unknown"
    executable = _executable(entry / "exe", shown)
    kind = protection_for(
        pid=parsed.pid,
        parent_pid=parsed.parent,
        name=executable,
        core_pid=core_pid,
    )
    line = _cmdline(entry / "cmdline") if reveal else None
    started = None
    if boot is not None:
        started = datetime.fromtimestamp(boot + parsed.start / _HZ, tz=UTC).isoformat()
    return ProcessRecord(
        pid=parsed.pid,
        executable=executable,
        command_line=line,
        command_permitted=reveal and line is not None,
        cpu_percent=None,
        cpu_seconds=(parsed.utime + parsed.stime) / _HZ,
        ram_bytes=rss,
        owner=owner,
        parent_pid=parsed.parent,
        state=_STATES.get(parsed.state, "unknown"),
        started_at=started,
        limits=_limits(entry / "limits"),
        protection=kind,
    )


def _with_children(records: list[ProcessRecord]) -> list[ProcessRecord]:
    children: dict[int, list[int]] = {}
    for record in records:
        if record.parent_pid is not None:
            children.setdefault(record.parent_pid, []).append(record.pid)
    return sorted(
        (
            record.model_copy(update={"children": sorted(children.get(record.pid, []))})
            for record in records
        ),
        key=lambda item: item.pid,
    )


class _ParsedStat:
    def __init__(
        self, pid: int, name: str, state: str, parent: int, utime: int, stime: int, start: int
    ) -> None:
        self.pid = pid
        self.name = name
        self.state = state
        self.parent = parent
        self.utime = utime
        self.stime = stime
        self.start = start


def _stat(path: Path) -> _ParsedStat | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    opened = text.find("(")
    closed = text.rfind(")")
    if opened < 1 or closed < opened:
        return None
    try:
        pid = int(text[:opened].strip())
    except ValueError:
        return None
    fields = text[closed + 2 :].split()
    if len(fields) <= 19:
        return None
    try:
        return _ParsedStat(
            pid=pid,
            name=text[opened + 1 : closed],
            state=fields[0],
            parent=int(fields[1]),
            utime=int(fields[11]),
            stime=int(fields[12]),
            start=int(fields[19]),
        )
    except ValueError:
        return None


def _status(path: Path) -> tuple[str | None, str | None, int | None]:
    name: str | None = None
    uid: str | None = None
    rss: int | None = None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return name, uid, rss
    for line in lines:
        if line.startswith("Name:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("Uid:"):
            parts = line.split()
            if len(parts) > 1 and parts[1].isdecimal():
                uid = parts[1]
        elif line.startswith("VmRSS:"):
            parts = line.split()
            if len(parts) > 1 and parts[1].isdecimal():
                rss = int(parts[1]) * 1024
    return name, uid, rss


def _executable(path: Path, fallback: str) -> str:
    try:
        target = os.readlink(path)
    except OSError:
        return fallback
    name = Path(target).name
    return name or fallback


def _cmdline(path: Path) -> str | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    text = raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
    return text or None


def _limits(path: Path) -> ResourceLimits:
    values: dict[str, int | None] = {
        "cpu_seconds": None,
        "address_bytes": None,
        "open_files": None,
        "processes": None,
    }
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ResourceLimits()
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 4:
            continue
        label = " ".join(parts[:-3]).lower()
        field = _LIMITS.get(label)
        if field is None:
            continue
        soft = parts[-3].lower()
        if soft.isdecimal():
            values[field] = int(soft)
    return ResourceLimits(
        cpu_seconds=values["cpu_seconds"],
        address_bytes=values["address_bytes"],
        open_files=values["open_files"],
        processes=values["processes"],
    )


def _owners(root: Path) -> dict[int, str]:
    found: dict[int, str] = {}
    try:
        lines = (root / "etc" / "passwd").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return found
    for line in lines:
        parts = line.split(":")
        if len(parts) < 3 or not parts[2].isdecimal():
            continue
        found[int(parts[2])] = parts[0]
    return found


def _boot_time(root: Path) -> int | None:
    try:
        lines = (root / "proc" / "stat").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in lines:
        if line.startswith("btime "):
            value = line.split(None, 1)[1].strip()
            if value.isdecimal():
                return int(value)
    return None
