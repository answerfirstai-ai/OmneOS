# Input architecture

OMNE needs one activation chord that works no matter which of its windows is focused. The chord is
configuration. Core compares a named action with that configuration. It does not contain the chord,
and it does not read the keyboard.

```text
OMNE.toml chords → InputService → desktop command surface
labwc / kernel device list → device report (names and kinds only)
```

Core depends on `omne.input`. The Linux provider is the implementation for development and
production on Linux. Tests and other hosts use the mock provider, which starts with no devices.

## Configured chords

The shipped development, testing, production, and system configurations set:

| Binding      | Default chord          |
| ------------ | ---------------------- |
| Activation   | `ctrl+alt+space`       |
| Cancel       | `ctrl+alt+escape`      |
| Push-to-talk | `ctrl+alt+shift+space` |

`OMNE_ACTIVATION_SHORTCUT`, `OMNE_CANCEL_SHORTCUT`, and `OMNE_PUSH_TO_TALK_SHORTCUT` override those
values. An empty value leaves that binding unset. A chord must include at least one modifier
(`ctrl`, `alt`, `shift`, or `super`) and one key or pointer button. A bare letter is rejected, so a
shortcut cannot be ordinary typing. The stored form sorts modifiers as ctrl, alt, shift, super.

Those strings live in the TOML files. The input service parses whatever settings loaded. It does not
substitute a chord of its own.

## What the providers do

| Provider | Role                                                         |
| -------- | ------------------------------------------------------------ |
| mock     | In-memory keyboards and mice for tests and non-Linux hosts   |
| linux    | Reads `/proc/bus/input/devices` for `N:` and `H:` lines only |

A keyboard is a record whose handlers include `kbd`. A mouse is a record whose handlers include
`mouse`. The reader skips `B:` lines, including key bitmaps. It does not store event node names and
does not open `/dev/input`.

On Linux the reader also reports whether `/usr/bin/labwc` exists and whether a GlobalShortcuts
portal interface file is installed. This revision does not write a labwc keybind and does not call
the portal, so `host_grab` stays false.

## Activation, cancel, and push-to-talk

`GET /input` returns the configured chords, the attention state, and the device list. The shell
matches a keydown against those chords only. Any other key is ignored and is not stored.

| Chord        | Result                                            |
| ------------ | ------------------------------------------------- |
| Activation   | Open the command window and focus its field       |
| Cancel       | Close the command window                          |
| Push-to-talk | Nothing is captured. The binding stays `prepared` |

`input.activate` and `input.cancel` require `input:use`. They change OMNE's attention record. They
do not send a key. `input.activated` and `input.cancelled` name the surface (`command` or `idle`).
When the attention revision changes, the shell opens or closes the command window even if another
OMNE window was focused.

`input.bind` requires `input:bind`. It is high risk: confirmation in development and testing, denied
in production. Allowing it still does not install a grab. The reason is that the global shortcut
grab is not installed. A later compositor binding can deliver the binding name. It must not deliver
a key stream.

Push-to-talk is preparation for a later voice path. `listening` stays false. The microphone is not
opened, and `voice.transmit` stays denied. There is no always-listening mode.

## Permissions

| Tool             | Grant        | Risk |
| ---------------- | ------------ | ---- |
| `input.activate` | `input:use`  | low  |
| `input.cancel`   | `input:use`  | low  |
| `input.bind`     | `input:bind` | high |

No agent manifest holds these grants. An unauthenticated `POST /input` is not a route. `OMNE input`
prints the record and does not change it.

## Events

| Event                  | When                                             |
| ---------------------- | ------------------------------------------------ |
| `input.activated`      | Attention becomes the command surface            |
| `input.cancelled`      | Attention returns to idle                        |
| `input.device.added`   | A keyboard or mouse appears after the first read |
| `input.device.removed` | A keyboard or mouse disappears                   |

The first read is a baseline and emits nothing. Events name a device id and kind, or a surface. They
do not contain keystrokes.

## What this revision does not do

It does not capture arbitrary keys, scan codes, or a pressed-key list. It does not open an input
event node. It does not install a host-wide grab, so a chord pressed in another process is not
delivered until a compositor binding exists. It does not listen on the microphone.
