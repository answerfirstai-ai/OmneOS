# Windowing

OMNE records windows. labwc places them.

The display provider in `docs/GRAPHICS_ARCHITECTURE.md` selects labwc and does not start it.
Windowing sits on that choice. It does not implement a tiling window manager, and it does not speak
the Wayland protocol.

```text
labwc (placement, focus, workspaces, outputs)
        │
        ▼
omne.windowing provider   ← mock session, or a labwc snapshot
        │
        ▼
WindowingService          ← grant check, then events
        │
        ▼
OMNE Core                 ← GET /windowing, event bus
        │
        ▼
OMNE Shell                ← parser for that record, still drawing its own page
```

Core imports `omne.windowing.select`. It does not import labwc.

## What the record contains

`omne/windowing/model.py` defines the record:

| Fact             | Field                                                |
| ---------------- | ---------------------------------------------------- |
| Open windows     | `windows`                                            |
| Application      | `app_id` and `title`                                 |
| Focused window   | `focused_window_id`                                  |
| Active workspace | `active_workspace_id`                                |
| Position         | `x`, `y`                                             |
| Size             | `width`, `height`                                    |
| Fullscreen       | per window, and `fullscreen_window_id`               |
| Minimized        | `minimized`                                          |
| Maximized        | `maximized`                                          |
| Workspace        | `workspace_id`                                       |
| Monitor          | `monitor_id` against `monitors`                      |
| Owner            | `owner`, the agent that launched the window, or null |

`known: false` means the window list was not observed. An empty `windows` array in that state is not
a report that the desktop has zero windows. `compositor_commanded` is false. This revision updates
the record and does not send the change to labwc.

## Providers

| Provider | When                                                   | Source                                                           |
| -------- | ------------------------------------------------------ | ---------------------------------------------------------------- |
| mock     | `OMNE_ENVIRONMENT=testing`, and any non-Linux platform | In-memory session. No windows until a permitted launch.          |
| labwc    | Development and production on Linux                    | A snapshot file. The host root `/` has no default snapshot path. |

The mock session has two fixed workspaces, `default` and `other`. They are names in the record, not
detected outputs. The mock starts with no monitors. A move onto an output that is not in the record
is refused. The Linux snapshot is where a test supplies real outputs, such as HDMI and DisplayPort.

The Linux provider reads `run/omne/windows.json` under a fixture root, or an explicit
`snapshot_path`. It does not read `/run/omne/windows.json` when the root is `/`, so a live host
session is not observed by opening a file. A Wayland socket is not a window list. An unreadable or
invalid snapshot leaves `known` false and does not raise. A valid snapshot copies windows,
workspaces, and monitors into memory. Later focus, close, move, resize, minimize, maximize,
fullscreen, and workspace updates change that copy only.

labwc 0.7 has no swaymsg-style control socket. A future observer can fill the snapshot from
`wlr-foreign-toplevel-management`. That client is not part of this revision, and nothing here
connects to `WAYLAND_DISPLAY`.

## Grants

`GET /windowing` and `OMNE windowing` are diagnostics. They do not require a grant. There is no
`POST /windowing`. An agent cannot close or move a window through the local HTTP API.

Mutations go through `WindowingService.apply(request, grants, environment)`:

| Grant            | Effect                                                                                                                                                                                                     |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `window: own`    | Launch a window owned by that agent. Focus, close, move, resize, minimize, maximize, fullscreen, and workspace changes apply to windows that agent owns.                                                   |
| `window: manage` | The grant that would cover every window, including a window with no owner. Production denies it. Development and testing do not apply it: confirmation is required, and this revision has no confirm step. |

A missing grant is a deny. An owned window stays unchanged when another agent holds only
`window: own`. Launch focuses the new window and emits `window.created`, then `window.focused`.
Closing the focused window records focus on the next mapped window that is not minimized. That
follow-up is part of the record. It is not a command to the other application.

`window: own` may also change which workspace is active. That updates the active flag and does not
rewrite foreign window geometry.

## Events

The service publishes these types on the OMNE event bus with `source` `windowing`:

| Event               | When                                                                                                           |
| ------------------- | -------------------------------------------------------------------------------------------------------------- |
| `window.created`    | A permitted launch added a window. Payload: `id`, `app_id`.                                                    |
| `window.focused`    | Focus moved to a window. Payload: `id`, `app_id`.                                                              |
| `window.closed`     | A permitted close removed a window. Payload: `id`, `app_id`.                                                   |
| `window.changed`    | Geometry, monitor, workspace, or state flags changed. Payload: `id`, `fields`.                                 |
| `workspace.changed` | The active workspace changed, or a window moved. Payload: `workspace_id`, and `window_id` when a window moved. |

Focusing the window that is already focused applies and does not emit a second `window.focused`. An
unknown window, monitor, or workspace applies nothing and emits nothing.

## Shell

`shell/src/windowing.ts` parses the `GET /windowing` document. The page still draws the launcher and
tasks windows in `shell/src/windows.ts`. The parser is the contract for a later host that can show
compositor windows beside that page.

## What this revision does not do

- It does not start labwc or install it.
- It does not change the host graphical session.
- It does not tile, stack, or animate windows.
- It does not map the shell URL into a Wayland layer. That remains the desktop surface in
  `docs/GRAPHICS_ARCHITECTURE.md`.
