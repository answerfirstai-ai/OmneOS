"""Hardware discovery reads Linux facts and does not invent the rest."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from tests.support import runtime_settings

from core.api.routes import route_get, route_post
from core.api.runtime import build_OMNE
from omne.hardware.model import HardwareDevice
from omne.hardware.providers.linux import LinuxHardwareProvider
from omne.hardware.providers.mock import MockHardwareProvider
from omne.hardware.select import select_provider
from omne.hardware.service import HardwareService


def test_mock_starts_empty_and_reports_hotplug() -> None:
    provider = MockHardwareProvider()
    events: list[tuple[str, dict[str, object]]] = []
    service = HardwareService(provider, sink=lambda kind, payload: events.append((kind, payload)))

    first = service.inventory()
    assert first.provider == "mock"
    assert first.observed is True
    assert first.drivers_modified is False
    assert first.devices == []
    assert events == []

    cpu = _device("cpu-package-0", "cpu", state="online")
    provider.set_devices([cpu])
    second = service.inventory()
    assert [device.id for device in second.devices] == ["cpu-package-0"]
    assert events == [("hardware.added", {"id": "cpu-package-0", "type": "cpu"})]

    provider.set_devices([_device("cpu-package-0", "cpu", state="offline")])
    service.inventory()
    assert events[-1][0] == "hardware.changed"
    assert events[-1][1]["fields"] == ["state"]

    provider.set_devices([])
    service.inventory()
    assert events[-1] == ("hardware.removed", {"id": "cpu-package-0", "type": "cpu"})


def test_an_unobserved_read_does_not_remove_devices() -> None:
    provider = MockHardwareProvider([_device("memory", "memory")])
    service = HardwareService(provider, sink=lambda _kind, _payload: None)
    service.inventory()
    provider.inventory = lambda: _unobserved()  # type: ignore[method-assign]
    report = service.inventory()

    assert report.observed is False
    assert report.devices == []
    assert service.inventory().observed is False


def test_linux_fixture_reports_present_hardware_only(tmp_path: Path) -> None:
    _fixture(tmp_path)
    report = LinuxHardwareProvider(root=tmp_path).inventory()

    assert report.provider == "linux"
    assert report.observed is True
    assert report.drivers_modified is False
    assert report.gaps == []
    by_id = {device.id: device for device in report.devices}
    assert set(by_id) == {
        "cpu-package-0",
        "memory",
        "gpu-card0",
        "monitor-card0-HDMI-A-1",
        "keyboard-input0",
        "mouse-input1",
        "usb-1-2",
        "pci-0000:00:02.0",
        "storage-vda",
        "net-enp0s4",
        "net-wlan0",
        "bluetooth-hci0",
        "audio-card0",
        "camera-video0",
        "power-BAT0",
        "power-ADP0",
    }
    cpu = by_id["cpu-package-0"]
    assert cpu.vendor == "GenuineIntel"
    assert cpu.model == "Test CPU"
    assert cpu.state == "online"
    assert cpu.driver is None
    assert "threads:2" in cpu.capabilities
    assert "cores:2" in cpu.capabilities
    assert "flag:fpu" in cpu.capabilities
    assert cpu.usage.frequency_hz == 2_200_000_000
    assert cpu.temperature_c == 45.123
    memory = by_id["memory"]
    assert memory.vendor is None
    assert memory.usage.total_bytes == 2048 * 1024
    assert memory.usage.available_bytes == 1024 * 1024
    assert memory.usage.used_bytes == 1024 * 1024
    gpu = by_id["gpu-card0"]
    assert gpu.vendor == "0x10de"
    assert gpu.model == "0x1b80"
    assert gpu.driver == "nvidia"
    assert gpu.usage.vram_total_bytes == 1024
    assert gpu.usage.vram_used_bytes == 0
    assert by_id["monitor-card0-HDMI-A-1"].state == "connected"
    assert "mode:1920x1080" in by_id["monitor-card0-HDMI-A-1"].capabilities
    assert by_id["keyboard-input0"].model == "Test Keyboard"
    assert by_id["mouse-input1"].type == "mouse"
    usb = by_id["usb-1-2"]
    assert usb.vendor == "046d"
    assert usb.model == "Unifying Receiver"
    assert "manufacturer:Logitech" in usb.capabilities
    assert by_id["pci-0000:00:02.0"].driver == "i915"
    assert by_id["pci-0000:00:02.0"].state == "online"
    disk = by_id["storage-vda"]
    assert disk.usage.total_bytes == 2048 * 512
    assert disk.state == "running"
    assert disk.driver == "virtio_blk"
    assert by_id["net-enp0s4"].type == "ethernet"
    assert by_id["net-enp0s4"].state == "up"
    assert "mac:02:00:00:00:00:01" in by_id["net-enp0s4"].capabilities
    assert by_id["net-wlan0"].type == "wifi"
    assert by_id["net-wlan0"].driver == "iwlwifi"
    assert by_id["bluetooth-hci0"].state == "online"
    assert by_id["audio-card0"].model == "PCH"
    assert by_id["audio-card0"].driver == "snd_hda_intel"
    assert by_id["camera-video0"].model == "Integrated Camera"
    battery = by_id["power-BAT0"]
    assert battery.type == "battery"
    assert battery.state == "Discharging"
    assert battery.temperature_c == 25.3
    assert battery.power is not None
    assert battery.power.capacity_percent == 42
    assert battery.power.energy_now_uwh == 1000
    assert battery.power.power_uw == 5_000_000
    mains = by_id["power-ADP0"]
    assert mains.type == "power"
    assert mains.state == "online"
    assert mains.power is not None
    assert mains.power.online is True


def test_missing_measurements_stay_missing(tmp_path: Path) -> None:
    card = tmp_path / "sys" / "class" / "drm" / "card1" / "device"
    _text(card / "vendor", "0x10de")
    _text(card / "device", "0x0000")
    zone = tmp_path / "sys" / "class" / "thermal" / "thermal_zone0"
    _text(zone / "type", "acpitz")
    _text(zone / "temp", "99000")
    _text(tmp_path / "proc" / "cpuinfo", "processor : 0\nvendor_id : GenuineIntel\n")
    _text(tmp_path / "sys" / "devices" / "system" / "cpu" / "cpu0" / "online", "1")

    report = LinuxHardwareProvider(root=tmp_path).inventory()
    gpu = next(device for device in report.devices if device.type == "gpu")
    cpu = next(device for device in report.devices if device.type == "cpu")

    assert gpu.vendor == "0x10de"
    assert gpu.usage.vram_total_bytes is None
    assert gpu.usage.vram_used_bytes is None
    assert gpu.temperature_c is None
    assert cpu.temperature_c is None
    assert cpu.usage.usage_percent is None
    assert cpu.usage.frequency_hz is None
    assert all(device.type != "monitor" for device in report.devices)


def test_unreadable_bus_is_a_gap(tmp_path: Path) -> None:
    pci = tmp_path / "sys" / "bus" / "pci" / "devices"
    pci.mkdir(parents=True)
    pci.chmod(0)
    try:
        report = LinuxHardwareProvider(root=tmp_path).inventory()
    finally:
        pci.chmod(0o755)

    assert report.observed is True
    assert "pci" in report.gaps
    assert all(device.type != "pci" for device in report.devices)


def test_proc_audio_is_used_when_sysfs_sound_is_absent(tmp_path: Path) -> None:
    _text(
        tmp_path / "proc" / "asound" / "cards",
        " 0 [PCH            ]: HDA-Intel - HDA Intel PCH\n",
    )
    report = LinuxHardwareProvider(root=tmp_path).inventory()
    audio = next(device for device in report.devices if device.type == "audio")

    assert audio.id == "audio-card0"
    assert audio.model == "HDA Intel PCH"
    assert audio.driver == "HDA-Intel"


def test_linux_provider_only_reads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("subprocess")

    monkeypatch.setattr("subprocess.run", explode)
    monkeypatch.setattr("subprocess.Popen", explode)
    source = Path(sys.modules["omne.hardware.providers.linux"].__file__ or "")
    text = source.read_text(encoding="utf-8")
    assert "subprocess" not in text
    assert "write_text" not in text
    assert "modprobe" not in text
    LinuxHardwareProvider(root=tmp_path).inventory()


def test_testing_api_is_read_only_mock(tmp_path: Path) -> None:
    omne = build_OMNE(runtime_settings(tmp_path))
    status, body = route_get(omne, "/hardware", {})

    assert status.value == 200
    hardware = body["hardware"]
    assert isinstance(hardware, dict)
    assert hardware["provider"] == "mock"
    assert hardware["observed"] is True
    assert hardware["drivers_modified"] is False
    assert hardware["devices"] == []
    assert hardware["gaps"] == []
    posted, payload = route_post(omne, "/hardware", {"action": "configure"})
    assert posted.value == 404
    assert payload["error"] == "not_found"
    created = [event for event in omne.list_events() if event.type.startswith("hardware.")]
    assert created == []


def test_testing_selects_mock_even_on_linux(tmp_path: Path) -> None:
    assert isinstance(select_provider("testing"), MockHardwareProvider)
    if sys.platform.startswith("linux"):
        provider = select_provider("development", root=tmp_path)
        assert isinstance(provider, LinuxHardwareProvider)
        assert provider.inventory().devices == []


def _device(device_id: str, device_type: str, *, state: str = "present") -> HardwareDevice:
    return HardwareDevice(id=device_id, type=device_type, state=state)  # type: ignore[arg-type]


def _unobserved() -> object:
    from omne.hardware.model import HardwareInventory

    return HardwareInventory(provider="linux", observed=False, devices=[], gaps=["linux"])


def _fixture(root: Path) -> None:
    _text(
        root / "proc" / "cpuinfo",
        "\n".join(
            [
                "processor : 0",
                "vendor_id : GenuineIntel",
                "model name : Test CPU",
                "physical id : 0",
                "flags : fpu vme",
                "",
                "processor : 1",
                "vendor_id : GenuineIntel",
                "model name : Test CPU",
                "physical id : 0",
                "flags : fpu vme",
                "",
            ]
        ),
    )
    cpu = root / "sys" / "devices" / "system" / "cpu"
    _text(cpu / "online", "0-1")
    _text(cpu / "cpu0" / "topology" / "physical_package_id", "0")
    _text(cpu / "cpu0" / "topology" / "core_id", "0")
    _text(cpu / "cpu0" / "cpufreq" / "scaling_cur_freq", "2200000")
    _text(cpu / "cpu1" / "topology" / "physical_package_id", "0")
    _text(cpu / "cpu1" / "topology" / "core_id", "1")
    _text(root / "proc" / "meminfo", "MemTotal:        2048 kB\nMemAvailable:    1024 kB\n")
    gpu = root / "sys" / "class" / "drm" / "card0" / "device"
    _text(gpu / "vendor", "0x10de")
    _text(gpu / "device", "0x1b80")
    _text(gpu / "mem_info_vram_total", "1024")
    _text(gpu / "mem_info_vram_used", "0")
    _link(gpu / "driver", "nvidia")
    hdmi = root / "sys" / "class" / "drm" / "card0-HDMI-A-1"
    _text(hdmi / "status", "connected")
    _text(hdmi / "enabled", "enabled")
    _text(hdmi / "modes", "1920x1080\n1280x720\n")
    _text(root / "sys" / "class" / "drm" / "card0-DP-1" / "status", "disconnected")
    keyboard = root / "sys" / "class" / "input" / "input0"
    _text(keyboard / "name", "Test Keyboard")
    _text(keyboard / "capabilities" / "ev", "3")
    _text(keyboard / "capabilities" / "key", "40000000")
    _text(keyboard / "id" / "vendor", "0001")
    _link(keyboard / "device" / "driver", "hid-generic")
    mouse = root / "sys" / "class" / "input" / "input1"
    _text(mouse / "name", "Test Mouse")
    _text(mouse / "capabilities" / "ev", "4")
    _link(mouse / "device" / "driver", "hid-generic")
    usb = root / "sys" / "bus" / "usb" / "devices" / "1-2"
    _text(usb / "idVendor", "046d")
    _text(usb / "idProduct", "c52b")
    _text(usb / "manufacturer", "Logitech")
    _text(usb / "product", "Unifying Receiver")
    _text(usb / "speed", "12")
    _link(usb / "driver", "usb")
    _text(root / "sys" / "bus" / "usb" / "devices" / "1-2:1.0" / "bInterfaceClass", "03")
    pci = root / "sys" / "bus" / "pci" / "devices" / "0000:00:02.0"
    _text(pci / "vendor", "0x8086")
    _text(pci / "device", "0x1234")
    _text(pci / "class", "0x030000")
    _text(pci / "enable", "1")
    _link(pci / "driver", "i915")
    disk = root / "sys" / "block" / "vda"
    _text(disk / "size", "2048")
    _text(disk / "device" / "vendor", "0x1af4")
    _text(disk / "device" / "model", "Test Disk")
    _text(disk / "device" / "state", "running")
    _link(disk / "device" / "driver", "virtio_blk")
    _text(root / "sys" / "block" / "loop0" / "size", "100")
    ethernet = root / "sys" / "class" / "net" / "enp0s4"
    _text(ethernet / "type", "1")
    _text(ethernet / "operstate", "up")
    _text(ethernet / "address", "02:00:00:00:00:01")
    _text(ethernet / "speed", "1000")
    _link(ethernet / "device" / "driver", "virtio_net")
    _text(root / "sys" / "class" / "net" / "lo" / "operstate", "unknown")
    _text(root / "sys" / "class" / "net" / "docker0" / "operstate", "up")
    wifi = root / "sys" / "class" / "net" / "wlan0"
    _text(wifi / "type", "1")
    _text(wifi / "operstate", "down")
    _text(wifi / "address", "02:00:00:00:00:02")
    (wifi / "wireless").mkdir(parents=True, exist_ok=True)
    _link(wifi / "device" / "driver", "iwlwifi")
    bluetooth = root / "sys" / "class" / "bluetooth" / "hci0"
    _text(bluetooth / "address", "00:11:22:33:44:55")
    _link(bluetooth / "device" / "driver", "btusb")
    rfkill = root / "sys" / "class" / "rfkill" / "rfkill0"
    _text(rfkill / "type", "bluetooth")
    _text(rfkill / "name", "hci0")
    _text(rfkill / "state", "1")
    audio = root / "sys" / "class" / "sound" / "card0"
    _text(audio / "id", "PCH")
    _link(audio / "device" / "driver", "snd_hda_intel")
    _text(root / "sys" / "class" / "sound" / "pcmC0D0p" / "pcm_class", "playback")
    camera = root / "sys" / "class" / "video4linux" / "video0"
    _text(camera / "name", "Integrated Camera")
    _link(camera / "device" / "driver", "uvcvideo")
    battery = root / "sys" / "class" / "power_supply" / "BAT0"
    _text(battery / "type", "Battery")
    _text(battery / "status", "Discharging")
    _text(battery / "capacity", "42")
    _text(battery / "energy_now", "1000")
    _text(battery / "energy_full", "2000")
    _text(battery / "voltage_now", "12000000")
    _text(battery / "power_now", "5000000")
    _text(battery / "manufacturer", "TestCo")
    _text(battery / "model_name", "BAT")
    _text(battery / "temp", "253")
    _text(root / "sys" / "class" / "power_supply" / "ADP0" / "type", "Mains")
    _text(root / "sys" / "class" / "power_supply" / "ADP0" / "online", "1")
    hwmon = root / "sys" / "class" / "hwmon" / "hwmon0"
    _text(hwmon / "name", "coretemp")
    _text(hwmon / "temp1_input", "45123")
    hwmon.joinpath("device").symlink_to(cpu / "cpu0")
    zone = root / "sys" / "class" / "thermal" / "thermal_zone0"
    _text(zone / "type", "acpitz")
    _text(zone / "temp", "99000")


def _text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _link(path: Path, name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(f"../../../../bus/pci/drivers/{name}")
