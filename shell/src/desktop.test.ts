import assert from "node:assert/strict";
import test from "node:test";

import { agentLine, modelLine, notificationLine, parentTasks, taskLine } from "./desktop.js";

test("parent tasks are the ones shown in the monitor", () => {
  const tasks = parentTasks([
    { id: "parent", objective: "write notes", status: "COMPLETED", metadata: { role: "parent" } },
    { id: "child", objective: "write notes", status: "COMPLETED", metadata: { role: "child" } },
  ]);

  assert.deepEqual(
    tasks.map((task) => task.id),
    ["parent"],
  );
  assert.equal(taskLine(tasks[0]!), "COMPLETED write notes");
});

test("agent model and notification lines stay literal", () => {
  assert.equal(
    agentLine({ id: "coding", state: "AVAILABLE", enabled: true }),
    "coding AVAILABLE enabled",
  );
  assert.equal(
    modelLine({ id: "mock-default", provider: "mock", local: false }),
    "mock-default mock cloud",
  );
  assert.equal(notificationLine({ id: "1", type: "task.completed" }), "task.completed");
});
