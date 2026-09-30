"""Read-only system diagnostic.

Each line passes only when its probe succeeds. NVIDIA is not contacted.
A missing credential does not hide a failed kernel, desktop, or core.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from core.models.types import ProviderError
from core.orchestrator.service import OMNE

CHECKS = (
    "Kernel",
    "Filesystem",
    "Network",
    "Graphics",
    "Audio",
    "Input",
    "OMNE Core",
    "Cortex",
    "Memory",
    "Agent Runtime",
    "Model Router",
    "NVIDIA Provider",
    "Desktop",
    "Browser",
    "Recovery",
)
_SHELL_URL = "http://127.0.0.1:4173/"
_DESKTOP_MARKER = 'id="desktop"'
_DESKTOP_SURFACE = "surface=desktop"


@dataclass(frozen=True)
class Diagnostic:
    """One doctor report."""

    checks: tuple[tuple[str, bool], ...]

    @property
    def ready(self) -> bool:
        return all(passed for _name, passed in self.checks)


def render(report: Diagnostic) -> str:
    """Format the report the operator reads after boot."""

    lines = ["OMNE SYSTEM DIAGNOSTIC", ""]
    for name, passed in report.checks:
        lines.append(f"[{'PASS' if passed else 'FAIL'}] {name}")
    lines.append("")
    lines.append(f"SYSTEM STATUS: {'READY' if report.ready else 'NOT READY'}")
    lines.append("")
    return "\n".join(lines)


def diagnose(
    runtime: OMNE,
    *,
    root: Path = Path("/"),
    data_dir: Path,
    workspace: Path,
    shell_text: str | None = None,
) -> Diagnostic:
    """Probe the machine and the running core. This does not start QEMU."""

    nvidia = runtime.nvidia_status()
    display = runtime.display_view()
    audio = runtime.audio_view()
    browser = runtime.browser_view()
    recovery = runtime.recovery_view()
    models = runtime.model_views()
    agents = runtime.agent_views()
    surface = _surface(display)
    body = shell_text if shell_text is not None else _fetch_shell(_SHELL_URL)
    results = {
        "Kernel": _kernel(root),
        "Filesystem": _filesystem(root, data_dir, workspace),
        "Network": _network(root),
        "Graphics": _graphics(root),
        "Audio": _audio(root, audio),
        "Input": _input(root),
        "OMNE Core": bool(agents) and bool(models),
        "Cortex": _cortex(runtime, nvidia),
        "Memory": (data_dir / "memory.sqlite").is_file(),
        "Agent Runtime": any(
            item.get("id") == "coding" and item.get("enabled") is True for item in agents
        ),
        "Model Router": any(
            item.get("availability") == "available" and _has_reasoning(item) for item in models
        ),
        "NVIDIA Provider": _nvidia_provider(models, nvidia),
        "Desktop": _DESKTOP_MARKER in body and _DESKTOP_SURFACE in surface,
        "Browser": _browser(browser),
        "Recovery": recovery.get("state") == "NORMAL" and recovery.get("data_erased") is False,
    }
    return Diagnostic(tuple((name, results[name]) for name in CHECKS))


def _cortex(runtime: OMNE, nvidia: Mapping[str, object]) -> bool:
    """Exercise the decision path without calling NVIDIA."""

    if nvidia.get("nvidia") == "CONFIGURED":
        return any(
            item.get("availability") == "available" and _has_reasoning(item)
            for item in runtime.model_views()
        )
    try:
        decision = asyncio.run(runtime.reason("doctor"))
    except (ProviderError, RuntimeError, ValueError, OSError):
        return False
    return decision.provider == "mock"


def _nvidia_provider(models: list[dict[str, object]], nvidia: Mapping[str, object]) -> bool:
    """The provider is installed. Inference is not run from doctor."""

    registered = any(item.get("provider") == "nvidia" for item in models)
    return (
        registered
        and nvidia.get("inference") == "NOT RUN"
        and nvidia.get("nvidia") in {"CONFIGURED", "NOT CONFIGURED"}
    )


def _browser(view: Mapping[str, object]) -> bool:
    if view.get("observed") is not True:
        return False
    applications = view.get("applications")
    layers = view.get("layers")
    return bool(applications) or bool(layers)


def _has_reasoning(model: Mapping[str, object]) -> bool:
    capabilities = model.get("capabilities")
    return isinstance(capabilities, list) and "reasoning" in capabilities


def _surface(display: Mapping[str, object]) -> str:
    surface = display.get("surface")
    if not isinstance(surface, Mapping):
        return ""
    uri = surface.get("uri")
    return uri if isinstance(uri, str) else ""


def _kernel(root: Path) -> bool:
    return "Linux" in _read(root / "proc" / "version")


def _filesystem(root: Path, data_dir: Path, workspace: Path) -> bool:
    mounted = False
    for line in _read(root / "proc" / "mounts").splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1] == "/":
            mounted = True
            break
    return mounted and data_dir.is_dir() and workspace.is_dir() and os.access(data_dir, os.W_OK)


def _network(root: Path) -> bool:
    net = root / "sys" / "class" / "net"
    if not net.is_dir():
        return False
    try:
        names = list(net.iterdir())
    except OSError:
        return False
    for path in names:
        if path.name == "lo":
            continue
        if _read(path / "operstate").strip() == "up":
            return True
    return False


def _graphics(root: Path) -> bool:
    drm = root / "sys" / "class" / "drm"
    if not drm.is_dir():
        return False
    try:
        names = [path.name for path in drm.iterdir()]
    except OSError:
        return False
    return any(name.startswith("card") and "-" not in name for name in names)


def _audio(root: Path, view: Mapping[str, object]) -> bool:
    if view.get("capture_open") is True:
        return False
    if _read(root / "proc" / "asound" / "cards").strip():
        return True
    sound = root / "sys" / "class" / "sound"
    if not sound.is_dir():
        return False
    try:
        return any(path.name.startswith("card") for path in sound.iterdir())
    except OSError:
        return False


def _input(root: Path) -> bool:
    text = _read(root / "proc" / "bus" / "input" / "devices").lower()
    return "kbd" in text or "mouse" in text


def _fetch_shell(url: str) -> str:
    request = Request(url, method="GET")
    try:
        with urlopen(request, timeout=2) as response:
            payload = response.read()
        if not isinstance(payload, bytes):
            return ""
        return payload.decode("utf-8", errors="replace")
    except (OSError, URLError, UnicodeError, ValueError, TimeoutError):
        return ""


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
