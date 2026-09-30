# Audio

Linux owns the audio server. OMNE reads it.

```text
microphone → audio capture → speech recognition → OMNE intent → execution → text-to-speech → audio output
```

That path is the architecture. This revision implements the read at both ends: which microphone and
which output exist, and what the mixer is doing. It does not capture audio, recognize speech, or
speak.

```text
PipeWire and WirePlumber, or ALSA
        │
        ▼
proc, sysfs, and an existing session dump
        │
        ▼
omne.audio provider      ← mock session, or a Linux read
        │
        ▼
AudioService             ← permission check, then events
        │
        ▼
OMNE Core                ← GET /audio, OMNE audio
        │
        ▼
OMNE Shell tray          ← default output, volume, mute, microphone state
```

Core imports `omne.audio.select`. Inspection does not start PipeWire, open a capture device, or
write a mixer control. `stack_commanded`, `capture_open`, and `transmitting` are false.
`recognition` is `not_implemented`. There is no `POST /audio`.

Voice stays on the existing rule. `voice.transmit` is denied, `listening` stays false, and
discovering a microphone does not mark voice hardware available. The shell listen control stays
disabled unless a later policy explicitly allows transmission and a provider is configured. This
revision does not add that provider.

## What a read contains

`omne/audio/model.py` defines the record:

| Field             | Meaning                                                                                 |
| ----------------- | --------------------------------------------------------------------------------------- |
| `devices`         | Microphones, speakers, headphones, Bluetooth audio, and other outputs                   |
| `default_input`   | The default source, when the session published one                                      |
| `default_output`  | The default sink, when the session published one                                        |
| `defaults_known`  | False when the stack does not publish defaults. ALSA alone leaves this false            |
| `streams`         | Client streams. A record has no samples                                                 |
| `microphone`      | `unknown`, `absent`, `present`, `muted`, or `active`                                    |
| `capture_open`    | Always false. An active stream means some other client has the device, not OMNE         |
| `recognition`     | Always `not_implemented`                                                                |
| `transmitting`    | Always false                                                                            |
| `stack`           | `pipewire` when that unit or a session dump is present, otherwise `alsa` or `unknown`   |
| `session_manager` | `wireplumber` when that unit file is present. This does not claim the daemon is running |
| `stack_commanded` | Always false                                                                            |

A missing volume or mute stays null. A real zero stays zero. Bluetooth wins over the headphone name
when the bus is Bluetooth, and the device role still says whether it is an input or an output.

`microphone` is `active` when an input stream is `running`. It is `muted` when an input is muted and
no capture stream is running. It is `absent` when the read succeeded and no input device was
published. It is `unknown` when the device or stream list could not be read.

## Sources

| Fact           | Linux source                                                                                         |
| -------------- | ---------------------------------------------------------------------------------------------------- |
| PipeWire nodes | `run/pipewire/dump.json` when that file is already on the root. Volume is the linear 0–1 mixer value |
| Defaults       | PipeWire metadata `default.audio.sink` and `default.audio.source`                                    |
| ALSA devices   | `/proc/asound/pcm` and `/proc/asound/cards`, or `/sys/class/sound` when the proc list is absent      |
| Active PCM     | `state: RUNNING` or `state: DRAINING` in the PCM status file                                         |
| Stack          | `pipewire.service` and `wireplumber.service` under the system or user unit directories               |

This revision does not run a PipeWire client. Connecting to the socket can start the session through
socket activation, so the development machine is left as it is. The future image can write the dump
from an already running PipeWire session. OMNE still does not replace that session.

## Operations

| Action      | Mock session                       | Linux provider                           |
| ----------- | ---------------------------------- | ---------------------------------------- |
| inspect     | Return the in-memory session       | Read proc, sysfs, unit files, and a dump |
| set default | Record the default input or output | Refused. The host stack is not commanded |
| set volume  | Record a percentage from 0 to 100  | Refused                                  |
| set mute    | Record mute or unmute              | Refused                                  |

There is no capture action and no speech action. The mock does not invent a sample.

Every mixer call goes through `AudioService.apply` before the provider sees it:

| Tool                                          | Grant             | Testing and development                         | Production |
| --------------------------------------------- | ----------------- | ----------------------------------------------- | ---------- |
| `audio.set_default`, `set_volume`, `set_mute` | `audio:configure` | Confirm. Confirmation does not apply the change | Deny       |

A missing grant is a deny. Agents are not given this grant. The Linux provider still refuses the
change after an allow.

## Events

| Event                      | When                                                     |
| -------------------------- | -------------------------------------------------------- |
| `audio.device.added`       | A device id appeared                                     |
| `audio.device.removed`     | A device id disappeared                                  |
| `audio.device.changed`     | The same id changed in a field other than volume or mute |
| `audio.default.changed`    | The default input or output changed                      |
| `audio.volume.changed`     | A device volume changed                                  |
| `audio.mute.changed`       | A device mute changed                                    |
| `audio.stream.started`     | A stream became `running`                                |
| `audio.stream.stopped`     | A running stream stopped                                 |
| `audio.microphone.changed` | The microphone classification changed                    |

The first inspect is the baseline and emits nothing. Payloads carry ids, roles, and mixer numbers.
They do not carry samples. The shell parser rejects `samples`, `pcm`, `waveform`, `frames`, and
`audio_bytes`, and it rejects `capture_open`, `transmitting`, and any recognition state other than
`not_implemented`.

`GET /audio` and `OMNE audio` return the record. They do not open a microphone.

## Future path

The image keeps PipeWire as the audio server and WirePlumber as the session manager, with ALSA
underneath. A later revision can:

1. Capture only after `voice.transmit` is explicitly allowed and a voice provider exists.
2. Hand that audio to a speech recognizer. Recognition is not implemented here.
3. Turn the transcript into an OMNE intent through the existing intent engine.
4. Execute that intent through the existing mission path.
5. Synthesize speech and play it on the default output through PipeWire.

Until that policy exists, the microphone stays closed and voice stays disabled.
