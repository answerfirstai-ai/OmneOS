"""Process inspection stays redacted and does not signal a protected process."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.conftest import ROOT
from tests.support import runtime_settings

from core.agents.registry import AgentRegistry
from core.api.routes import route_get, route_post
from core.api.runtime import build_OMNE
from core.events.bus import EventBus
from core.permissions.audit import AuditLog
from core.permissions.evaluator import PermissionEvaluator
from core.permissions.policies import PermissionDecision, PermissionRequest, decide
from core.tools import build_registry
from core.tools.base import ToolContext
from core.tools.gateway import ToolGateway
from core.tools.processes import ProcessListTool
from omne.processes.model import ProcessRequest
from omne.processes.providers.linux import LinuxProcessProvider
from omne.processes.providers.mock import MockProcessProvider
from omne.processes.select import process_service, select_provider
from omne.processes.service import (
    ProcessService,
    admit_resources,
    application_id_for,
    worker_id_for,
)

_SECRET = "https://user:secret@example.invalid"


def test_mock_refuses_protected_and_unowned_processes() -> None:
    events: list[tuple[str, dict[str, object]]] = []

    def sink(event_type: str, payload: dict[str, object]) -> None:
        events.append((event_type, payload))

    service = ProcessService(MockProcessProvider(), sink=sink)
    protected = {
        1: "pid 1 is protected",
        2: "kernel process is protected",
        100: "system service is protected",
        200: "security service is protected",
        300: "desktop session is protected",
        400: "OMNE Core is protected",
    }
    for pid, reason in protected.items():
        outcome = service.apply(_stop(pid), {}, "testing", permitted=True)
        assert outcome.applied is False
        assert outcome.permitted is False
        assert outcome.reason == reason
        assert outcome.events[0].type == "process.protected"
        assert outcome.events[0].payload["pid"] == pid

    firefox = service.apply(_stop(500), {}, "testing", permitted=True)
    assert firefox.reason == "process is not owned by an OMNE worker"
    assert firefox.events == []
    rendered = json.dumps(events)
    assert "secret" not in rendered


def test_mock_refuses_a_shell_and_a_protected_program() -> None:
    provider = MockProcessProvider()
    shell = provider.apply(_start(["/bin/bash", "-c", "echo"]))
    guarded = provider.apply(_start(["sshd"]))
    init = provider.apply(_start(["systemd"]))

    assert shell.permitted is False
    assert shell.reason == "process start does not accept a shell"
    assert guarded.reason == "protected program cannot be started"
    assert init.reason == "protected program cannot be started"
    assert guarded.events[0].type == "process.protected"


def test_owned_process_tracks_worker_and_hides_the_command_line() -> None:
    events: list[tuple[str, dict[str, object]]] = []
    service = ProcessService(
        MockProcessProvider(),
        sink=lambda event_type, payload: events.append((event_type, payload)),
        worker_for=lambda task_id: worker_id_for(
            task_id, [("worker-9", "task-9", "RUNNING"), ("worker-8", "task-8", "IDLE")]
        ),
        application_for=lambda program: application_id_for(
            program, [("firefox", "/usr/bin/firefox"), ("files", "/usr/bin/nautilus")]
        ),
    )
    started = service.apply(
        ProcessRequest(
            action="start",
            agent_id="coding",
            task_id="task-9",
            argv=["/usr/bin/firefox", _SECRET],
        ),
        {},
        "testing",
        permitted=True,
    )

    assert started.applied is True
    record = next(item for item in started.state.processes if item.pid == 61001)
    assert record.owned is True
    assert record.ownership.agent_id == "coding"
    assert record.ownership.worker_id == "worker-9"
    assert record.ownership.task_id == "task-9"
    assert record.ownership.application_id == "firefox"
    assert record.command_line is None
    assert record.parent_pid is None
    assert _SECRET not in json.dumps(started.state.model_dump())

    hidden = service.apply(_command(61001, reveal=False), {}, "testing", permitted=True)
    assert hidden.command_line is None
    assert hidden.permitted is False
    revealed = service.apply(_command(61001, reveal=True), {}, "testing", permitted=True)
    assert revealed.command_line == f"/usr/bin/firefox {_SECRET}"
    assert _SECRET not in json.dumps(revealed.state.model_dump())
    assert revealed.events == []

    stopped = service.apply(_stop(61001), {}, "testing", permitted=True)
    restarted = service.apply(_restart(61001), {}, "testing", permitted=True)
    assert stopped.applied is True
    assert restarted.applied is True
    names = [event_type for event_type, _payload in events]
    assert names == ["process.started", "process.stopped", "process.restarted"]
    assert _SECRET not in json.dumps(events)


def test_compute_denial_does_not_create_a_process() -> None:
    assert admit_resources(None, None) == ("ALLOW", "resources allow a process")
    assert admit_resources(95, 256)[0] == "DENY"
    assert admit_resources(10, 63)[0] == "DENY"
    service = ProcessService(MockProcessProvider(), admit=lambda: ("DENY", "cpu is too high"))
    before = {item.pid for item in service.status().processes}
    outcome = service.apply(_start(["firefox"]), {}, "testing", permitted=True)

    assert outcome.applied is False
    assert outcome.reason == "cpu is too high"
    assert {item.pid for item in service.status().processes} == before


def test_permission_denies_shells_pid_one_and_unauthenticated_callers() -> None:
    shell = decide(_request("process.start", {"argv": ["bash", "-c", _SECRET]}))
    restart = decide(_request("process.restart", {"pid": 1}, grants=["restart"]))
    production = decide(
        _request("process.restart", {"pid": 40}, grants=["restart"], environment="production")
    )
    missing = decide(_request("process.command", {"pid": 40}, grants=["list"]))

    assert shell.decision is PermissionDecision.DENY
    assert shell.reason == "process start does not accept a shell"
    assert restart.decision is PermissionDecision.DENY
    assert restart.reason == "refusing to signal pid 1 or below"
    assert production.decision is PermissionDecision.DENY
    assert missing.decision is PermissionDecision.DENY
    assert "secret" not in shell.reason


def test_linux_reads_proc_without_signaling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixture(tmp_path)
    before = _tree(tmp_path)

    def explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("host process control")

    monkeypatch.setattr("subprocess.run", explode)
    monkeypatch.setattr("subprocess.Popen", explode)
    monkeypatch.setattr("os.kill", explode)
    provider = LinuxProcessProvider(root=tmp_path, core_pid=30)
    state = provider.snapshot()
    started = provider.apply(_start(["firefox"]))
    stopped = provider.apply(_stop(1))
    ordinary = provider.apply(_stop(40))
    revealed = provider.apply(_command(40, reveal=True))

    assert _tree(tmp_path) == before
    by_pid = {item.pid: item for item in state.processes}
    assert by_pid[1].protection == "pid1"
    assert by_pid[2].protection == "kernel"
    assert by_pid[10].protection == "security"
    assert by_pid[20].protection == "desktop_session"
    assert by_pid[30].protection == "omne_core"
    firefox = by_pid[40]
    assert firefox.protection is None
    assert firefox.executable == "firefox"
    assert firefox.owner == "user"
    assert firefox.parent_pid == 20
    assert firefox.children == [41]
    assert firefox.ram_bytes == 1234 * 1024
    assert firefox.cpu_seconds == pytest.approx(0.02)
    assert firefox.limits.open_files == 1024
    assert firefox.limits.cpu_seconds is None
    assert firefox.command_line is None
    assert firefox.started_at == datetime.fromtimestamp(1700000000.5, tz=UTC).isoformat()
    assert state.control_installed is False
    rendered = json.dumps(state.model_dump())
    assert "secret" not in rendered
    assert "secret-hash" not in rendered
    assert "/bin/bash" not in rendered
    assert started.applied is False
    assert started.permitted is True
    assert started.reason == "host process control is not installed"
    assert stopped.permitted is False
    assert stopped.events[0].type == "process.protected"
    assert ordinary.reason == "process is not owned by an OMNE worker"
    assert revealed.command_line == f"firefox {_SECRET}"
    assert _SECRET not in json.dumps(revealed.state.model_dump())
    for path in Path("omne/processes").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "subprocess" not in text
        assert "os.kill" not in text
        assert "os.system" not in text
        assert "shell=True" not in text
    for path in Path("core/tools/processes").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "subprocess" not in text
        assert "os.kill" not in text
        assert "os.system" not in text
        assert "shell=True" not in text


def test_list_omits_arguments_until_command_is_granted(tmp_path: Path) -> None:
    service = process_service(
        "testing",
        worker_for=lambda task_id: "worker-1" if task_id == "task" else None,
        application_for=lambda program: "firefox" if Path(program).name == "firefox" else None,
    )
    gateway = ToolGateway(
        build_registry(processes=service), PermissionEvaluator(), AuditLog(), EventBus()
    )
    context = ToolContext(
        task_id="task",
        agent_id="coding",
        user="local",
        workspace_root=tmp_path,
        timeout_seconds=5,
    )
    grants = {"process": ["list", "start", "signal", "restart", "command"]}
    started = gateway.invoke(
        tool_id="process.start",
        arguments={"argv": ["firefox", _SECRET], "command": "bash"},
        context=context,
        grants=grants,
        environment="testing",
        approved=True,
    )
    assert started.ok is False
    started = gateway.invoke(
        tool_id="process.start",
        arguments={"argv": ["firefox", _SECRET]},
        context=context,
        grants=grants,
        environment="testing",
        approved=True,
    )
    assert started.ok is True
    assert started.output["ownership"]["worker_id"] == "worker-1"
    assert started.output["ownership"]["application_id"] == "firefox"
    assert _SECRET not in json.dumps(started.output)
    listed = ProcessListTool(service).execute({"limit": 50}, context)
    assert _SECRET not in json.dumps(listed)
    assert all("command_line" not in row for row in listed["processes"])
    denied = gateway.invoke(
        tool_id="process.command",
        arguments={"pid": started.output["pid"]},
        context=context,
        grants={"process": ["list"]},
        environment="testing",
        approved=True,
    )
    assert denied.ok is False
    shown = gateway.invoke(
        tool_id="process.command",
        arguments={"pid": started.output["pid"]},
        context=context,
        grants=grants,
        environment="testing",
    )
    assert shown.ok is True
    assert shown.output["command_line"] == f"firefox {_SECRET}"
    stopped = gateway.invoke(
        tool_id="process.stop",
        arguments={"pid": started.output["pid"]},
        context=context,
        grants=grants,
        environment="testing",
        approved=True,
    )
    restarted = gateway.invoke(
        tool_id="process.restart",
        arguments={"pid": started.output["pid"]},
        context=context,
        grants=grants,
        environment="testing",
        approved=True,
    )
    assert stopped.ok is True
    assert restarted.ok is True


def test_shipped_agents_do_not_receive_command_or_restart() -> None:
    loaded = AgentRegistry().discover(ROOT / "agents", known_tools=build_registry().ids())
    for agent in loaded:
        grants = agent.permissions.get("process", [])
        assert "command" not in grants
        assert "restart" not in grants


def test_select_provider_follows_the_environment() -> None:
    assert isinstance(select_provider("testing"), MockProcessProvider)
    if sys.platform.startswith("linux"):
        assert isinstance(select_provider("development"), LinuxProcessProvider)
    else:
        assert isinstance(select_provider("development"), MockProcessProvider)


def test_testing_api_is_read_only(tmp_path: Path) -> None:
    omne = build_OMNE(runtime_settings(tmp_path))
    status, body = route_get(omne, "/processes", {})

    assert status.value == 200
    record = body["processes"]
    assert isinstance(record, dict)
    assert record["provider"] == "mock"
    assert record["control_installed"] is False
    assert record["commanded"] is False
    assert record["observed"] is True
    rendered = json.dumps(record)
    assert "secret" not in rendered
    rows = record["processes"]
    assert isinstance(rows, list)
    assert all(item["command_line"] is None for item in rows)
    protections = {item["pid"]: item["protection"] for item in rows}
    assert protections[1] == "pid1"
    assert protections[2] == "kernel"
    posted, payload = route_post(omne, "/processes", {"action": "stop", "pid": 1})
    assert posted.value == 404
    assert payload["error"] == "not_found"


def _request(
    tool_id: str,
    arguments: dict[str, object],
    *,
    grants: list[str] | None = None,
    environment: str = "testing",
) -> PermissionRequest:
    allowed = ["list", "start", "signal", "command"]
    if grants is not None:
        allowed = grants
    return PermissionRequest(
        tool_id=tool_id,
        arguments=arguments,
        grants={"process": allowed},
        environment=environment,
        workspace_root="/workspace",
    )


def _start(argv: list[str]) -> ProcessRequest:
    return ProcessRequest(action="start", agent_id="coding", argv=argv)


def _stop(pid: int) -> ProcessRequest:
    return ProcessRequest(action="stop", agent_id="coding", pid=pid)


def _restart(pid: int) -> ProcessRequest:
    return ProcessRequest(action="restart", agent_id="coding", pid=pid)


def _command(pid: int, *, reveal: bool) -> ProcessRequest:
    return ProcessRequest(action="command", agent_id="coding", pid=pid, reveal=reveal)


def _fixture(root: Path) -> None:
    proc = root / "proc"
    proc.mkdir()
    (proc / "stat").write_text("cpu 0 0\nbtime 1700000000\n", encoding="utf-8")
    (root / "etc").mkdir()
    (root / "etc" / "passwd").write_text(
        "root:x:0:0::/root:/bin/bash\nuser:secret-hash:1000:1000::/home/user:/bin/bash\n",
        encoding="utf-8",
    )
    rows = [
        (1, "systemd", "S", 0, "systemd", "0", None, 0),
        (2, "kthreadd", "S", 0, "kthreadd", "0", None, 0),
        (10, "sshd", "S", 1, "sshd", "0", None, 0),
        (20, "labwc", "S", 1, "labwc", "1000", None, 0),
        (30, "python", "S", 1, "OMNE", "1000", None, 0),
        (40, "firefox", "R", 20, "firefox", "1000", 1234, 50),
        (41, "Web Content", "S", 40, "Web Content", "1000", None, 0),
    ]
    for pid, comm, state, ppid, name, uid, rss, start in rows:
        entry = proc / str(pid)
        entry.mkdir()
        tail = f"{state} {ppid} 0 0 0 -1 0 0 0 0 0 1 1 0 0 20 0 1 0 {start}\n"
        (entry / "stat").write_text(f"{pid} ({comm}) {tail}", encoding="utf-8")
        status = [f"Name:\t{name}", f"Uid:\t{uid} {uid} {uid} {uid}"]
        if rss is not None:
            status.append(f"VmRSS:\t{rss} kB")
        (entry / "status").write_text("\n".join(status) + "\n", encoding="utf-8")
    firefox = proc / "40"
    (firefox / "exe").symlink_to("/usr/bin/firefox")
    (firefox / "cmdline").write_bytes(f"firefox\0{_SECRET}\0".encode())
    (firefox / "limits").write_text(
        "Limit                     Soft Limit           Hard Limit           Units\n"
        "Max cpu time              unlimited            unlimited            seconds\n"
        "Max open files            1024                 4096                 files\n",
        encoding="utf-8",
    )


def _tree(root: Path) -> list[str]:
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
