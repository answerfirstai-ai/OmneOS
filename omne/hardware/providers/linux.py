"""Discover hardware from Linux sysfs and proc.

Drivers stay in the kernel. This module only reads text files and symlinks.
It does not load modules, write sysfs, or run configuration commands.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

from omne.hardware.model import (
    HardwareDevice,
    HardwareInventory,
    PowerInfo,
    ResourceUsage,
)

_USB_DEVICE = re.compile(r"^(?:usb\d+|\d+-\d+(?:\.\d+)*)$")
_BLOCK = re.compile(r"^(?:sd[a-z]+|vd[a-z]+|hd[a-z]+|nvme\d+n\d+|mmcblk\d+|sr\d+)$")
_CARD = re.compile(r"^card\d+$")
_SOUND_CARD = re.compile(r"^card\d+$")
_CPU_SENSORS = {"coretemp", "k10temp", "zenpower", "cpu_thermal", "x86_pkg_temp"}
_EV_KEY = 0x2
_EV_REL = 0x4
_EV_ABS = 0x8
_KEY_LETTER = 1 << 30


class _Seen:
    def __init__(self, device: HardwareDevice, paths: list[Path]) -> None:
        self.device = device
        self.paths = paths


class LinuxHardwareProvider:
    """Read one sysfs root and report the devices that are actually there."""

    def __init__(self, *, root: Path | None = None) -> None:
        self._root = root if root is not None else Path("/")

    def inventory(self) -> HardwareInventory:
        if not self._root.is_dir():
            return HardwareInventory(provider="linux", observed=False, devices=[], gaps=["linux"])
        seen: list[_Seen] = []
        gaps: list[str] = []
        for reader in (
            _cpus,
            _memory,
            _gpus,
            _monitors,
            _inputs,
            _usb,
            _pci,
            _storage,
            _networks,
            _bluetooth,
            _audio,
            _cameras,
            _power,
        ):
            found, gap = reader(self._root)
            seen.extend(found)
            if gap is not None:
                gaps.append(gap)
        _attach_temperatures(self._root, seen)
        devices = sorted(
            (item.device for item in seen), key=lambda device: (device.type, device.id)
        )
        return HardwareInventory(
            provider="linux",
            observed=True,
            devices=devices,
            gaps=sorted(set(gaps)),
        )


def _cpus(root: Path) -> tuple[list[_Seen], str | None]:
    cpuinfo = root / "proc" / "cpuinfo"
    syscpu = root / "sys" / "devices" / "system" / "cpu"
    if not cpuinfo.is_file() and not syscpu.is_dir():
        return [], None
    processors = _parse_cpuinfo(_optional(cpuinfo) or "")
    online = _cpu_set(_optional(syscpu / "online"))
    packages: dict[str, list[tuple[str, dict[str, str]]]] = {}
    if syscpu.is_dir():
        listed = _list_dir(syscpu)
        if listed is None:
            return [], "cpu"
        for path in listed:
            if not re.fullmatch(r"cpu\d+", path.name):
                continue
            number = path.name.removeprefix("cpu")
            info = next(
                (item for item in processors if item.get("processor") == number),
                {},
            )
            package = _optional(path / "topology" / "physical_package_id") or info.get(
                "physical id", "0"
            )
            packages.setdefault(package, []).append((number, info))
    elif processors:
        for info in processors:
            package = info.get("physical id", "0")
            packages.setdefault(package, []).append((info.get("processor", "0"), info))
    if not packages and cpuinfo.is_file() and _optional(cpuinfo) is None:
        return [], "cpu"
    seen: list[_Seen] = []
    for package, members in sorted(packages.items(), key=lambda item: item[0]):
        numbers = [int(number) for number, _info in members if number.isdigit()]
        info = members[0][1]
        flags = [flag for flag in info.get("flags", "").split() if flag]
        cores = {
            _optional(syscpu / f"cpu{number}" / "topology" / "core_id") for number, _info in members
        }
        cores.discard(None)
        capabilities = [f"threads:{len(members)}"]
        if cores:
            capabilities.append(f"cores:{len(cores)}")
        capabilities.extend(f"flag:{flag}" for flag in flags)
        frequency_hz = _frequency_hz(syscpu, numbers)
        if numbers and online is not None and set(numbers) <= online:
            state = "online"
        elif numbers and online is not None and set(numbers).isdisjoint(online):
            state = "offline"
        else:
            state = "present"
        device = HardwareDevice(
            id=f"cpu-package-{package}",
            type="cpu",
            vendor=info.get("vendor_id") or None,
            model=info.get("model name") or None,
            driver=None,
            state=state,
            capabilities=capabilities,
            usage=ResourceUsage(frequency_hz=frequency_hz),
        )
        seen.append(_Seen(device, [syscpu / f"cpu{number}" for number in numbers]))
    return seen, None


def _memory(root: Path) -> tuple[list[_Seen], str | None]:
    path = root / "proc" / "meminfo"
    if not path.exists():
        return [], None
    if not path.is_file():
        return [], "memory"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [], "memory"
    info = _meminfo(text)
    total = info.get("MemTotal")
    available = info.get("MemAvailable")
    if total is None:
        return [], "memory"
    total_bytes = total * 1024
    available_bytes = available * 1024 if available is not None else None
    used = total_bytes - available_bytes if available_bytes is not None else None
    device = HardwareDevice(
        id="memory",
        type="memory",
        vendor=None,
        model=None,
        driver=None,
        state="present",
        usage=ResourceUsage(
            total_bytes=total_bytes,
            available_bytes=available_bytes,
            used_bytes=used,
        ),
    )
    return [_Seen(device, [])], None


def _gpus(root: Path) -> tuple[list[_Seen], str | None]:
    drm = root / "sys" / "class" / "drm"
    listed = _list_dir(drm)
    if listed is None:
        return [], "gpu"
    seen: list[_Seen] = []
    for path in listed:
        if not _CARD.fullmatch(path.name):
            continue
        device_path = path / "device"
        total = _nonnegative_int(_optional(device_path / "mem_info_vram_total"))
        used = _nonnegative_int(_optional(device_path / "mem_info_vram_used"))
        device = HardwareDevice(
            id=f"gpu-{path.name}",
            type="gpu",
            vendor=_optional(device_path / "vendor"),
            model=_optional(device_path / "device"),
            driver=_driver(device_path),
            state="present",
            usage=ResourceUsage(vram_total_bytes=total, vram_used_bytes=used),
        )
        seen.append(_Seen(device, _paths(_resolve(device_path), path)))
    return seen, None


def _monitors(root: Path) -> tuple[list[_Seen], str | None]:
    drm = root / "sys" / "class" / "drm"
    listed = _list_dir(drm)
    if listed is None:
        return [], "monitor"
    seen: list[_Seen] = []
    for path in listed:
        if not (path.name.startswith("card") and "-" in path.name):
            continue
        status = _optional(path / "status")
        if status != "connected":
            continue
        modes = _lines(path / "modes")
        enabled = _optional(path / "enabled")
        capabilities = [f"mode:{line}" for line in modes]
        if enabled is not None:
            capabilities.append(f"enabled:{enabled}")
        name = path.name.split("-", 1)[1]
        device = HardwareDevice(
            id=f"monitor-{path.name}",
            type="monitor",
            vendor=None,
            model=name,
            driver=None,
            state="connected",
            capabilities=capabilities,
        )
        seen.append(_Seen(device, [path]))
    return seen, None


def _inputs(root: Path) -> tuple[list[_Seen], str | None]:
    directory = root / "sys" / "class" / "input"
    listed = _list_dir(directory)
    if listed is None:
        return [], "input"
    seen: list[_Seen] = []
    for path in listed:
        if not path.name.startswith("input"):
            continue
        kind = _input_kind(path)
        if kind is None:
            continue
        device_type, capabilities = kind
        vendor = _optional(path / "id" / "vendor")
        product = _optional(path / "id" / "product")
        if product is not None:
            capabilities = [*capabilities, f"product:{product}"]
        device = HardwareDevice(
            id=f"{device_type}-{path.name}",
            type=device_type,
            vendor=vendor,
            model=_optional(path / "name"),
            driver=_driver(path / "device"),
            state="present",
            capabilities=capabilities,
        )
        seen.append(_Seen(device, _paths(path, _resolve(path / "device"))))
    return seen, None


def _usb(root: Path) -> tuple[list[_Seen], str | None]:
    directory = root / "sys" / "bus" / "usb" / "devices"
    listed = _list_dir(directory)
    if listed is None:
        return [], "usb"
    seen: list[_Seen] = []
    for path in listed:
        if _USB_DEVICE.fullmatch(path.name) is None:
            continue
        vendor_id = _optional(path / "idVendor")
        product_id = _optional(path / "idProduct")
        manufacturer = _optional(path / "manufacturer")
        capabilities: list[str] = []
        speed = _optional(path / "speed")
        if speed is not None:
            capabilities.append(f"speed:{speed}")
        serial = _optional(path / "serial")
        if serial is not None:
            capabilities.append(f"serial:{serial}")
        if manufacturer is not None and vendor_id is not None:
            capabilities.append(f"manufacturer:{manufacturer}")
        device = HardwareDevice(
            id=f"usb-{path.name}",
            type="usb",
            vendor=vendor_id or manufacturer,
            model=_optional(path / "product") or product_id,
            driver=_driver(path),
            state="present",
            capabilities=capabilities,
        )
        seen.append(_Seen(device, [path]))
    return seen, None


def _pci(root: Path) -> tuple[list[_Seen], str | None]:
    directory = root / "sys" / "bus" / "pci" / "devices"
    listed = _list_dir(directory)
    if listed is None:
        return [], "pci"
    seen: list[_Seen] = []
    for path in listed:
        enabled = _optional(path / "enable")
        if enabled == "1":
            state = "online"
        elif enabled == "0":
            state = "offline"
        else:
            state = "present"
        class_id = _optional(path / "class")
        capabilities = [f"class:{class_id}"] if class_id is not None else []
        device = HardwareDevice(
            id=f"pci-{path.name}",
            type="pci",
            vendor=_optional(path / "vendor"),
            model=_optional(path / "device"),
            driver=_driver(path),
            state=state,
            capabilities=capabilities,
        )
        seen.append(_Seen(device, _paths(_resolve(path))))
    return seen, None


def _storage(root: Path) -> tuple[list[_Seen], str | None]:
    directory = root / "sys" / "block"
    listed = _list_dir(directory)
    if listed is None:
        return [], "storage"
    seen: list[_Seen] = []
    for path in listed:
        if _BLOCK.fullmatch(path.name) is None:
            continue
        sectors = _nonnegative_int(_optional(path / "size"))
        total = sectors * 512 if sectors is not None else None
        state = _optional(path / "device" / "state") or "present"
        capabilities: list[str] = []
        if _optional(path / "removable") == "1":
            capabilities.append("removable")
        device = HardwareDevice(
            id=f"storage-{path.name}",
            type="storage",
            vendor=_optional(path / "device" / "vendor"),
            model=_optional(path / "device" / "model"),
            driver=_driver(path / "device"),
            state=state,
            capabilities=capabilities,
            usage=ResourceUsage(total_bytes=total),
        )
        seen.append(_Seen(device, _paths(path, _resolve(path / "device"))))
    return seen, None


def _networks(root: Path) -> tuple[list[_Seen], str | None]:
    directory = root / "sys" / "class" / "net"
    listed = _list_dir(directory)
    if listed is None:
        return [], "network"
    seen: list[_Seen] = []
    for path in listed:
        if path.name == "lo" or not (path / "device").exists():
            continue
        wireless = (path / "wireless").exists() or (path / "phy80211").exists()
        medium = _optional(path / "type")
        device_type: Literal["wifi", "ethernet"]
        if wireless:
            device_type = "wifi"
        elif medium == "1":
            device_type = "ethernet"
        else:
            continue
        capabilities: list[str] = []
        address = _optional(path / "address")
        if address is not None:
            capabilities.append(f"mac:{address}")
        speed = _positive_int(_optional(path / "speed"))
        if speed is not None:
            capabilities.append(f"speed:{speed}")
        device = HardwareDevice(
            id=f"net-{path.name}",
            type=device_type,
            vendor=None,
            model=path.name,
            driver=_driver(path / "device"),
            state=_optional(path / "operstate") or "present",
            capabilities=capabilities,
        )
        seen.append(_Seen(device, _paths(path, _resolve(path / "device"))))
    return seen, None


def _bluetooth(root: Path) -> tuple[list[_Seen], str | None]:
    directory = root / "sys" / "class" / "bluetooth"
    listed = _list_dir(directory)
    if listed is None:
        return [], "bluetooth"
    blocked = _rfkill(root, "bluetooth")
    seen: list[_Seen] = []
    for path in listed:
        if not path.name.startswith("hci"):
            continue
        address = _optional(path / "address")
        capabilities = [f"address:{address}"] if address is not None else []
        rfkill_state = blocked.get(path.name)
        if rfkill_state == "1":
            state = "online"
        elif rfkill_state == "0":
            state = "offline"
        else:
            state = "present"
        device = HardwareDevice(
            id=f"bluetooth-{path.name}",
            type="bluetooth",
            vendor=None,
            model=path.name,
            driver=_driver(path / "device"),
            state=state,
            capabilities=capabilities,
        )
        seen.append(_Seen(device, _paths(path, _resolve(path / "device"))))
    return seen, None


def _audio(root: Path) -> tuple[list[_Seen], str | None]:
    directory = root / "sys" / "class" / "sound"
    listed = _list_dir(directory)
    if listed is None:
        return [], "audio"
    seen: list[_Seen] = []
    for path in listed:
        if _SOUND_CARD.fullmatch(path.name) is None:
            continue
        device = HardwareDevice(
            id=f"audio-{path.name}",
            type="audio",
            vendor=None,
            model=_optional(path / "id"),
            driver=_driver(path / "device"),
            state="present",
        )
        seen.append(_Seen(device, _paths(path, _resolve(path / "device"))))
    if seen or directory.exists():
        return seen, None
    return _audio_proc(root), None


def _audio_proc(root: Path) -> list[_Seen]:
    path = root / "proc" / "asound" / "cards"
    text = _optional(path)
    if text is None:
        return []
    seen: list[_Seen] = []
    for line in text.splitlines():
        match = re.match(r"\s*(\d+)\s+\[([^\]]+)\]:\s*(\S+)\s+-\s+(.*)$", line)
        if match is None:
            continue
        seen.append(
            _Seen(
                HardwareDevice(
                    id=f"audio-card{match.group(1)}",
                    type="audio",
                    vendor=None,
                    model=match.group(4).strip() or None,
                    driver=match.group(3),
                    state="present",
                ),
                [],
            )
        )
    return seen


def _cameras(root: Path) -> tuple[list[_Seen], str | None]:
    directory = root / "sys" / "class" / "video4linux"
    listed = _list_dir(directory)
    if listed is None:
        return [], "camera"
    seen: list[_Seen] = []
    for path in listed:
        if not path.name.startswith("video"):
            continue
        device = HardwareDevice(
            id=f"camera-{path.name}",
            type="camera",
            vendor=None,
            model=_optional(path / "name"),
            driver=_driver(path / "device"),
            state="present",
        )
        seen.append(_Seen(device, _paths(path, _resolve(path / "device"))))
    return seen, None


def _power(root: Path) -> tuple[list[_Seen], str | None]:
    directory = root / "sys" / "class" / "power_supply"
    listed = _list_dir(directory)
    if listed is None:
        return [], "power"
    seen: list[_Seen] = []
    for path in listed:
        kind = (_optional(path / "type") or "").lower()
        device_type: Literal["battery", "power"]
        if kind == "battery":
            device_type = "battery"
        elif kind in {"mains", "usb", "ups"}:
            device_type = "power"
        else:
            continue
        status = _optional(path / "status")
        online = _optional(path / "online")
        if device_type == "battery":
            state = status or "present"
        elif online == "1":
            state = "online"
        elif online == "0":
            state = "offline"
        else:
            state = "present"
        power = PowerInfo(
            status=status,
            online=True if online == "1" else False if online == "0" else None,
            capacity_percent=_float_value(_optional(path / "capacity")),
            energy_now_uwh=_nonnegative_int(_optional(path / "energy_now")),
            energy_full_uwh=_nonnegative_int(_optional(path / "energy_full")),
            voltage_uv=_nonnegative_int(_optional(path / "voltage_now")),
            power_uw=_nonnegative_int(_optional(path / "power_now")),
            current_ua=_nonnegative_int(_optional(path / "current_now")),
        )
        temp = _nonnegative_int(_optional(path / "temp"))
        device = HardwareDevice(
            id=f"power-{path.name}",
            type=device_type,
            vendor=_optional(path / "manufacturer"),
            model=_optional(path / "model_name"),
            driver=None,
            state=state,
            temperature_c=temp / 10 if temp is not None else None,
            power=power if power.known() else None,
        )
        seen.append(_Seen(device, [path]))
    return seen, None


def _attach_temperatures(root: Path, seen: list[_Seen]) -> None:
    _attach_hwmon(root, seen)
    _attach_package_zone(root, seen)


def _attach_hwmon(root: Path, seen: list[_Seen]) -> None:
    listed = _list_dir(root / "sys" / "class" / "hwmon")
    if not listed:
        return
    for path in listed:
        reading = _nonnegative_int(_optional(path / "temp1_input"))
        if reading is None:
            continue
        celsius = reading / 1000
        target = _resolve(path / "device")
        matched = False
        if target is not None:
            for item in seen:
                if item.device.temperature_c is not None:
                    continue
                if any(
                    target == candidate or candidate in target.parents for candidate in item.paths
                ):
                    item.device = item.device.model_copy(update={"temperature_c": celsius})
                    matched = True
                    break
        if matched:
            continue
        name = _optional(path / "name")
        if name not in _CPU_SENSORS:
            continue
        cpus = [
            item for item in seen if item.device.type == "cpu" and item.device.temperature_c is None
        ]
        if len(cpus) == 1:
            cpus[0].device = cpus[0].device.model_copy(update={"temperature_c": celsius})


def _attach_package_zone(root: Path, seen: list[_Seen]) -> None:
    listed = _list_dir(root / "sys" / "class" / "thermal")
    if not listed:
        return
    cpus = [
        item for item in seen if item.device.type == "cpu" and item.device.temperature_c is None
    ]
    if len(cpus) != 1:
        return
    for path in listed:
        if _optional(path / "type") != "x86_pkg_temp":
            continue
        reading = _nonnegative_int(_optional(path / "temp"))
        if reading is None:
            continue
        cpus[0].device = cpus[0].device.model_copy(update={"temperature_c": reading / 1000})
        return


def _rfkill(root: Path, kind: str) -> dict[str, str]:
    listed = _list_dir(root / "sys" / "class" / "rfkill")
    found: dict[str, str] = {}
    if not listed:
        return found
    for path in listed:
        if _optional(path / "type") != kind:
            continue
        name = _optional(path / "name") or ""
        state = _optional(path / "state")
        if state is None:
            continue
        found[name] = state
    return found


def _input_kind(path: Path) -> tuple[Literal["keyboard", "mouse", "input"], list[str]] | None:
    events = _bitmap(_optional(path / "capabilities" / "ev"))
    if events is None:
        return None
    key_bits = _bitmap(_optional(path / "capabilities" / "key")) or 0
    keyboard = bool(events & _EV_KEY) and bool(key_bits & _KEY_LETTER)
    mouse = bool(events & _EV_REL) or (bool(events & _EV_ABS) and bool(events & _EV_KEY))
    if keyboard and mouse:
        return "input", ["keyboard", "mouse"]
    if keyboard:
        return "keyboard", ["keyboard"]
    if mouse:
        return "mouse", ["mouse"]
    return None


def _parse_cpuinfo(text: str) -> list[dict[str, str]]:
    processors: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            if current:
                processors.append(current)
                current = {}
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        current[key.strip()] = value.strip()
    if current:
        processors.append(current)
    return processors


def _meminfo(text: str) -> dict[str, int]:
    info: dict[str, int] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        number = value.strip().split()
        if not number or not number[0].isdigit():
            continue
        info[key.strip()] = int(number[0])
    return info


def _cpu_set(text: str | None) -> set[int] | None:
    if text is None:
        return None
    found: set[int] = set()
    for part in text.split(","):
        piece = part.strip()
        if not piece:
            continue
        try:
            if "-" in piece:
                start, end = piece.split("-", 1)
                found.update(range(int(start), int(end) + 1))
            else:
                found.add(int(piece))
        except ValueError:
            return None
    return found


def _paths(*candidates: Path | None) -> list[Path]:
    return [candidate for candidate in candidates if candidate is not None]


def _driver(path: Path) -> str | None:
    link = path / "driver"
    try:
        target = os.readlink(link)
    except OSError:
        return None
    name = Path(target).name
    return name or None


def _resolve(path: Path) -> Path | None:
    try:
        if not path.exists():
            return None
        return path.resolve()
    except OSError:
        return None


def _list_dir(path: Path) -> list[Path] | None:
    if not path.exists():
        return []
    if not path.is_dir():
        return []
    try:
        return sorted(path.iterdir(), key=lambda item: item.name)
    except OSError:
        return None


def _optional(path: Path) -> str | None:
    try:
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    return text or None


def _lines(path: Path) -> list[str]:
    text = _optional(path)
    if text is None:
        return []
    return [line.strip() for line in text.splitlines() if line.strip()]


def _nonnegative_int(text: str | None) -> int | None:
    if text is None:
        return None
    try:
        value = int(text, 0)
    except ValueError:
        return None
    if value < 0:
        return None
    return value


def _positive_int(text: str | None) -> int | None:
    value = _nonnegative_int(text)
    if value is None or value <= 0:
        return None
    return value


def _bitmap(text: str | None) -> int | None:
    if text is None:
        return None
    value = 0
    try:
        for word in text.split():
            value = (value << 64) | int(word, 16)
    except ValueError:
        return None
    return value


def _frequency_hz(syscpu: Path, numbers: list[int]) -> int | None:
    if not numbers:
        return None
    khz = _positive_int(_optional(syscpu / f"cpu{numbers[0]}" / "cpufreq" / "scaling_cur_freq"))
    if khz is None:
        return None
    return khz * 1000


def _float_value(text: str | None) -> float | None:
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None
