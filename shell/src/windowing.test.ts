import assert from "node:assert/strict";
import test from "node:test";

import { parseWindowing, parseWindowingResponse } from "./windowing.js";

const state = {
  provider: "labwc",
  known: true,
  compositor: "labwc",
  compositor_commanded: false,
  focused_window_id: "editor",
  active_workspace_id: "ws-1",
  windows: [
    {
      id: "editor",
      title: "Editor",
      app_id: "editor",
      workspace_id: "ws-1",
      monitor_id: "HDMI-A-1",
      x: 10,
      y: 20,
      width: 800,
      height: 600,
      fullscreen: false,
      minimized: false,
      maximized: false,
      focused: true,
      mapped: true,
      owner: "coding",
    },
  ],
  workspaces: [{ id: "ws-1", name: "One", active: true, window_ids: ["editor"] }],
  monitors: [{ id: "HDMI-A-1", name: "HDMI-A-1", x: 0, y: 0, width: 1920, height: 1080 }],
  fullscreen_window_id: null,
  detail: null,
};

test("parseWindowing accepts a labwc record", () => {
  assert.deepEqual(parseWindowing(state), state);
});

test("parseWindowingResponse reads the route envelope", () => {
  assert.equal(parseWindowingResponse({ windowing: state }).focused_window_id, "editor");
});

test("parseWindowing keeps an unknown list distinct from an empty desktop", () => {
  const parsed = parseWindowing({
    ...state,
    provider: "mock",
    known: false,
    compositor: "none",
    windows: [],
    focused_window_id: null,
    detail: "window list is not observed",
  });
  assert.equal(parsed.known, false);
  assert.deepEqual(parsed.windows, []);
  assert.equal(parsed.detail, "window list is not observed");
});

test("parseWindowing rejects a commanded compositor", () => {
  assert.throws(() => parseWindowing({ ...state, compositor_commanded: true }), /compositor/);
});

test("parseWindowing rejects a window without an owner field", () => {
  const window = { ...state.windows[0] };
  delete window.owner;
  assert.throws(() => parseWindowing({ ...state, windows: [window] }), /owner/);
});
