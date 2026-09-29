import assert from "node:assert/strict";
import test from "node:test";

import {
  activateWindow,
  clampSize,
  closeWindow,
  focusedWindow,
  initialWindowState,
  isWindowId,
  minimizeWindow,
  openWindow,
  toggleMaximize,
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
  assert.equal(isWindowId("graph"), true);
  assert.equal(isWindowId("settings"), false);
});

test("minimize keeps the window on the taskbar and focuses the next one", () => {
  const state = minimizeWindow(initialWindowState(), "tasks");

  assert.equal(state.open.includes("tasks"), true);
  assert.equal(state.minimized.includes("tasks"), true);
  assert.equal(focusedWindow(state), "launcher");
  assert.equal(focusedWindow(activateWindow(state, "tasks")), "tasks");
});

test("maximize toggles without closing the window", () => {
  const maximized = toggleMaximize(initialWindowState(), "tasks");
  const restored = toggleMaximize(maximized, "tasks");

  assert.equal(maximized.maximized.includes("tasks"), true);
  assert.equal(maximized.open.includes("tasks"), true);
  assert.equal(restored.maximized.includes("tasks"), false);
  assert.equal(focusedWindow(maximized), "tasks");
});

test("resize stays inside the desktop bounds", () => {
  assert.deepEqual(
    clampSize(40, 900, { minWidth: 280, minHeight: 160, maxWidth: 640, maxHeight: 480 }),
    {
      width: 280,
      height: 480,
    },
  );
});

test("closing a minimized window removes it from the taskbar", () => {
  const state = closeWindow(minimizeWindow(initialWindowState(), "launcher"), "launcher");

  assert.equal(state.open.includes("launcher"), false);
  assert.equal(state.minimized.includes("launcher"), false);
});
