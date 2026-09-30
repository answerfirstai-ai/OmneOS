import assert from "node:assert/strict";
import test from "node:test";

import { chordMatches, pointerMatches, readInputStatus } from "./input-status.js";

const payload = {
  input: {
    observed: true,
    host_grab: false,
    key_stream: false,
    pointer_stream: false,
    listening: false,
    attention: "idle",
    revision: 0,
    activation: { modifiers: ["ctrl", "alt"], key: "space", button: null },
    cancel: { modifiers: ["ctrl", "alt"], key: "escape", button: null },
    push_to_talk: { modifiers: ["ctrl", "alt", "shift"], key: "space", button: null },
    push_to_talk_state: "prepared",
  },
};

test("readInputStatus shows the configured activation chord", () => {
  assert.equal(readInputStatus(payload).text, "ctrl+alt+space");
  assert.equal(readInputStatus(payload).state, "ready");
  assert.equal(readInputStatus(payload).text.includes("listening"), false);
});

test("readInputStatus stays unknown until input is observed", () => {
  assert.deepEqual(readInputStatus({ input: { observed: false } }).state, "unknown");
});

test("readInputStatus reports the command surface and rejects a key log", () => {
  const view = readInputStatus({ input: { ...payload.input, attention: "command", revision: 2 } });
  assert.equal(view.state, "command");
  assert.equal(view.text, "command");
  assert.throws(() => readInputStatus({ input: { ...payload.input, keylog: ["a"] } }), /key log/);
  assert.throws(() => readInputStatus({ input: { ...payload.input, listening: true } }), /capture/);
});

test("chordMatches accepts only the configured chord", () => {
  const activation = "ctrl+alt+space";
  assert.equal(
    chordMatches(
      { key: " ", ctrlKey: true, altKey: true, shiftKey: false, metaKey: false },
      activation,
    ),
    true,
  );
  assert.equal(
    chordMatches(
      { key: "a", ctrlKey: true, altKey: true, shiftKey: false, metaKey: false },
      activation,
    ),
    false,
  );
  assert.equal(
    chordMatches(
      { key: " ", ctrlKey: false, altKey: false, shiftKey: false, metaKey: false },
      activation,
    ),
    false,
  );
  assert.equal(
    chordMatches(
      { key: "Escape", ctrlKey: true, altKey: true, shiftKey: false, metaKey: false },
      "ctrl+alt+escape",
    ),
    true,
  );
  assert.equal(
    pointerMatches(
      { button: 1, key: "", ctrlKey: true, altKey: false, shiftKey: false, metaKey: false },
      "ctrl+middle",
    ),
    true,
  );
});
