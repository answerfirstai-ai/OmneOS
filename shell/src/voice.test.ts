import assert from "node:assert/strict";
import test from "node:test";

import { voiceControlEnabled, voiceSummary } from "./voice.js";

test("voice control stays disabled when permission is not allow", () => {
  const status = {
    provider: "unavailable",
    hardware: "unavailable",
    permission: "DENY",
    listening: false,
    reason: "no voice provider or audio hardware is configured",
  };

  assert.equal(voiceControlEnabled(status), false);
  assert.match(voiceSummary(status), /DENY/);
  assert.match(voiceSummary(status), /unavailable/);
});

test("voice control enables only for an allowed available provider", () => {
  const status = {
    provider: "available",
    hardware: "available",
    permission: "ALLOW",
    listening: false,
  };

  assert.equal(voiceControlEnabled(status), true);
});
