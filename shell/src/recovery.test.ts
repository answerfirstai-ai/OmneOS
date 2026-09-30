import assert from "node:assert/strict";
import test from "node:test";

import { readRecovery, shellSurfaces } from "./recovery.js";

const healthy = {
  state: "NORMAL",
  explanation: "startup checks passed",
  shell_reduced: false,
  diagnostics_available: true,
  data_erased: false,
  os_reinstalled: false,
};

test("readRecovery accepts a healthy document", () => {
  assert.deepEqual(readRecovery(healthy), healthy);
  assert.deepEqual(shellSurfaces(readRecovery(healthy)), [
    "diagnostics",
    "recovery",
    "tasks",
    "agents",
    "models",
    "missions",
    "voice",
  ]);
});

test("safe mode keeps diagnostics and hides optional shell surfaces", () => {
  const status = readRecovery({
    ...healthy,
    state: "SAFE_MODE",
    explanation: "normal startup failed: startup failed 3 consecutive times",
    shell_reduced: true,
  });
  assert.deepEqual(shellSurfaces(status), ["diagnostics", "recovery"]);
});

test("readRecovery rejects erased data and a missing explanation", () => {
  assert.throws(() => readRecovery({ ...healthy, data_erased: true }), /erase/);
  assert.throws(() => readRecovery({ ...healthy, os_reinstalled: true }), /reinstall/);
  assert.throws(() => readRecovery({ ...healthy, explanation: "" }), /explanation/);
});
