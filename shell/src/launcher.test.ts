import assert from "node:assert/strict";
import test from "node:test";

import { LAUNCHER_ACTIONS, launcherObjective } from "./launcher.js";

test("the launcher offers intelligence objectives", () => {
  assert.deepEqual(
    LAUNCHER_ACTIONS.map((action) => action.label),
    [
      "Research NVIDIA's latest AI models",
      "Open Chrome",
      "Build my project",
      "Check system resources",
      "Start coding agent",
      "Find my files",
    ],
  );
  assert.equal(launcherObjective("research-models"), "Research NVIDIA's latest AI models");
  assert.equal(launcherObjective("open-chrome"), "Open Chrome");
  assert.equal(launcherObjective("missing"), null);
  assert.equal(
    LAUNCHER_ACTIONS.every((action) => action.objective === action.label),
    true,
  );
});
