"""Setup runs once. Later boots are a password gate. Theme writes stay in state."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from tests.support import runtime_settings

from core.api.main import main
from core.api.routes import route_get, route_post
from core.api.runtime import build_OMNE
from omne.firstboot import (
    DEPENDENCY_NOTE,
    SetupClosed,
    ThemePathError,
    apply_theme,
    boot_gate,
    finish_setup,
    load_theme,
    public_setup,
    unlock,
)
from omne.persist import PersistPathError, attach_state, volatile_discards

PASSWORD = "correct-horse"
PAYLOAD = {
    "name": "Ada",
    "password": PASSWORD,
    "confirm": PASSWORD,
    "theme": {
        "colors": {
            "accent": "#7eb6d6",
            "desktop": "#10202c",
            "glass": "#101820",
            "ink": "#e7f1f6",
            "muted": "#b7c7d1",
        },
        "type": '"Segoe UI", ui-sans-serif, system-ui, sans-serif',
        "wallpaper": "linear-gradient(180deg, #0c1218 0%, #1a2430 55%, #101418 100%)",
    },
}


def _decoys(root: Path) -> list[Path]:
    paths = [
        root / "boot" / "grub" / "grub.cfg",
        root / "efi" / "EFI" / "BOOT" / "BOOTX64.EFI",
        root / "usr" / "lib" / "systemd" / "system" / "omne-core.service",
        root / "usr" / "share" / "omne" / "shell" / "styles.css",
        root / "etc" / "omne" / "OMNE.toml",
        root / "lib" / "systemd" / "system" / "omne.target",
    ]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("untouched\n", encoding="utf-8")
    return paths


def test_setup_runs_once_and_stores_a_verifier(tmp_path: Path) -> None:
    data = tmp_path / "memory"

    assert boot_gate(data) == "setup"
    first = finish_setup(data, PAYLOAD)

    assert first["complete"] is True
    assert first["gate"] == "password"
    assert first["name"] == "Ada"
    assert first["dependency_note"] == DEPENDENCY_NOTE
    assert all(item["weights"] is False for item in first["dependencies"])  # type: ignore[index]
    record = json.loads((data / "setup.json").read_text(encoding="utf-8"))
    assert record["complete"] is True
    assert record["verifier"]["algorithm"] == "scrypt"
    assert PASSWORD not in (data / "setup.json").read_text(encoding="utf-8")
    assert "password" not in record
    public = json.dumps(public_setup(data))
    assert PASSWORD not in public
    assert "verifier" not in public
    files = sorted(path.name for path in data.iterdir() if path.is_file())
    assert files == ["setup.json", "theme.json"]

    before = (data / "setup.json").read_bytes()
    with pytest.raises(SetupClosed):
        finish_setup(data, PAYLOAD)
    assert (data / "setup.json").read_bytes() == before
    assert boot_gate(data) == "password"


def test_password_gate_rejects_a_miss_and_accepts_a_match(tmp_path: Path) -> None:
    data = tmp_path / "memory"
    finish_setup(data, PAYLOAD)
    before = (data / "setup.json").read_bytes()

    assert unlock(data, "wrong-password") is False
    assert (data / "setup.json").read_bytes() == before
    assert unlock(data, PASSWORD) is True
    assert boot_gate(data) == "password"
    assert unlock(tmp_path / "empty", PASSWORD) is False


def test_theme_apply_refuses_boot_package_and_unit_paths(tmp_path: Path) -> None:
    data = tmp_path / "memory"
    data.mkdir()
    decoys = _decoys(tmp_path)
    document = dict(PAYLOAD["theme"])

    for path in decoys:
        with pytest.raises(ThemePathError):
            apply_theme(data, document, destination=path)
        assert path.read_text(encoding="utf-8") == "untouched\n"

    for blocked in (
        Path("/boot"),
        Path("/boot/grub.cfg"),
        Path("/efi/BOOT"),
        Path("/usr/share/omne/shell"),
        Path("/etc/systemd/system/omne-core.service"),
        Path("/lib/systemd/system"),
    ):
        with pytest.raises(ThemePathError):
            apply_theme(blocked, document)
        with pytest.raises(ThemePathError):
            apply_theme(data, document, destination=blocked / "theme.json")

    outside = tmp_path / "boot" / "theme.json"
    outside.write_text("untouched\n", encoding="utf-8")
    link_dir = tmp_path / "linked"
    link_dir.mkdir()
    (link_dir / "theme.json").symlink_to(outside)
    with pytest.raises(ThemePathError):
        apply_theme(link_dir, document)
    assert outside.read_text(encoding="utf-8") == "untouched\n"

    with pytest.raises(ValidationError):
        apply_theme(data, {**document, "wallpaper": "/boot/grub.cfg"})
    assert not (data / "theme.json").exists()

    written = apply_theme(data, document)
    assert written == (data / "theme.json").resolve()
    assert json.loads(written.read_text(encoding="utf-8"))["colors"]["accent"] == "#7eb6d6"
    for path in decoys:
        assert path.read_text(encoding="utf-8") == "untouched\n"
    assert not Path("/boot/theme.json").exists()
    assert load_theme(data).wallpaper.startswith("linear-gradient")


def test_routes_setup_once_then_password(tmp_path: Path) -> None:
    omne = build_OMNE(runtime_settings(tmp_path))
    status, body = route_get(omne, "/setup", {})
    assert status.value == 200
    assert body["gate"] == "setup"
    assert body["complete"] is False

    status, body = route_post(omne, "/setup", PAYLOAD)
    assert status.value == 200
    assert body["gate"] == "password"
    assert body["complete"] is True

    status, body = route_post(omne, "/setup", PAYLOAD)
    assert status.value == 409
    assert body["gate"] == "password"

    status, body = route_post(omne, "/unlock", {"password": "wrong-password"})
    assert status.value == 401
    assert body["unlocked"] is False
    assert body["gate"] == "password"

    status, body = route_post(omne, "/unlock", {"password": PASSWORD})
    assert status.value == 200
    assert body["unlocked"] is True
    assert body["gate"] == "desktop"

    text = (tmp_path / "memory" / "setup.json").read_text(encoding="utf-8")
    assert PASSWORD not in text
    assert (tmp_path / "memory" / "theme.json").is_file()
    status, rejected = route_post(
        omne,
        "/theme",
        {**PAYLOAD["theme"], "wallpaper": "/etc/systemd/system/omne.service"},
    )
    assert status.value == 400
    assert "linear-gradient" in (tmp_path / "memory" / "theme.json").read_text(encoding="utf-8")
    assert rejected["error"] == "theme was not accepted"


def test_theme_command_writes_only_the_data_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "theme-src.json"
    source.write_text(json.dumps(PAYLOAD["theme"]), encoding="utf-8")
    original = source.read_text(encoding="utf-8")

    assert main(["theme", "apply", str(source)]) == 0
    captured = capsys.readouterr().out
    assert '"applied": true' in captured
    written = tmp_path / "memory" / "theme.json"
    assert written.is_file()
    assert source.read_text(encoding="utf-8") == original
    assert not (tmp_path / "boot").exists()
    assert not (tmp_path / "usr").exists()

    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps({**PAYLOAD["theme"], "wallpaper": "/boot/grub.cfg"}),
        encoding="utf-8",
    )
    assert main(["theme", "apply", str(bad)]) == 2
    assert "gradient" in capsys.readouterr().err
    assert json.loads(written.read_text(encoding="utf-8"))["colors"]["accent"] == "#7eb6d6"


def test_volatile_reboot_keeps_the_setup_flag_and_verifier(tmp_path: Path) -> None:
    assert volatile_discards(Path("/var/log/journal")) is True
    assert volatile_discards(Path("/var/lib/omne/memory/setup.json")) is False
    persistent = tmp_path / "OMNE-STATE"
    persistent.mkdir()
    finish_setup(persistent / "memory", PAYLOAD)

    volatile = tmp_path / "var"
    first = attach_state(volatile, persistent)
    assert boot_gate(first / "memory") == "password"
    assert unlock(first / "memory", PASSWORD) is True

    second = attach_state(volatile, persistent)
    assert boot_gate(second / "memory") == "password"
    assert unlock(second / "memory", "wrong-password") is False
    assert unlock(second / "memory", PASSWORD) is True
    assert (persistent / "memory" / "setup.json").is_file()
    assert boot_gate(tmp_path / "wiped" / "memory") == "setup"
    with pytest.raises(PersistPathError):
        attach_state(Path("/var"), persistent)
