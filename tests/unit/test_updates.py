"""Signed update catalogs are planned, staged, and rolled back without apt."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from tests.support import runtime_settings

from core.api.main import main
from core.api.routes import route_get, route_post
from core.api.runtime import build_OMNE
from omne.updates.model import UpdatePhase
from omne.updates.service import UpdateRejected, UpdateService


def test_valid_update_is_verified_and_not_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = _signed_tree(tmp_path, channel="omne", version="0.2.0", reboot=False)
    calls = _forbid_host_install(monkeypatch)
    service = UpdateService(tmp_path / "state", host_protected=True)

    plan = service.plan(catalog, dry_run=True)
    staged = service.stage(catalog)

    assert plan.dry_run is True
    assert plan.executed is False
    assert plan.host_updated is False
    assert plan.channels[0].verified is True
    assert plan.channels[0].commands[0][:3] == ["apt-get", "-s", "install"]
    assert staged.host_updated is False
    assert staged.automatic is False
    assert staged.boot_slot == "A"
    assert staged.pending_slot == "B"
    assert staged.reboot_required is False
    assert staged.history[-1].phase is UpdatePhase.STAGED
    assert staged.rollback.available is True
    assert calls
    assert {command[0] for command in calls} <= {"openssl", "dpkg-deb"}
    assert list((tmp_path / "state" / "staging").iterdir())


def test_invalid_signature_is_rejected(tmp_path: Path) -> None:
    catalog = _signed_tree(tmp_path, channel="omne", version="0.2.0", reboot=False)
    signature = catalog / "omne" / "updates.json.sig"
    data = bytearray(signature.read_bytes())
    data[-1] ^= 0x01
    signature.write_bytes(bytes(data))
    service = UpdateService(tmp_path / "state")

    plan = service.plan(catalog, dry_run=True)

    assert plan.channels[0].verified is False
    assert plan.channels[0].phase is UpdatePhase.REJECTED
    assert "signature" in plan.channels[0].reason
    with pytest.raises(UpdateRejected, match="not verified"):
        service.stage(catalog)
    assert not (tmp_path / "state" / "staging").exists()


def test_unsigned_omne_package_is_rejected(tmp_path: Path) -> None:
    catalog = _signed_tree(tmp_path, channel="omne", version="0.2.0", reboot=False)
    (catalog / "omne" / "updates.json.sig").unlink()
    service = UpdateService(tmp_path / "state")

    plan = service.plan(catalog, dry_run=True)

    assert plan.channels[0].reason == "unsigned omne package"
    with pytest.raises(UpdateRejected):
        service.stage(catalog)


def test_corrupt_package_is_rejected(tmp_path: Path) -> None:
    catalog = _signed_tree(tmp_path, channel="omne", version="0.2.0", reboot=False)
    deb = next((catalog / "omne").rglob("*.deb"))
    with deb.open("ab") as handle:
        handle.write(b"corrupt")
    service = UpdateService(tmp_path / "state")

    plan = service.plan(catalog, dry_run=True)

    assert plan.channels[0].reason == "update package is corrupt"
    with pytest.raises(UpdateRejected):
        service.stage(catalog)
    assert service.status().history == []


def test_interrupted_update_does_not_change_the_booted_slot(tmp_path: Path) -> None:
    directory = tmp_path / "state"
    directory.mkdir()
    (directory / "state.json").write_text(
        json.dumps(
            {
                "boot_slot": "A",
                "booted_generation": "boot-1",
                "pending_generation": "pending-1",
                "generations": [
                    {
                        "id": "boot-1",
                        "channel": "omne",
                        "version": "0.1.0",
                        "phase": "installed",
                        "slot": "A",
                        "reboot_required": False,
                        "packages": ["omne-core"],
                        "booted": True,
                    },
                    {
                        "id": "pending-1",
                        "channel": "omne",
                        "version": "0.2.0",
                        "phase": "installing",
                        "slot": "B",
                        "reboot_required": True,
                        "packages": ["omne-core"],
                        "booted": False,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    status = UpdateService(directory).status()
    booted = next(item for item in status.history if item.booted)

    assert status.boot_slot == "A"
    assert status.pending_slot is None
    assert status.host_updated is False
    assert booted.version == "0.1.0"
    assert booted.phase is UpdatePhase.INSTALLED
    interrupted = next(item for item in status.history if item.id == "pending-1")
    assert interrupted.phase is UpdatePhase.INTERRUPTED


def test_rollback_restores_the_booted_generation(tmp_path: Path) -> None:
    first = _signed_tree(tmp_path / "first", channel="omne", version="0.2.0", reboot=False)
    second = _signed_tree(tmp_path / "second", channel="omne", version="0.3.0", reboot=False)
    service = UpdateService(tmp_path / "state")
    service.stage(first)
    committed = service.commit()
    service.stage(second)

    restored = service.rollback()

    assert committed.boot_slot == "B"
    assert committed.history[-1].version == "0.2.0"
    assert restored.boot_slot == "B"
    assert restored.pending_slot is None
    assert restored.history[-1].phase is UpdatePhase.ROLLED_BACK
    assert restored.history[-1].version == "0.3.0"
    booted = next(item for item in restored.history if item.booted)
    assert booted.version == "0.2.0"


def test_pending_rollback_leaves_the_boot_slot(tmp_path: Path) -> None:
    catalog = _signed_tree(tmp_path, channel="linux", version="24.04.1", reboot=False)
    service = UpdateService(tmp_path / "state")
    staged = service.stage(catalog)

    restored = service.rollback()

    assert staged.reboot_required is True
    assert staged.channels[0].commands[0] == ["apt-get", "update"]
    assert "-s" not in staged.channels[0].commands[1]
    assert restored.boot_slot == "A"
    assert restored.pending_slot is None
    assert restored.reboot_required is False
    assert restored.history[-1].phase is UpdatePhase.ROLLED_BACK


def test_channels_stay_separate(tmp_path: Path) -> None:
    catalog = _signed_tree(tmp_path, channel="model", version="1", reboot=False)
    service = UpdateService(tmp_path / "state")

    plan = service.plan(catalog, dry_run=True)

    assert plan.channels[0].channel == "model"
    assert plan.channels[0].commands == []
    assert plan.channels[0].reboot_required is False


def test_install_without_dry_run_is_refused(tmp_path: Path) -> None:
    catalog = _signed_tree(tmp_path, channel="application", version="1.0", reboot=False)
    service = UpdateService(tmp_path / "state")

    with pytest.raises(UpdateRejected, match="refusing to install"):
        service.plan(catalog, dry_run=False)


def test_updates_status_does_not_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    omne = build_OMNE(runtime_settings(tmp_path))
    status, body = route_get(omne, "/updates", {})
    posted, payload = route_post(omne, "/updates", {"action": "install"})

    assert status.value == 200
    record = body["updates"]
    assert isinstance(record, dict)
    assert record["automatic"] is False
    assert record["host_protected"] is True
    assert record["host_updated"] is False
    assert record["channels"] == []
    assert posted.value == 404
    assert payload["error"] == "not_found"

    monkeypatch.chdir(tmp_path)
    assert main(["updates"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["host_updated"] is False
    catalog = _signed_tree(tmp_path / "catalog", channel="omne", version="0.2.0", reboot=False)
    assert main(["updates", "--catalog", str(catalog)]) == 2
    assert "refusing to install" in capsys.readouterr().err
    assert main(["updates", "--dry-run", "--catalog", str(catalog)]) == 0
    dry = json.loads(capsys.readouterr().out)
    assert dry["executed"] is False
    assert dry["dry_run"] is True


def _forbid_host_install(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    real = subprocess.run
    calls: list[list[str]] = []

    def spy(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        command = list(args)
        calls.append(command)
        if command and command[0] in {"apt-get", "apt", "dpkg"}:
            raise AssertionError(command)
        return real(command, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(subprocess, "run", spy)
    return calls


def _signed_tree(root: Path, *, channel: str, version: str, reboot: bool) -> Path:
    catalog = root / "catalog"
    private, public = _keypair(root / "keys")
    channel_dir = catalog / channel
    package_dir = channel_dir / "pkgs"
    package_dir.mkdir(parents=True)
    shutil.copyfile(public, catalog / "trusted.pub")
    if channel == "model":
        artifact = package_dir / "model.bin"
        artifact.write_bytes(b"model-fixture")
        name = "resident"
        filename = "pkgs/model.bin"
    else:
        package = "linux-image-generic" if channel == "linux" else f"omne-{channel}"
        if channel == "omne":
            package = "omne-core"
        if channel == "application":
            package = "editor"
        artifact = _deb(root / "build", package, version)
        shutil.copyfile(artifact, package_dir / artifact.name)
        artifact = package_dir / artifact.name
        name = package
        filename = f"pkgs/{artifact.name}"
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    document = {
        "channel": channel,
        "version": version,
        "reboot_required": reboot,
        "packages": [
            {
                "name": name,
                "version": version,
                "filename": filename,
                "sha256": digest,
                "size": artifact.stat().st_size,
                "reboot": reboot,
            }
        ],
    }
    path = channel_dir / "updates.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    subprocess.run(
        [
            "openssl",
            "pkeyutl",
            "-sign",
            "-inkey",
            str(private),
            "-rawin",
            "-in",
            str(path),
            "-out",
            str(channel_dir / "updates.json.sig"),
        ],
        check=True,
        capture_output=True,
    )
    return catalog


def _keypair(directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    private = directory / "key.pem"
    public = directory / "trusted.pub"
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)],
        check=True,
        capture_output=True,
    )
    return private, public


def _deb(directory: Path, package: str, version: str) -> Path:
    root = directory / package
    debian = root / "DEBIAN"
    debian.mkdir(parents=True)
    (debian / "control").write_text(
        "\n".join(
            [
                f"Package: {package}",
                f"Version: {version}",
                "Architecture: all",
                "Maintainer: OMNE <omne@example.invalid>",
                "Description: fixture",
                "",
            ]
        ),
        encoding="utf-8",
    )
    share = root / "usr" / "share" / "omne"
    share.mkdir(parents=True)
    (share / "fixture.txt").write_text("fixture\n", encoding="utf-8")
    deb = directory / f"{package}_{version}_all.deb"
    subprocess.run(
        ["dpkg-deb", "--build", str(root), str(deb)],
        check=True,
        capture_output=True,
    )
    return deb
