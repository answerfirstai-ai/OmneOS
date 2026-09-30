"""The capability registry follows the inventory and does not assume a machine."""

from __future__ import annotations

from pathlib import Path

from tests.unit.test_hardware import _fixture

from core.compute.manager import ResourceManager
from core.compute.monitor import (
    CpuTelemetry,
    DiskTelemetry,
    GpuTelemetry,
    MemoryTelemetry,
    NetworkTelemetry,
    ResourceSnapshot,
    ThermalTelemetry,
)
from omne.hardware.capabilities import format_bytes, machine_capabilities
from omne.hardware.model import HardwareDevice, HardwareInventory, ResourceUsage
from omne.hardware.providers.linux import LinuxHardwareProvider


def test_one_nvidia_gpu_is_named_without_calling_nvidia() -> None:
    inventory = HardwareInventory(
        provider="linux",
        observed=True,
        devices=[
            _gpu("gpu-card0", vendor="0x10de", driver="nvidia", vram=1024),
            _device("audio-card0", "audio", driver="snd_hda_intel"),
            _device("microphone-pcmC0D0c", "microphone"),
            _device("net-wlan0", "wifi", driver="iwlwifi"),
        ],
    )

    profile = machine_capabilities(inventory).model_dump(mode="json")
    gpu = profile["gpu"]

    assert isinstance(gpu, dict)
    assert gpu["vendor"] == "NVIDIA"
    assert gpu["vendor_id"] == "0x10de"
    assert gpu["vram"] == "1.0 KB"
    assert gpu["vram_bytes"] == 1024
    assert gpu["cuda"] is True
    assert profile["audio"] is True
    assert profile["microphone"] is True
    assert profile["wifi"] is True
    assert profile["ethernet"] is False
    assert profile["camera"] is False


def test_nouveau_and_a_second_gpu_are_not_one_nvidia_machine() -> None:
    inventory = HardwareInventory(
        provider="linux",
        observed=True,
        devices=[
            _gpu("gpu-card0", vendor="0x10de", driver="nouveau", vram=None),
            _gpu("gpu-card1", vendor="0x1af4", driver="virtio-pci", vram=None),
        ],
    )

    gpus = machine_capabilities(inventory).gpu

    assert isinstance(gpus, list)
    assert [item.vendor for item in gpus] == ["NVIDIA", "Red Hat"]
    assert [item.cuda for item in gpus] == [False, False]
    assert gpus[0].vram is None
    assert gpus[1].vendor_id == "0x1af4"


def test_an_unobserved_read_does_not_claim_the_machine_lacks_hardware() -> None:
    inventory = HardwareInventory(provider="linux", observed=False, gaps=["linux"])

    profile = machine_capabilities(inventory)

    assert profile.observed is False
    assert profile.gpu is None
    assert profile.wifi is None
    assert profile.audio is None
    assert profile.drivers.known is False


def test_an_unreadable_gpu_stays_unknown() -> None:
    inventory = HardwareInventory(provider="linux", observed=True, devices=[], gaps=["gpu"])

    assert machine_capabilities(inventory).gpu is None


def test_an_unbound_device_is_listed_and_not_given_a_driver() -> None:
    inventory = HardwareInventory(
        provider="linux",
        observed=True,
        devices=[_device("pci-0000:00:1f.0", "pci", driver=None)],
    )

    drivers = machine_capabilities(inventory).drivers

    assert drivers.known is True
    assert drivers.bound == []
    assert drivers.unbound == ["pci-0000:00:1f.0"]


def test_linux_fixture_profile_matches_that_machine(tmp_path: Path) -> None:
    _fixture(tmp_path)
    profile = machine_capabilities(LinuxHardwareProvider(root=tmp_path).inventory())
    gpu = profile.gpu
    cpu = profile.cpu

    assert isinstance(gpu, dict) is False
    assert profile.gpu is not False
    assert gpu is not None
    assert not isinstance(gpu, list)
    assert gpu.vendor == "NVIDIA"
    assert gpu.cuda is True
    assert gpu.driver == "nvidia"
    assert isinstance(cpu, dict) is False
    assert not isinstance(cpu, list)
    assert cpu is not False and cpu is not None
    assert cpu.vendor == "GenuineIntel"
    assert cpu.cores == 2
    assert cpu.threads == 2
    assert profile.memory is not False and profile.memory is not None
    assert profile.memory.total == "2.0 MB"
    assert profile.motherboard is not False and profile.motherboard is not None
    assert profile.motherboard.vendor == "TestBoard"
    assert profile.motherboard.model == "OMNE Board"
    assert profile.storage is True
    assert profile.ethernet is True
    assert profile.bluetooth is True
    assert profile.keyboard is True
    assert profile.mouse is True
    assert profile.display is True
    assert profile.usb is True
    assert profile.camera is True
    assert profile.drivers.unbound == []
    assert "nvidia" in profile.drivers.bound
    assert "iwlwifi" in profile.drivers.bound


def test_capture_proc_is_a_microphone_when_sysfs_sound_is_absent(tmp_path: Path) -> None:
    path = tmp_path / "proc" / "asound" / "pcm"
    path.parent.mkdir(parents=True)
    path.write_text(
        "00-00: ALC1220 Analog : ALC1220 Analog : playback 1 : capture 1\n",
        encoding="utf-8",
    )

    report = LinuxHardwareProvider(root=tmp_path).inventory()
    microphone = next(device for device in report.devices if device.type == "microphone")

    assert microphone.id == "microphone-pcmC0D0c"
    assert machine_capabilities(report).microphone is True


def test_resource_manager_carries_the_registry_without_using_it_as_telemetry() -> None:
    profile = machine_capabilities(
        HardwareInventory(provider="mock", observed=True, devices=[])
    ).model_dump(mode="json")
    snapshot = ResourceSnapshot(
        cpu=CpuTelemetry(),
        memory=MemoryTelemetry(),
        gpu=GpuTelemetry(),
        disk=DiskTelemetry(),
        network=NetworkTelemetry(available=False),
        thermal=ThermalTelemetry(),
    )

    view = ResourceManager(_Idle(snapshot)).status(snapshot, hardware=profile)

    assert view["hardware"] == profile
    assert view["gpu"]["available"] is None
    assert view["hardware"]["gpu"] is False


def test_format_bytes_uses_the_measured_count() -> None:
    assert format_bytes(None) is None
    assert format_bytes(0) == "0 B"
    assert format_bytes(512) == "512 B"
    assert format_bytes(1024) == "1.0 KB"


class _Idle:
    def __init__(self, snapshot: ResourceSnapshot) -> None:
        self._snapshot = snapshot

    def snapshot(self, *, disk_path: Path | None = None) -> ResourceSnapshot:
        del disk_path
        return self._snapshot


def _gpu(device_id: str, *, vendor: str, driver: str | None, vram: int | None) -> HardwareDevice:
    return HardwareDevice(
        id=device_id,
        type="gpu",
        vendor=vendor,
        driver=driver,
        state="present",
        usage=ResourceUsage(vram_total_bytes=vram),
    )


def _device(device_id: str, device_type: str, *, driver: str | None = None) -> HardwareDevice:
    return HardwareDevice(
        id=device_id,
        type=device_type,  # type: ignore[arg-type]
        driver=driver,
        state="present",
    )
