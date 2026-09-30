"""Write an OMNE machine root that keeps its state across reboot.

The destination is a directory. Block devices, the live root, and boot paths
are refused. This installer does not format a disk or write a bootloader.
"""

from __future__ import annotations

import json
import shutil
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import TypedDict

from core.config.settings import Settings, load_settings, override_settings

SHELL_SURFACE = "http://127.0.0.1:4173/?surface=desktop"
_REFUSED = ("/boot", "/efi", "/dev", "/proc", "/sys", "/run")
_UNITS = (
    "omne-core.service",
    "omne-shell.service",
    "omne-session.service",
    "omne-boot.service",
    "omne-diag.service",
    "omne.target",
    "omne-reboot.socket",
    "omne-reboot@.service",
    "omne-doctor.service",
)
_EXECUTABLES = (
    ("omne-boot", "usr/bin/omne-boot"),
    ("omne-diag", "usr/bin/omne-diag"),
    ("omne-session", "usr/bin/omne-session"),
    ("omne-prove", "usr/bin/omne-prove"),
    ("OMNE", "usr/bin/OMNE"),
    ("request-reboot", "usr/lib/omne/request-reboot"),
    ("omne-hello", "usr/lib/omne/applications/omne-hello"),
)
_TARGET_WANTS = ("omne-core.service", "omne-shell.service", "omne-boot.service")


class InstallRecord(TypedDict):
    """What the installer claims about the machine it wrote."""

    kind: str
    persistent_state: bool
    volatile_state: bool
    nvidia_boot_dependency: bool
    model_route: str
    environment: str
    shell_surface: str
    session: str
    target: str
    state_dir: str
    disk_format: bool
    bootloader_written: bool
    block_device: bool


class InstallError(Exception):
    """The destination cannot be installed."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def install_machine(source: Path, dest: Path, *, dry_run: bool = False) -> InstallRecord:
    """Copy the operator onto ``dest``. A dry run writes nothing."""

    destination = _refuse(dest, source)
    record = _record()
    if dry_run:
        return record
    _write(source.resolve(), destination, record)
    return record


def boot_settings(root: Path, *, environ: Mapping[str, str] | None = None) -> Settings:
    """Load the installed configuration with state kept on that root."""

    installed = root.resolve()
    settings = load_settings(
        environ={} if environ is None else environ,
        config_path=installed / "etc" / "omne" / "OMNE.toml",
        cwd=installed,
    )
    if installed == Path("/"):
        return settings
    return override_settings(
        settings,
        {
            "workspace_root": _on_root(installed, settings.workspace_root),
            "data_dir": _on_root(installed, settings.data_dir),
            "agents_dir": _on_root(installed, settings.agents_dir),
            "models_dir": _on_root(installed, settings.models_dir),
        },
    )


def _record() -> InstallRecord:
    return {
        "kind": "omne-machine",
        "persistent_state": True,
        "volatile_state": False,
        "nvidia_boot_dependency": False,
        "model_route": "auto",
        "environment": "production",
        "shell_surface": SHELL_SURFACE,
        "session": "omne-session.service",
        "target": "multi-user.target",
        "state_dir": "/var/lib/omne/memory",
        "disk_format": False,
        "bootloader_written": False,
        "block_device": False,
    }


def _write(source: Path, dest: Path, record: InstallRecord) -> None:
    linux = source / "system" / "linux"
    etc = dest / "etc" / "omne"
    units = dest / "etc" / "systemd" / "system"
    etc.mkdir(parents=True, exist_ok=True)
    units.mkdir(parents=True, exist_ok=True)
    (dest / "var" / "lib" / "omne" / "memory").mkdir(parents=True, exist_ok=True)
    (dest / "var" / "lib" / "omne" / "workspace").mkdir(parents=True, exist_ok=True)
    config = _configuration(linux / "OMNE.toml")
    if "nvapi-" in config or "api_key" in config:
        raise InstallError("installed configuration must not carry a credential")
    (etc / "OMNE.toml").write_text(config, encoding="utf-8")
    (etc / "install.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for name in _UNITS:
        shutil.copy2(linux / name, units / name)
    for name, relative in _EXECUTABLES:
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(linux / name, target)
        target.chmod(0o755)
    shutil.copy2(linux / "base", dest / "usr" / "lib" / "omne" / "base")
    sysusers = dest / "usr" / "lib" / "sysusers.d"
    sysusers.mkdir(parents=True, exist_ok=True)
    shutil.copy2(linux / "omne.sysusers", sysusers / "omne.conf")
    _replace_tree(source / "agents", dest / "usr" / "lib" / "omne" / "agents")
    _replace_tree(
        source / "models" / "manifests", dest / "usr" / "lib" / "omne" / "models" / "manifests"
    )
    shell = dest / "usr" / "share" / "omne" / "shell"
    shell.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / "shell" / "index.html", shell / "index.html")
    shutil.copy2(source / "shell" / "styles.css", shell / "styles.css")
    bundle = source / "shell" / "dist"
    if bundle.is_dir():
        _replace_tree(bundle, shell / "dist")
    _link(units / "multi-user.target.wants", "omne.target", "../omne.target")
    _link(
        units / "multi-user.target.wants",
        "omne-session.service",
        "../omne-session.service",
    )
    _link(
        units / "multi-user.target.wants",
        "omne-doctor.service",
        "../omne-doctor.service",
    )
    _link(
        units / "multi-user.target.wants",
        "omne-diag.service",
        "../omne-diag.service",
    )
    for name in _TARGET_WANTS:
        _link(units / "omne.target.wants", name, f"../{name}")
    if (dest / "boot").exists():
        raise InstallError("installed tree must not contain /boot")


def _configuration(path: Path) -> str:
    text = path.read_text(encoding="utf-8").rstrip() + "\n"
    if "model_route" not in text:
        text += 'model_route = "auto"\n'
    return text


def _replace_tree(source: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(
        source,
        dest,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )


def _link(directory: Path, name: str, target: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    link = directory / name
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(target)


def _on_root(root: Path, path: Path) -> Path:
    if path.is_absolute():
        return root.joinpath(*path.parts[1:])
    return path


def _refuse(dest: Path, source: Path) -> Path:
    raw = str(dest).strip()
    if not raw:
        raise InstallError("dest is required")
    try:
        resolved = dest.expanduser().resolve()
        source_root = source.expanduser().resolve()
    except OSError as exc:
        raise InstallError(f"refusing to install into {dest}") from exc
    if resolved == Path("/"):
        raise InstallError("refusing to install into /")
    if resolved == source_root or source_root in resolved.parents:
        raise InstallError("refusing to install into the source tree")
    for prefix in _REFUSED:
        blocked = Path(prefix)
        if resolved == blocked or blocked in resolved.parents:
            raise InstallError(f"refusing to install into {dest}")
    if resolved.exists() and not resolved.is_dir():
        raise InstallError(f"refusing to install into {dest}")
    cursor = resolved
    while True:
        if _block_device(cursor):
            raise InstallError(f"refusing to install onto a block device {cursor}")
        if cursor.parent == cursor:
            break
        cursor = cursor.parent
    return resolved


def _block_device(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except OSError:
        return False
    return stat.S_ISBLK(mode)
