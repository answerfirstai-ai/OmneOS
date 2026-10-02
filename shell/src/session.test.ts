import assert from "node:assert/strict";
import test from "node:test";

import {
  DESKTOP_SURFACES,
  intelligenceBanner,
  maySendObjective,
  readIntelligence,
  sessionLine,
} from "./session.js";

test("the desktop stays available when intelligence is off", () => {
  const view = readIntelligence({
    enabled: false,
    desktop: true,
    reason: "Intelligence is off until an API key or a local model is connected.",
  });
  assert.equal(view.enabled, false);
  assert.equal(view.desktop, true);
  assert.equal(maySendObjective(view.enabled), false);
  assert.match(intelligenceBanner(false), /Intelligence is off/);
  assert.deepEqual(DESKTOP_SURFACES, ["browse", "files", "settings", "wifi"]);
  assert.match(sessionLine("wifi up"), /Wi-Fi: wifi up/);
});

test("a connected model is the only way an objective is sent", () => {
  const view = readIntelligence({ enabled: true, desktop: true, reason: "ready" });
  assert.equal(maySendObjective(view.enabled), true);
  assert.equal(intelligenceBanner(true), "Intelligence is connected.");
});
