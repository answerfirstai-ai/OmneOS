import assert from "node:assert/strict";
import test from "node:test";

import {
  agentLine,
  modelLine,
  notificationLine,
  parentTasks,
  readDesktop,
  taskLine,
} from "./desktop.js";

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

test("one desktop document supplies every panel", () => {
  const desktop = readDesktop({
    tasks: [
      { id: "parent", objective: "write notes", status: "COMPLETED", metadata: { role: "parent" } },
    ],
    agents: [{ id: "coding", state: "AVAILABLE", enabled: true }],
    models: [{ id: "mock-default", provider: "mock", local: false }],
    events: [{ id: "1", type: "task.completed" }],
    voice: {
      provider: "unavailable",
      hardware: "unavailable",
      permission: "DENY",
      listening: false,
    },
  });

  assert.equal(parentTasks(desktop.tasks)[0]?.id, "parent");
  assert.equal(desktop.agents[0]?.id, "coding");
  assert.equal(desktop.models[0]?.id, "mock-default");
  assert.equal(desktop.events[0]?.type, "task.completed");
  assert.equal(desktop.voice.permission, "DENY");
  assert.equal(desktop.voice.reason, undefined);
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
