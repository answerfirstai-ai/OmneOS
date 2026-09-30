import assert from "node:assert/strict";
import test from "node:test";

import { characterAsset, characterMode, characterState } from "./character.js";

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

test("the visible character follows the live system", () => {
  const idle = { coreOk: true, voiceListening: false, statuses: [] as const };
  assert.equal(characterMode(idle), "IDLE");
  assert.equal(characterMode({ ...idle, statuses: ["COMPLETED"] }), "IDLE");
  assert.equal(characterMode({ ...idle, coreOk: false }), "OFFLINE");
  assert.equal(characterMode({ ...idle, statuses: ["PLANNING"] }), "THINKING");
  assert.equal(
    characterMode({ ...idle, statuses: ["RUNNING"], activeAgents: ["research"] }),
    "RESEARCHING",
  );
  assert.equal(characterMode({ ...idle, statuses: ["RUNNING"] }), "EXECUTING");
  assert.equal(characterMode({ ...idle, statuses: ["WAITING"] }), "WAITING");
  assert.equal(characterMode({ ...idle, waitingForUser: true }), "WAITING");
  assert.equal(characterMode({ ...idle, recovery: "DEGRADED" }), "WARNING");
  assert.equal(characterMode({ ...idle, statuses: ["FAILED"], recovery: "DEGRADED" }), "ERROR");
  assert.equal(
    characterMode({ ...idle, statuses: ["RUNNING"], recovery: "SAFE_MODE" }),
    "EXECUTING",
  );
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
