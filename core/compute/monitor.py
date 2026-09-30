"""Host telemetry.

Values come from the local machine. Missing sources stay null or explicitly
unavailable. This module does not invent measurements.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from core.logging_config import get_logger

logger = get_logger("compute")


class CpuTelemetry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    usage_percent: float | None = None
    count: int | None = None


class MemoryTelemetry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    used_mb: float | None = None
    available_mb: float | None = None
    total_mb: float | None = None


class GpuTelemetry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    available: bool | None = None
    count: int | None = None
    usage_percent: float | None = None
    vram_used_mb: float | None = None
    vram_total_mb: float | None = None


class ThermalTelemetry(BaseModel):
    """A temperature reading. Null means the sensor was not available."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    celsius: float | None = None


class DiskTelemetry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    total_mb: float | None = None
    used_mb: float | None = None
    available_mb: float | None = None


class NetworkInterface(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    rx_bytes: int
    tx_bytes: int


class NetworkTelemetry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    available: bool
    interfaces: list[NetworkInterface] = Field(default_factory=list)


class ResourceSnapshot(BaseModel):
    """One consistent read of host resources."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cpu: CpuTelemetry
    memory: MemoryTelemetry
    gpu: GpuTelemetry
    disk: DiskTelemetry
    network: NetworkTelemetry
    thermal: ThermalTelemetry = Field(default_factory=ThermalTelemetry)


class SystemMonitor:
    """Read CPU, memory, GPU, disk, and network telemetry."""

    def __init__(
        self,
        *,
        root: Path | None = None,
        sample_seconds: float = 0.05,
        cache_ttl: float = 1.0,
    ) -> None:
        self._root = root or Path("/")
        self._sample_seconds = sample_seconds
        self._cache_ttl = cache_ttl
        self._lock = threading.Lock()
        self._cached: tuple[float, ResourceSnapshot] | None = None
        self._cpu_sample: tuple[float, tuple[int, int]] | None = None
        self._nvidia_probed = False
        self._nvidia_command: str | None = None

    def snapshot(self, *, disk_path: Path | None = None) -> ResourceSnapshot:
        if disk_path is not None:
            return self._collect(disk_path)
        now = time.monotonic()
        with self._lock:
            cached = self._cached
            if cached is not None and now - cached[0] < self._cache_ttl:
                return cached[1]
        fresh = self._collect(Path.cwd())
        with self._lock:
            self._cached = (time.monotonic(), fresh)
        return fresh

    def _collect(self, disk_path: Path) -> ResourceSnapshot:
        return ResourceSnapshot(
            cpu=self.cpu(),
            memory=self.memory(),
            gpu=self.gpu(),
            disk=self.disk(disk_path),
            network=self.network(),
            thermal=self.thermal(),
        )

    def cpu(self) -> CpuTelemetry:
        now = time.monotonic()
        current = _read_cpu_times(self._root)
        if current is None:
            return self._cpu(None)
        with self._lock:
            prior = self._cpu_sample
        if prior is not None and now - prior[0] >= self._sample_seconds:
            with self._lock:
                self._cpu_sample = (time.monotonic(), current)
            return self._cpu(usage_from_samples(prior[1], current))
        time.sleep(self._sample_seconds)
        second = _read_cpu_times(self._root)
        if second is None:
            return self._cpu(None)
        with self._lock:
            self._cpu_sample = (time.monotonic(), second)
        return self._cpu(usage_from_samples(current, second))

    def _cpu(self, usage_percent: float | None) -> CpuTelemetry:
        return CpuTelemetry(usage_percent=usage_percent, count=_cpu_count(self._root))

    def thermal(self) -> ThermalTelemetry:
        return ThermalTelemetry(celsius=_read_thermal(self._root))

    def memory(self) -> MemoryTelemetry:
        info = _read_meminfo(self._root)
        if info is None:
            return MemoryTelemetry()
        total_kb = info.get("MemTotal")
        available_kb = info.get("MemAvailable")
        if total_kb is None or available_kb is None:
            return MemoryTelemetry()
        total_mb = total_kb / 1024
        available_mb = available_kb / 1024
        return MemoryTelemetry(
            total_mb=round(total_mb, 1),
            available_mb=round(available_mb, 1),
            used_mb=round(total_mb - available_mb, 1),
        )

    def gpu(self) -> GpuTelemetry:
        command = self._nvidia_binary()
        if command is None:
            return GpuTelemetry(available=False, count=0)
        try:
            completed = subprocess.run(
                [
                    command,
                    "--query-gpu=utilization.gpu,memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.info("gpu telemetry unavailable: %s", exc)
            return GpuTelemetry(available=None)
        if completed.returncode != 0 or not completed.stdout.strip():
            logger.info("nvidia-smi returned no gpu telemetry")
            return GpuTelemetry(available=False, count=0)
        lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        if not lines:
            return GpuTelemetry(available=False, count=0)
        parts = [part.strip() for part in lines[0].split(",")]
        if len(parts) != 3:
            return GpuTelemetry(available=True, count=len(lines))
        return GpuTelemetry(
            available=True,
            count=len(lines),
            usage_percent=_optional_float(parts[0]),
            vram_used_mb=_optional_float(parts[1]),
            vram_total_mb=_optional_float(parts[2]),
        )

    def _nvidia_binary(self) -> str | None:
        with self._lock:
            if self._nvidia_probed:
                return self._nvidia_command
        found = shutil.which("nvidia-smi")
        with self._lock:
            self._nvidia_probed = True
            self._nvidia_command = found
        return found

    def disk(self, path: Path) -> DiskTelemetry:
        try:
            usage = shutil.disk_usage(path)
        except OSError as exc:
            logger.info("disk telemetry unavailable path=%s error=%s", path, exc)
            return DiskTelemetry()
        return DiskTelemetry(
            total_mb=round(usage.total / (1024 * 1024), 1),
            used_mb=round(usage.used / (1024 * 1024), 1),
            available_mb=round(usage.free / (1024 * 1024), 1),
        )

    def network(self) -> NetworkTelemetry:
        path = self._root / "proc" / "net" / "dev"
        if not path.is_file():
            return NetworkTelemetry(available=False)
        interfaces: list[NetworkInterface] = []
        for line in path.read_text(encoding="utf-8").splitlines()[2:]:
            if ":" not in line:
                continue
            name, rest = line.split(":", 1)
            columns = rest.split()
            if len(columns) < 9:
                continue
            interfaces.append(
                NetworkInterface(
                    name=name.strip(), rx_bytes=int(columns[0]), tx_bytes=int(columns[8])
                )
            )
        return NetworkTelemetry(available=True, interfaces=interfaces)


def usage_from_samples(first: tuple[int, int], second: tuple[int, int]) -> float | None:
    """Compute a CPU percent from two ``(idle, total)`` samples."""

    idle_delta = second[0] - first[0]
    total_delta = second[1] - first[1]
    if total_delta <= 0:
        return None
    busy = total_delta - idle_delta
    percent = 100.0 * busy / total_delta
    return round(max(0.0, min(100.0, percent)), 1)


def _cpu_count(root: Path) -> int | None:
    path = root / "proc" / "stat"
    if not path.is_file():
        return None
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("cpu") and len(line) > 3 and line[3].isdigit():
            count += 1
    if count == 0:
        return None
    return count


def _read_thermal(root: Path) -> float | None:
    """Return a CPU zone temperature. Missing or unrelated zones stay null."""

    base = root / "sys" / "class" / "thermal"
    if not base.is_dir():
        return None
    for zone in sorted(base.glob("thermal_zone*")):
        type_path = zone / "type"
        temp_path = zone / "temp"
        if not type_path.is_file() or not temp_path.is_file():
            continue
        try:
            kind = type_path.read_text(encoding="utf-8").strip().lower()
            raw = temp_path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if not any(
            token in kind for token in ("cpu", "x86_pkg", "coretemp", "k10temp", "zenpower")
        ):
            continue
        try:
            milli = int(raw)
        except ValueError:
            continue
        return round(milli / 1000, 1)
    return None


def _read_cpu_times(root: Path) -> tuple[int, int] | None:
    path = root / "proc" / "stat"
    if not path.is_file():
        return None
    line = path.read_text(encoding="utf-8").splitlines()[0]
    parts = [int(item) for item in line.split()[1:]]
    if len(parts) < 4:
        return None
    idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
    return idle, sum(parts)


def _read_meminfo(root: Path) -> dict[str, int] | None:
    path = root / "proc" / "meminfo"
    if not path.is_file():
        return None
    info: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        columns = rest.split()
        if not columns:
            continue
        info[key] = int(columns[0])
    return info


def _optional_float(value: str) -> float | None:
    if value in {"", "[N/A]", "N/A"}:
        return None
    try:
        return float(value)
    except ValueError:
        return None
