# Hardware

Linux owns the drivers. OMNE reads what those drivers already published.

```text
Linux kernel drivers
        │
        ▼
sysfs and proc
        │
        ▼
omne.hardware provider   ← mock inventory, or a Linux read
        │
        ▼
HardwareService          ← hotplug diff, then events
        │
        ▼
OMNE Core                ← GET /hardware, OMNE hardware
```

Core imports `omne.hardware.select`. Discovery does not load a module, write sysfs, or run a
configuration command. `drivers_modified` is false. There is no `POST /hardware`.

## What a device contains

`omne/hardware/model.py` defines `HardwareDevice`:

| Field           | Meaning                                                                                                                           |
| --------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `id`            | Stable name from the kernel path, such as `storage-vda` or `cpu-package-0`                                                        |
| `type`          | cpu, memory, gpu, monitor, keyboard, mouse, input, usb, pci, storage, ethernet, wifi, bluetooth, audio, camera, battery, or power |
| `vendor`        | The vendor string or id Linux published. Null when the source has none                                                            |
| `model`         | The product string or device id Linux published. Null when the source has none                                                    |
| `driver`        | The driver symlink name. Null when the device has no bound driver                                                                 |
| `state`         | The kernel's own word when one exists, otherwise `present`                                                                        |
| `capabilities`  | Flags, modes, and identifiers that were read from sysfs                                                                           |
| `usage`         | Bytes, frequency, or VRAM only when a file reported them                                                                          |
| `temperature_c` | Degrees Celsius when a sensor is tied to that device. Otherwise null                                                              |
| `power`         | Battery or mains values in the kernel's units. Null when no power file exists                                                     |

A missing file stays null. A PCI vendor id is kept as `0x10de` rather than replaced with a vendor
name. VRAM is set only from `mem_info_vram_total` and `mem_info_vram_used`. CPU usage percent is
left null here; `OMNE compute` is the sampler that measures it. An unrelated thermal zone, such as
`acpitz`, is not copied onto the CPU.

`gaps` lists a category whose directory exists but could not be read. An absent directory is an
empty category, not a gap, and not a claim that the read failed.

## Sources

| Device    | Linux source                                                                   |
| --------- | ------------------------------------------------------------------------------ |
| CPU       | `/proc/cpuinfo`, `/sys/devices/system/cpu`                                     |
| RAM       | `/proc/meminfo`                                                                |
| GPU       | `/sys/class/drm/cardN`                                                         |
| VRAM      | `mem_info_vram_total` and `mem_info_vram_used` on that card                    |
| Monitors  | DRM connectors whose `status` is `connected`                                   |
| Keyboard  | `/sys/class/input` when the key bitmap includes a letter key                   |
| Mouse     | `/sys/class/input` when relative or absolute pointer events are present        |
| USB       | `/sys/bus/usb/devices` device nodes, not interface nodes                       |
| PCI       | `/sys/bus/pci/devices`                                                         |
| Storage   | `/sys/block` disks (`sd`, `vd`, `nvme`, `mmc`, `sr`). Loop devices are skipped |
| Ethernet  | `/sys/class/net` interfaces with a parent device and no wireless directory     |
| Wi-Fi     | The same tree when `wireless` or `phy80211` exists                             |
| Bluetooth | `/sys/class/bluetooth`, with `/sys/class/rfkill` state when the name matches   |
| Audio     | `/sys/class/sound/cardN`, or `/proc/asound/cards` when that class is absent    |
| Cameras   | `/sys/class/video4linux` when it exists                                        |
| Battery   | `/sys/class/power_supply` entries whose type is `Battery`                      |
| Mains     | Power-supply entries whose type is `Mains`, `USB`, or `UPS`                    |

Temperature comes from a hwmon device linked to that hardware, from a known CPU sensor name when
only one CPU package is present, or from `x86_pkg_temp`. Battery `temp` is tenths of a degree, which
is the power-supply ABI. Other sensors are millidegrees.

## Providers

| Provider | When                                                   |
| -------- | ------------------------------------------------------ |
| mock     | `OMNE_ENVIRONMENT=testing`, and any non-Linux platform |
| linux    | Development and production on Linux                    |

The mock inventory starts empty. Tests can replace its device list. The Linux provider reads the
given root and never writes it.

## Events

The service keeps the previous inventory. The first read is the baseline and emits nothing. A later
read emits:

| Event              | When                                                              |
| ------------------ | ----------------------------------------------------------------- |
| `hardware.added`   | An id appeared. Payload: `id`, `type`                             |
| `hardware.removed` | An id disappeared. Payload: `id`, `type`                          |
| `hardware.changed` | The same id has different fields. Payload: `id`, `type`, `fields` |

Events use source `hardware`. A read that could not observe the machine does not treat an empty list
as removal.

`GET /hardware` and `OMNE hardware` return the inventory. They do not configure devices.
