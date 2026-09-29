import assert from "node:assert/strict";
import test from "node:test";

import {
  activateWindow,
  closeWindow,
  focusedWindow,
  initialWindowState,
  isWindowId,
  openWindow,
  windowZ,
} from "./windows.js";

test("launcher and tasks start on the desktop", () => {
  const state = initialWindowState();

  assert.deepEqual(state.open, ["launcher", "tasks"]);
  assert.equal(focusedWindow(state), "tasks");
  assert.equal(windowZ(state, "tasks") > windowZ(state, "launcher"), true);
});

test("opening a window puts it in front", () => {
  const state = openWindow(initialWindowState(), "agents");

  assert.equal(focusedWindow(state), "agents");
  assert.equal(state.open.includes("agents"), true);
  assert.equal(state.open.includes("launcher"), true);
});

test("the front window hides when activated again", () => {
  const state = activateWindow(initialWindowState(), "tasks");

  assert.equal(state.open.includes("tasks"), false);
  assert.equal(focusedWindow(state), "launcher");
});

test("closing the last window leaves the desktop clear", () => {
  const state = closeWindow(closeWindow(initialWindowState(), "tasks"), "launcher");

  assert.deepEqual(state.open, []);
  assert.equal(focusedWindow(state), null);
});

test("window ids are the desktop apps", () => {
  assert.equal(isWindowId("voice"), true);
  assert.equal(isWindowId("settings"), false);
});
