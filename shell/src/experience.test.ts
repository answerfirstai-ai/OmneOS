import assert from "node:assert/strict";
import test from "node:test";

import { cycleDetail } from "./detail.js";
import { layoutGraph } from "./graph-layout.js";
import { focusGraph } from "./graph-context.js";
import {
  agentBoard,
  commandStory,
  desktopOrbit,
  missionListLabel,
  modelCards,
  modelLines,
  modelStateLabel,
  nameWorkers,
  taskSurface,
  verificationLine,
} from "./present.js";
import { matchShortcut } from "./shortcuts.js";

test("detail level cycles without removing a mode", () => {
  assert.equal(cycleDetail("normal"), "inspect");
  assert.equal(cycleDetail("inspect"), "debug");
  assert.equal(cycleDetail("debug"), "normal");
});

test("an idle graph stays at the core", () => {
  const layout = layoutGraph(
    [
      { id: "core", type: "core", label: "OMNE Core" },
      { id: "mission-1", type: "mission", label: "write notes" },
      { id: "task-1", type: "task", label: "write notes" },
      { id: "tool:filesystem.write", type: "tool", label: "filesystem.write" },
    ],
    [
      { from: "core", to: "mission-1", type: "owns" },
      { from: "mission-1", to: "task-1", type: "mission_task" },
    ],
  );
  const idle = focusGraph(layout, null);
  assert.deepEqual(
    idle.nodes.map((node) => node.id),
    ["core"],
  );
  assert.equal(idle.edges.length, 0);

  const focused = focusGraph(layout, "mission-1");
  assert.deepEqual(focused.nodes.map((node) => node.id).sort(), ["core", "mission-1", "task-1"]);
  assert.equal(
    focused.nodes.some((node) => node.id === "tool:filesystem.write"),
    false,
  );
});

test("a shared agent does not import another mission", () => {
  const layout = layoutGraph(
    [
      { id: "core", type: "core", label: "OMNE Core" },
      { id: "mission-1", type: "mission", label: "one" },
      { id: "mission-2", type: "mission", label: "two" },
      { id: "task-1", type: "task", label: "one" },
      { id: "task-2", type: "task", label: "two" },
      { id: "agent:coding", type: "agent", label: "coding" },
      { id: "worker-a", type: "worker", label: "coding" },
      { id: "worker-b", type: "worker", label: "coding" },
    ],
    [
      { from: "core", to: "mission-1", type: "owns" },
      { from: "core", to: "mission-2", type: "owns" },
      { from: "mission-1", to: "task-1", type: "mission_task" },
      { from: "mission-2", to: "task-2", type: "mission_task" },
      { from: "task-1", to: "agent:coding", type: "assigned_agent" },
      { from: "task-1", to: "worker-a", type: "task_worker" },
      { from: "task-2", to: "worker-b", type: "task_worker" },
      { from: "worker-a", to: "agent:coding", type: "worker_agent" },
      { from: "worker-b", to: "agent:coding", type: "worker_agent" },
    ],
  );
  const focused = focusGraph(layout, "mission-1");
  const ids = focused.nodes.map((node) => node.id);
  assert.equal(ids.includes("mission-2"), false);
  assert.equal(ids.includes("task-2"), false);
  assert.equal(ids.includes("worker-b"), false);
  assert.equal(ids.includes("worker-a"), true);
  assert.equal(ids.includes("agent:coding"), true);
});

test("the command story stays free of raw identifiers", () => {
  const story = commandStory({
    lifecycle: [
      { id: "understanding", label: "UNDERSTANDING", mark: "done", detail: "" },
      { id: "planning", label: "PLANNING", mark: "done", detail: "" },
      { id: "execution", label: "EXECUTION", mark: "active", detail: "" },
      { id: "verification", label: "VERIFICATION", mark: "pending", detail: "" },
    ],
    taskCount: 4,
    workers: [
      { name: "Coding Worker #1", status: "RUNNING" },
      { name: "Research Worker #1", status: "COMPLETED" },
    ],
    verification: { status: "NONE", lines: [], passedChecks: 0, totalChecks: 0 },
  });
  const text = story
    .flatMap((beat) => [beat.title, ...beat.lines.map((line) => line.text)])
    .join("\n");
  assert.equal(text.includes("UNDERSTANDING"), true);
  assert.equal(text.includes("Request understood"), true);
  assert.equal(text.includes("4 tasks created"), true);
  const single = commandStory({
    lifecycle: [{ id: "planning", label: "PLANNING", mark: "done", detail: "" }],
    taskCount: 1,
    workers: [],
    verification: { status: "NONE", lines: [], passedChecks: 0, totalChecks: 0 },
  });
  assert.equal(
    single.some((beat) => beat.lines.some((line) => line.text === "1 task created")),
    true,
  );
  assert.equal(text.includes("Coding Worker #1"), true);
  assert.equal(text.includes("trace"), false);
  assert.equal(text.includes("mock"), false);
});

test("workers are numbered from the ones that exist", () => {
  const named = nameWorkers([
    { worker_id: "b", agent_id: "coding", status: "IDLE" },
    { worker_id: "a", agent_id: "coding", status: "RUNNING" },
    { worker_id: "c", agent_id: "research", status: "IDLE" },
  ]);
  assert.equal(named.find((worker) => worker.id === "a")?.name, "Coding Worker #1");
  assert.equal(named.find((worker) => worker.id === "b")?.name, "Coding Worker #2");
  const board = agentBoard(
    [
      { id: "coding", state: "AVAILABLE", enabled: true },
      { id: "research", state: "AVAILABLE", enabled: true },
    ],
    [
      { worker_id: "a", agent_id: "coding", status: "RUNNING" },
      { worker_id: "c", agent_id: "research", status: "IDLE" },
    ],
  );
  assert.deepEqual(
    board.definitions.map((agent) => agent.name),
    ["Coding", "Research"],
  );
  assert.equal(board.active.length, 1);
  assert.equal(board.idle.length, 1);
  assert.equal(board.active[0]?.name, "Coding Worker #1");
});

test("models hide provider names until inspection", () => {
  assert.equal(modelStateLabel({ local: true, lifecycle: "AVAILABLE" }), "Ready");
  assert.equal(modelStateLabel({ local: false, lifecycle: "AVAILABLE" }), "Available");
  assert.equal(modelStateLabel({ local: false, lifecycle: "UNAVAILABLE" }), "Unavailable");
  assert.equal(modelStateLabel({ local: false }), "Unknown");
  const cards = modelCards(
    [
      {
        id: "mock-default",
        provider: "mock",
        local: false,
        lifecycle: "AVAILABLE",
        model_name: "mock",
      },
      {
        id: "local",
        provider: "local",
        local: true,
        lifecycle: "UNAVAILABLE",
        model_name: "local",
      },
    ],
    [{ assigned_model: "mock-default", objective: "write notes", status: "RUNNING" }],
  );
  assert.equal(modelLines(cards.cloud[0]!, "normal")[0], "mock Available");
  assert.equal(modelLines(cards.cloud[0]!, "normal")[0]?.includes("mock-default"), false);
  assert.equal(modelLines(cards.cloud[0]!, "inspect")[0]?.includes("mock"), true);
  assert.equal(cards.active[0]?.work, "write notes");
  assert.equal(cards.local[0]?.state, "Unavailable");
});

test("normal task and mission lists omit completed history and ids", () => {
  const lines = taskSurface(
    [
      { id: "done", objective: "old", status: "COMPLETED", metadata: { role: "parent" } },
      { id: "now", objective: "build the page", status: "RUNNING", metadata: { role: "parent" } },
    ],
    "normal",
  );
  assert.deepEqual(lines, ["ACTIVE build the page"]);
  assert.equal(taskSurface([], "normal")[0], "Nothing running");
  assert.equal(
    missionListLabel({ id: "abc", objective: "build the page", status: "RUNNING" }, "normal"),
    "build the page",
  );
  assert.equal(
    missionListLabel(
      { id: "abc", objective: "build the page", status: "RUNNING" },
      "debug",
    ).includes("abc"),
    true,
  );
});

test("verification and the desktop orbit use recorded state only", () => {
  assert.equal(
    verificationLine({
      status: "PASSED",
      lines: ["exists index.html"],
      passedChecks: 2,
      totalChecks: 4,
    }),
    "2 / 4 PASSED",
  );
  assert.equal(
    verificationLine({ status: "NONE", lines: [], passedChecks: 0, totalChecks: 0 }),
    "No verification record",
  );
  assert.deepEqual(desktopOrbit({ mission: null, tasks: [], workers: [] }), []);
  const orbit = desktopOrbit({
    mission: { id: "m1", objective: "build the page", status: "RUNNING" },
    tasks: [{ id: "t1", label: "implement", status: "RUNNING" }],
    workers: [{ id: "w1", name: "Coding Worker #1", status: "RUNNING" }],
  });
  assert.equal(orbit.length, 3);
  assert.equal(orbit[0]?.label, "build the page");
  assert.equal(
    orbit.some((item) => item.label === "Worker #99"),
    false,
  );
});

test("inspect shortcut cycles the detail level", () => {
  assert.equal(
    matchShortcut({ key: ".", metaKey: false, ctrlKey: true, shiftKey: true, altKey: false })
      ?.target,
    "detail",
  );
});
