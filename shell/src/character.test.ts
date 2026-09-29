import assert from "node:assert/strict";
import test from "node:test";

import { characterAsset, characterState } from "./character.js";

test("character is idle without tasks", () => {
  assert.equal(characterState({ coreOk: true, voiceListening: false, statuses: [] }), "idle");
});

test("character follows task status", () => {
  assert.equal(
    characterState({ coreOk: true, voiceListening: false, statuses: ["WAITING"] }),
    "thinking",
  );
  assert.equal(
    characterState({ coreOk: true, voiceListening: false, statuses: ["RUNNING"] }),
    "working",
  );
  assert.equal(
    characterState({ coreOk: true, voiceListening: false, statuses: ["COMPLETED"] }),
    "success",
  );
  assert.equal(
    characterState({ coreOk: true, voiceListening: false, statuses: ["FAILED"] }),
    "error",
  );
});

test("character reports an unreachable core and missing assets", () => {
  assert.equal(characterState({ coreOk: false, voiceListening: true, statuses: [] }), "error");
  assert.equal(characterAsset("idle"), null);
});

test("mission status drives the character when the core reports one", () => {
  assert.equal(
    characterState({
      coreOk: true,
      voiceListening: false,
      statuses: ["COMPLETED"],
      missionStatuses: ["ANALYZING"],
    }),
    "analyzing",
  );
  assert.equal(
    characterState({
      coreOk: true,
      voiceListening: false,
      statuses: [],
      missionStatuses: ["VERIFYING"],
    }),
    "verifying",
  );
  assert.equal(
    characterState({
      coreOk: true,
      voiceListening: false,
      statuses: ["WAITING"],
      missionStatuses: ["WAITING"],
    }),
    "waiting",
  );
});
