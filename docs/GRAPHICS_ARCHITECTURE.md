# Graphics architecture

OMNE uses Linux graphics infrastructure. It does not implement a display server or a Wayland
compositor.

```text
DRM/KMS  →  labwc (Wayland compositor)  →  OMNE display provider  →  OMNE Core
                                              ↓
                                         OMNE Shell (later, as a Wayland surface)
```

Core depends on `omne.display`. The labwc provider is the only Linux implementation. Tests and
non-Linux hosts use the mock provider. Neither provider starts a compositor, and neither changes the
host's current graphical session.

## Compositor

This environment is Linux on x86_64, with no `/dev/dri` node and no `WAYLAND_DISPLAY`. Ubuntu 24.04
publishes several Wayland compositors. OMNE selects **labwc**:

| Compositor | Role                                                          |
| ---------- | ------------------------------------------------------------- |
| labwc      | Selected. Stacking wlroots compositor for application windows |
| weston     | Reference compositor. Its own desktop shell is not OMNE       |
| sway       | Tiling compositor                                             |
| cage       | One fullscreen surface                                        |
| wayfire    | 3D compositor with its own shell                              |

labwc 0.7.1 provides the pieces OMNE needs and does not ship GNOME, KDE, or a display manager:

- DRM/KMS through wlroots, including GPU rendering when a render node exists
- Wayland surfaces for the shell and for application windows
- Monitor detection, resolution, and refresh from the kernel mode list
- More than one output
- Fullscreen and window placement
- Keyboard and pointer routing through libinput

`GET /display` and `OMNE display` report those facts. A check is present only when the device or
binary is there. An empty window list means the provider has not queried a compositor
(`windows_known` is false), not that zero windows exist. The planned desktop surface stays inactive:

`http://127.0.0.1:4173/?surface=desktop`

The TypeScript shell still draws its own windows in the page. A later host can map that URL as a
Wayland layer. This revision does not replace the shell and does not start labwc. The ISO installs
the labwc package and leaves it stopped. See `docs/ISO_BUILD.md`.

## Providers

`omne/display/model.py` defines `Display`, `Monitor`, `Window`, `Workspace`, `Surface`, and
`FullscreenState`.

| Provider | When                                                   |
| -------- | ------------------------------------------------------ |
| mock     | `OMNE_ENVIRONMENT=testing`, and any non-Linux platform |
| labwc    | Development and production on Linux                    |

The mock reports `provider: mock`, no monitor, and `gpu_acceleration: unavailable`. It does not read
`/dev/dri`.

The labwc provider reads:

| Fact              | Source                                                       |
| ----------------- | ------------------------------------------------------------ |
| DRM/KMS           | `/dev/dri/card*` or `/sys/class/drm/cardN`                   |
| GPU acceleration  | `/dev/dri/renderD*`                                          |
| Monitors          | `/sys/class/drm/card*-*` with `status` `connected`           |
| Resolution        | First mode in the connector `modes` file                     |
| Refresh           | The `@rate` suffix when the kernel lists one. Otherwise null |
| Input             | `/dev/input/event*`                                          |
| Compositor binary | `/usr/bin/labwc`                                             |
| Wayland session   | A socket at `$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY`              |

`can_launch` is true only when Linux, a DRM card, a render node, labwc, a connected monitor with a
mode, and an input device are all present. That flag does not start labwc.

## Before a graphical desktop can launch in a VM

`can_launch` has to be true inside the guest, and a future session unit has to start labwc. This
revision does not start that unit. All of the following have to exist first:

1. A Linux guest with systemd. The UEFI disk from `scripts/linux/build-disk.sh` is the OMNE boot
   path. The kernel stays Ubuntu's `linux-image-generic`.
2. The `labwc` package from Ubuntu universe, installed in the guest. A render-capable DRM driver
   comes with the kernel, not from an OMNE graphics stack.
3. A QEMU display device that exposes both a KMS card and a render node. `virtio-vga` or
   `virtio-gpu` creates `/dev/dri/card*` and `/dev/dri/renderD*`. A serial console alone has no
   display. The guest connector in `/sys/class/drm` must be `connected` and must list at least one
   mode, such as `1920x1080`.
4. Input event nodes for the keyboard and pointer, so labwc can route them. A virtio keyboard and a
   virtio or USB tablet create `/dev/input/event*`.
5. The session user in the `video`, `render`, and `input` groups, and a writable `XDG_RUNTIME_DIR`.
6. No display manager. `gdm3`, `lightdm`, `plymouth`, and `ubuntu-desktop` stay off the disk. labwc
   is the session compositor.
7. OMNE Core on `127.0.0.1:8787` and the current shell files on `127.0.0.1:4173`. The shell is not
   yet mapped into Wayland. The URL above is the desktop surface reserved for that host.

Until those are true, the console checklist remains the boot screen. `OMNE display` prints the
missing items and leaves the host session untouched.

Window records live in `omne.windowing` and are described in `docs/WINDOWING.md`. labwc still owns
placement. OMNE stores focus, geometry, workspace, and monitor assignment, and a grant is required
before that record changes. The change is not sent to the compositor.
