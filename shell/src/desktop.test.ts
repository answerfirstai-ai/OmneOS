import assert from "node:assert/strict";
import test from "node:test";

import {
  activeMission,
  agentLine,
  attentionLine,
  chooseMission,
  describeModel,
  modelLine,
  notificationLine,
  parentTasks,
  readDesktop,
  retainDesktop,
  shouldRepaint,
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

test("desktop fields stay empty until the core sends them", () => {
  const desktop = readDesktop({
    tasks: [],
    agents: [],
    models: [
      { id: "mock-default", provider: "mock", local: false, lifecycle: "AVAILABLE", loaded: false },
    ],
    events: [{ id: "1", type: "mission.completed", mission_id: "m1" }],
    voice: {
      provider: "unavailable",
      hardware: "unavailable",
      permission: "DENY",
      listening: false,
    },
    confirmations: [
      {
        task_id: "child",
        objective: "run echo",
        tool_id: "terminal.execute",
        command: "echo hello",
        agent_id: "coding",
        mission_id: "m1",
      },
    ],
  });

  assert.deepEqual(desktop.activity, []);
  assert.equal(desktop.project, null);
  assert.equal(desktop.confirmations[0]?.command, "echo hello");
  assert.equal(desktop.events[0]?.mission_id, "m1");
  assert.equal(describeModel(desktop.models[0]!), "mock-default mock cloud AVAILABLE not loaded");
  assert.equal(retainDesktop(desktop, null), desktop);
  assert.equal(shouldRepaint("same", "same"), false);
  assert.equal(shouldRepaint("same", "next"), true);
});

test("attention follows a waiting mission before an idle one", () => {
  const missions = [
    { id: "old", objective: "done", status: "COMPLETED", updated_at: "2026-01-01T00:00:00Z" },
    { id: "now", objective: "run tests", status: "WAITING", updated_at: "2026-01-02T00:00:00Z" },
  ];

  assert.equal(activeMission(missions)?.id, "now");
  assert.equal(chooseMission(missions, "done")?.id, "old");
  assert.equal(
    attentionLine(
      [{ question_id: "q", mission_id: "now", question: "Which file?" }],
      [
        {
          task_id: "t",
          objective: "run",
          tool_id: "terminal.execute",
          command: "npm test",
          agent_id: "coding",
          mission_id: "now",
        },
      ],
    ),
    "Permission: npm test",
  );
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
