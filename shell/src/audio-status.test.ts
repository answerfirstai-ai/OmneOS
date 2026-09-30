import assert from "node:assert/strict";
import test from "node:test";

import { readAudioStatus } from "./audio-status.js";

const payload = {
  audio: {
    observed: true,
    capture_open: false,
    transmitting: false,
    recognition: "not_implemented",
    default_output: "alsa_output.analog-stereo",
    microphone: "present",
    devices: [
      {
        id: "alsa_input.analog-stereo",
        name: "Built-in Microphone",
        role: "input",
        muted: false,
        volume: 100,
      },
      {
        id: "alsa_output.analog-stereo",
        name: "Built-in Speaker",
        role: "output",
        muted: false,
        volume: 40,
      },
    ],
  },
};

test("readAudioStatus shows the default output volume and microphone state", () => {
  assert.deepEqual(readAudioStatus(payload), {
    text: "Built-in Speaker 40% mic present",
    state: "present",
  });
});

test("readAudioStatus stays unknown until the stack is observed", () => {
  assert.deepEqual(readAudioStatus({ audio: { observed: false, devices: [] } }), {
    text: "audio unknown",
    state: "unknown",
  });
});

test("readAudioStatus reports mute without a capture claim", () => {
  const view = readAudioStatus({
    audio: {
      ...payload.audio,
      microphone: "active",
      devices: payload.audio.devices.map((device) =>
        device.role === "output" ? { ...device, muted: true, volume: 40 } : device,
      ),
    },
  });
  assert.equal(view.state, "active");
  assert.equal(view.text, "Built-in Speaker muted mic active");
  assert.equal(view.text.includes("listening"), false);
});

test("readAudioStatus rejects samples and an open capture", () => {
  assert.throws(() => readAudioStatus({ audio: { ...payload.audio, samples: [1, 2] } }), /samples/);
  assert.throws(
    () => readAudioStatus({ audio: { ...payload.audio, capture_open: true } }),
    /capture/,
  );
  assert.throws(
    () => readAudioStatus({ audio: { ...payload.audio, recognition: "ready" } }),
    /not implemented/,
  );
});
