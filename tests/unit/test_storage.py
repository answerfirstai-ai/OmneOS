"""Storage inspection and the path classes filesystem tools must honor."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from tests.support import runtime_settings

from core.api.routes import route_get, route_post
from core.api.runtime import build_OMNE
from core.events.bus import EventBus
from core.permissions.audit import AuditLog
from core.permissions.evaluator import PermissionEvaluator
from core.tools import build_registry
from core.tools.base import ToolContext
from core.tools.gateway import ToolGateway
from omne.storage.classify import PathClass, classify_path
from omne.storage.model import Disk, FilesystemMount, Partition, StorageState
from omne.storage.providers.linux import LinuxStorageProvider
from omne.storage.providers.mock import MockStorageProvider
from omne.storage.select import select_provider
from omne.storage.service import StorageService

_GRANTS = {"filesystem": ["workspace"], "terminal": ["workspace"]}


def test_classes_keep_protected_locations_closed(tmp_path: Path) -> None:
    cases = {
        "/etc/passwd": PathClass.SYSTEM,
        "/proc/1/mem": PathClass.SYSTEM,
        "/sys/block": PathClass.SYSTEM,
        "/boot/grub/grub.cfg": PathClass.BOOT,
        "/boot/efi/EFI/BOOT": PathClass.BOOT,
        "/efi/EFI": PathClass.BOOT,
        "/dev/vda": PathClass.DEVICE,
        "/dev/nvme0n1p1": PathClass.DEVICE,
    }
    for raw, kind in cases.items():
        verdict = classify_path(raw, workspace=tmp_path)
        assert verdict.classification is kind
        assert verdict.allowed is False
    root_workspace = classify_path("/etc/shadow", workspace=Path("/"))
    assert root_workspace.classification is PathClass.SYSTEM
    assert root_workspace.allowed is False
    assert classify_path("/tmp/not-omne", workspace=Path("/")).allowed is False


def test_traversal_symlink_and_unauthorized_paths_are_denied(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("secret", encoding="utf-8")
    (workspace / "escape").symlink_to(outside)
    (workspace / "system").symlink_to("/etc/passwd")
    (workspace / "device").symlink_to("/dev/null")
    nested = workspace / "nested"
    nested.mkdir()

    traversal = classify_path("../outside-secret.txt", workspace=workspace)
    assert traversal.classification is PathClass.USER
    assert traversal.allowed is False
    assert traversal.reason == "path is outside the approved workspace"
    assert not (tmp_path / "nope").exists()

    deep = classify_path("nested/../../outside-secret.txt", workspace=workspace)
    assert deep.allowed is False
    assert deep.resolved.endswith("outside-secret.txt")

    linked = classify_path("escape", workspace=workspace)
    assert linked.classification is PathClass.USER
    assert linked.allowed is False

    system_link = classify_path("system", workspace=workspace)
    assert system_link.classification is PathClass.SYSTEM
    assert system_link.allowed is False

    device_link = classify_path("device", workspace=workspace)
    assert device_link.classification is PathClass.DEVICE
    assert device_link.allowed is False

    own = workspace / "notes.txt"
    allowed = classify_path("notes.txt", workspace=workspace)
    assert allowed.classification is PathClass.OMNE
    assert allowed.allowed is True
    assert allowed.resolved == str(own)


def test_inaccessible_path_is_denied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    locked = tmp_path / "locked"
    locked.write_text("hidden", encoding="utf-8")
    real_stat = os.stat

    def deny_locked(path: object, *args: object, **kwargs: object) -> os.stat_result:
        if os.fspath(path) == os.fspath(locked):  # type: ignore[arg-type]
            raise PermissionError("denied")
        return real_stat(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "stat", deny_locked)
    verdict = classify_path("locked", workspace=tmp_path)

    assert verdict.classification is PathClass.OMNE
    assert verdict.allowed is False
    assert verdict.reason == "path is inaccessible"


def test_filesystem_tools_refuse_protected_and_linked_paths(tmp_path: Path) -> None:
    gateway, context = _gateway(tmp_path)
    outside = tmp_path.parent / "storage-outside.txt"
    (tmp_path / "linked").symlink_to("/etc/passwd")
    passwd_stamp = Path("/etc/passwd").stat().st_mtime_ns

    for raw in (
        "/etc/passwd",
        "/boot/grub/grub.cfg",
        "/dev/sda",
        "../storage-outside.txt",
        "linked",
    ):
        result = gateway.invoke(
            tool_id="filesystem.write",
            arguments={"path": raw, "content": "nope"},
            context=context,
            grants=_GRANTS,
            environment="testing",
        )
        assert result.ok is False
        assert result.error is not None
        assert result.error["code"] == "denied"
        assert "root:" not in json.dumps(result.output)

    assert not outside.exists()
    assert os.readlink(tmp_path / "linked") == "/etc/passwd"
    assert Path("/etc/passwd").stat().st_mtime_ns == passwd_stamp


def test_formatting_commands_stay_denied(tmp_path: Path) -> None:
    gateway, context = _gateway(tmp_path)
    result = gateway.invoke(
        tool_id="terminal.execute",
        arguments={"argv": ["wipefs", "--all", "/dev/vda"]},
        context=context,
        grants=_GRANTS,
        environment="testing",
        approved=True,
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error["code"] == "denied"
    assert "wipefs" in result.error["message"]


def test_storage_events_report_disks_mounts_and_space() -> None:
    provider = MockStorageProvider()
    events: list[str] = []
    service = StorageService(provider, sink=lambda event_type, _payload: events.append(event_type))
    service.inspect()
    provider.set_state(
        StorageState(
            provider="mock",
            observed=True,
            disks=[_disk()],
            partitions=[_partition()],
            filesystems=[_mount(free=10)],
        )
    )
    service.inspect()
    provider.set_state(
        StorageState(
            provider="mock",
            observed=True,
            disks=[_disk()],
            partitions=[_partition()],
            filesystems=[_mount(free=4)],
        )
    )
    service.inspect()

    assert events == [
        "storage.disk.added",
        "storage.partition.added",
        "storage.mount.added",
        "storage.space.changed",
    ]


def test_linux_reader_reports_layout_without_writing(tmp_path: Path) -> None:
    _disk_tree(tmp_path)
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    state = LinuxStorageProvider(root=tmp_path).inspect()
    after = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))

    assert after == before
    assert state.provider == "linux"
    assert state.observed is True
    assert state.raw_access is False
    assert state.formatting is False
    disks = {item.name: item for item in state.disks}
    assert disks["vda"].protected is True
    assert disks["vda"].removable is False
    assert disks["sdb"].removable is True
    assert disks["sdb"].protected is False
    assert "loop0" not in disks
    partitions = {item.name: item for item in state.partitions}
    assert partitions["vda1"].role == "system"
    assert partitions["vda1"].protected is True
    assert partitions["vda2"].role == "boot"
    assert partitions["vdb1"].role == "user"
    assert partitions["vdb1"].protected is False
    mounts = {item.mount: item for item in state.filesystems}
    assert mounts["/"].type == "ext4"
    assert mounts["/"].protected is True
    assert mounts["/"].read_only is False
    assert mounts["/"].used_bytes is not None
    assert mounts["/boot"].read_only is True
    assert mounts["/boot"].role == "boot"
    assert mounts["/boot"].used_bytes is None
    assert mounts["/home"].role == "user"
    assert sum(1 for item in state.filesystems if item.mount == "/home") == 1
    assert mounts["/home"].protected is False
    assert mounts["/dev"].role == "device"
    rendered = json.dumps(state.model_dump())
    assert "root:" not in rendered
    with pytest.raises(ValueError, match="storage mutation"):
        StorageState(provider="linux", observed=True, raw_access=True)


def test_linux_provider_does_not_format_or_open_devices(tmp_path: Path) -> None:
    source = Path(sys.modules["omne.storage.providers.linux"].__file__ or "")
    text = source.read_text(encoding="utf-8")
    for banned in ("subprocess", "write_text", "mkfs", "fdisk", "parted", "wipefs", "grub-install"):
        assert banned not in text
    LinuxStorageProvider(root=tmp_path).inspect()


def test_testing_api_is_read_only(tmp_path: Path) -> None:
    omne = build_OMNE(runtime_settings(tmp_path))
    status, body = route_get(omne, "/storage", {})

    assert status.value == 200
    record = body["storage"]
    assert isinstance(record, dict)
    assert record["provider"] == "mock"
    assert record["disks"] == []
    assert record["filesystems"] == []
    assert record["raw_access"] is False
    assert record["formatting"] is False
    posted, payload = route_post(omne, "/storage", {"action": "format"})
    assert posted.value == 404
    assert payload["error"] == "not_found"


def test_testing_selects_mock_even_on_linux(tmp_path: Path) -> None:
    assert isinstance(select_provider("testing"), MockStorageProvider)
    if sys.platform.startswith("linux"):
        provider = select_provider("development", root=tmp_path)
        assert isinstance(provider, LinuxStorageProvider)
        assert provider.inspect().disks == []


def _gateway(tmp_path: Path) -> tuple[ToolGateway, ToolContext]:
    gateway = ToolGateway(build_registry(), PermissionEvaluator(), AuditLog(), EventBus())
    context = ToolContext(
        task_id="task",
        agent_id="coding",
        user="local",
        workspace_root=tmp_path,
        timeout_seconds=5,
    )
    return gateway, context


def _disk() -> Disk:
    return Disk(
        id="disk-vda",
        name="vda",
        device="/dev/vda",
        size_bytes=1024,
        removable=False,
        read_only=False,
        protected=True,
        rotational=False,
    )


def _partition() -> Partition:
    return Partition(
        id="partition-vda1",
        name="vda1",
        disk="vda",
        device="/dev/vda1",
        size_bytes=512,
        removable=False,
        read_only=False,
        protected=True,
        role="system",
    )


def _mount(free: int) -> FilesystemMount:
    return FilesystemMount(
        id="/",
        device="/dev/vda1",
        mount="/",
        type="ext4",
        read_only=False,
        removable=False,
        used_bytes=20,
        free_bytes=free,
        role="system",
        protected=True,
    )


def _disk_tree(root: Path) -> None:
    _text(
        root / "proc" / "mounts",
        "\n".join(
            [
                "/dev/vda1 / ext4 rw,relatime 0 0",
                "/dev/vda2 /boot ext4 ro 0 0",
                "/dev/vdb1 /home ext4 rw 0 0",
                "/dev/sdb1 /media/usb vfat rw 0 0",
                "udev /dev devtmpfs rw 0 0",
                "/dev/vdb1 /home ext4 rw 0 0",
                "",
            ]
        ),
    )
    for name, removable in (("vda", "0"), ("vdb", "0"), ("sdb", "1"), ("loop0", "0")):
        disk = root / "sys" / "block" / name
        _text(disk / "size", "2048")
        _text(disk / "removable", removable)
        _text(disk / "ro", "0")
        _text(disk / "queue" / "rotational", "0")
    for part in ("vda1", "vda2", "vdb1", "sdb1"):
        disk_name = part.rstrip("0123456789")
        _text(root / "sys" / "block" / disk_name / part / "size", "1024")
        _text(root / "sys" / "block" / disk_name / part / "ro", "0")
    (root / "home").mkdir()
    (root / "media" / "usb").mkdir(parents=True)


def _text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
