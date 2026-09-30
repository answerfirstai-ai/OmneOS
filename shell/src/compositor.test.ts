import assert from "node:assert/strict";
import test from "node:test";

import {
  activateWorkspace,
  cancelSwitcher,
  commitSwitcher,
  cycleMonitor,
  cycleSwitcher,
  cycleWorkspace,
  dismissToast,
  focusedOnWorkspace,
  initialCompositor,
  isVisible,
  moveFrame,
  moveToMonitor,
  paintedFrame,
  publishToasts,
  resizeFrame,
  shiftWindowWorkspace,
  toggleFullscreen,
  windowMonitor,
} from "./compositor.js";
import { matchDesktopCommand } from "./shortcuts.js";
import { focusedWindow, minimizeWindow } from "./windows.js";

const view = { width: 1440, height: 810 };

test("the desktop starts on two monitors and the first workspace", () => {
  const state = initialCompositor();

  assert.deepEqual(
    state.monitors.map((monitor) => monitor.name),
    ["Main", "Side"],
  );
  assert.equal(state.activeWorkspace, "one");
  assert.equal(focusedWindow(state.windows), "tasks");
  assert.equal(isVisible(state, "tasks"), true);
  assert.equal(isVisible(state, "notifications"), false);
  assert.equal(windowMonitor(state, "notifications"), "side");
});

test("moving across the seam records the side monitor", () => {
  const moved = moveFrame(initialCompositor(), "tasks", 1700, 80);

  assert.equal(windowMonitor(moved, "tasks"), "side");
  assert.equal(moved.windows.maximized.includes("tasks"), false);
  const painted = paintedFrame(moved, "tasks", view);
  assert.ok(painted !== null && painted.x > view.width / 2);
});

test("resize stays inside the monitor", () => {
  const resized = resizeFrame(initialCompositor(), "launcher", 20, 4000);

  assert.equal(resized.frames.launcher?.width, 280);
  assert.equal(resized.frames.launcher?.height, 900);
});

test("fullscreen fills that window's monitor and toggles off", () => {
  const on = toggleFullscreen(initialCompositor(), "tasks");
  const painted = paintedFrame(on, "tasks", view);
  const monitor = paintedFrame(moveToMonitor(initialCompositor(), "tasks", "main"), "tasks", view);

  assert.equal(on.fullscreen, "tasks");
  assert.ok(painted !== null && monitor !== null && painted.width > (monitor?.width ?? 0));
  assert.equal(toggleFullscreen(on, "tasks").fullscreen, null);
});

test("a workspace hides the windows that were left behind", () => {
  const work = activateWorkspace(initialCompositor(), "two");

  assert.equal(focusedOnWorkspace(work), null);
  assert.equal(isVisible(work, "tasks"), false);
  const followed = shiftWindowWorkspace(initialCompositor(), "tasks", 1);
  assert.equal(followed.activeWorkspace, "two");
  assert.equal(isVisible(followed, "tasks"), true);
  assert.equal(isVisible(followed, "launcher"), false);
  assert.equal(cycleWorkspace(followed, -1).activeWorkspace, "one");
});

test("the switcher lands on the window behind the front one", () => {
  const started = cycleSwitcher(initialCompositor(), 1);

  assert.equal(started.switcher[0], "launcher");
  const committed = commitSwitcher(started);
  assert.equal(focusedWindow(committed.windows), "launcher");
  assert.deepEqual(committed.switcher, []);
  assert.deepEqual(cancelSwitcher(started).switcher, []);
});

test("minimized windows return when the switcher commits them", () => {
  const hidden = {
    ...initialCompositor(),
    windows: minimizeWindow(initialCompositor().windows, "launcher"),
  };
  const committed = commitSwitcher(cycleSwitcher(hidden, 1));

  assert.equal(focusedWindow(committed.windows), "launcher");
  assert.equal(committed.windows.minimized.includes("launcher"), false);
});

test("a second display receives the window and one display does not jump it", () => {
  const moved = cycleMonitor(initialCompositor(), "launcher");

  assert.equal(windowMonitor(moved, "launcher"), "side");
  const alone = { ...initialCompositor(), monitors: initialCompositor().monitors.slice(0, 1) };
  const stayed = cycleMonitor(alone, "launcher");
  assert.equal(stayed.frames.launcher, alone.frames.launcher);
});

test("a notice is shown once and can be dismissed", () => {
  const first = publishToasts(initialCompositor(), [{ id: "event-1", text: "Mission completed." }]);
  const again = publishToasts(first, [{ id: "event-1", text: "Mission completed." }]);

  assert.equal(first.toasts.length, 1);
  assert.equal(again.toasts.length, 1);
  assert.equal(dismissToast(first, "event-1").toasts.length, 0);
});

test("desktop chords are the window manager", () => {
  const alt = { metaKey: false, ctrlKey: false, altKey: true, shiftKey: false };
  const meta = { metaKey: true, ctrlKey: false, altKey: false, shiftKey: false };
  assert.equal(matchDesktopCommand({ ...alt, key: "Tab" }), "switch-next");
  assert.equal(matchDesktopCommand({ ...alt, key: "Tab", shiftKey: true }), "switch-previous");
  assert.equal(matchDesktopCommand({ ...meta, key: "Tab" }), "switch-next");
  assert.equal(matchDesktopCommand({ ...meta, key: "Tab", shiftKey: true }), "switch-previous");
  assert.equal(matchDesktopCommand({ ...alt, key: "F4" }), "close-window");
  assert.equal(
    matchDesktopCommand({
      key: "F11",
      metaKey: false,
      ctrlKey: false,
      altKey: false,
      shiftKey: false,
    }),
    "fullscreen",
  );
  assert.equal(matchDesktopCommand({ ...meta, key: "ArrowUp" }), "maximize");
  assert.equal(matchDesktopCommand({ ...meta, key: "ArrowDown" }), "minimize");
  assert.equal(matchDesktopCommand({ ...meta, key: "ArrowRight" }), "workspace-next");
  assert.equal(
    matchDesktopCommand({ ...meta, key: "ArrowLeft", shiftKey: true }),
    "window-workspace-previous",
  );
  assert.equal(matchDesktopCommand({ ...meta, key: "M", shiftKey: true }), "monitor-next");
  assert.equal(
    matchDesktopCommand({
      key: "Tab",
      metaKey: false,
      ctrlKey: true,
      altKey: false,
      shiftKey: false,
    }),
    null,
  );
});
