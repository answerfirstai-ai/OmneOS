/** Tray text for the audio record. A missing fact stays unknown, and samples are not shown. */

export interface AudioStatusView {
  text: string;
  state: "unknown" | "absent" | "present" | "muted" | "active";
}

const SAMPLE_KEYS = new Set(["samples", "pcm", "waveform", "frames", "audio_bytes"]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function rejectSamples(value: unknown): void {
  if (Array.isArray(value)) {
    for (const item of value) {
      rejectSamples(item);
    }
    return;
  }
  if (!isRecord(value)) {
    return;
  }
  for (const key of Object.keys(value)) {
    if (SAMPLE_KEYS.has(key)) {
      throw new Error("Audio payload must not include samples");
    }
    rejectSamples(value[key]);
  }
}

function stringOrNull(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

/** Format GET /audio for the desktop tray. */
export function readAudioStatus(payload: unknown): AudioStatusView {
  rejectSamples(payload);
  if (!isRecord(payload)) {
    return { text: "audio unknown", state: "unknown" };
  }
  const audio = isRecord(payload["audio"]) ? payload["audio"] : payload;
  if (audio["capture_open"] === true || audio["transmitting"] === true) {
    throw new Error("Audio payload must not capture or transmit");
  }
  if ("recognition" in audio && audio["recognition"] !== "not_implemented") {
    throw new Error("Speech recognition is not implemented");
  }
  if (audio["observed"] !== true) {
    return { text: "audio unknown", state: "unknown" };
  }
  const devices = Array.isArray(audio["devices"]) ? audio["devices"].filter(isRecord) : [];
  if (devices.length === 0) {
    return { text: "no audio devices", state: "absent" };
  }
  const chosen = chooseDevice(audio, devices);
  const name = stringOrNull(chosen["name"]) ?? "audio";
  const parts = [name];
  if (chosen["muted"] === true) {
    parts.push("muted");
  } else if (typeof chosen["volume"] === "number" && Number.isFinite(chosen["volume"])) {
    parts.push(`${Math.round(chosen["volume"])}%`);
  }
  const microphone = stringOrNull(audio["microphone"]);
  if (microphone === "present" || microphone === "muted" || microphone === "active") {
    parts.push(`mic ${microphone}`);
  }
  return { text: parts.join(" "), state: trayState(chosen, microphone) };
}

function chooseDevice(
  audio: Record<string, unknown>,
  devices: readonly Record<string, unknown>[],
): Record<string, unknown> {
  const outputId = stringOrNull(audio["default_output"]);
  if (outputId !== null) {
    const match = devices.find((item) => item["id"] === outputId);
    if (match !== undefined) {
      return match;
    }
  }
  return devices.find((item) => item["role"] === "output") ?? devices[0] ?? { name: "audio" };
}

function trayState(
  chosen: Record<string, unknown>,
  microphone: string | null,
): AudioStatusView["state"] {
  if (microphone === "active") {
    return "active";
  }
  if (chosen["muted"] === true) {
    return "muted";
  }
  return "present";
}
