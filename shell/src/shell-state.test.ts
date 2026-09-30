import assert from "node:assert/strict";
import test from "node:test";

import { evidenceSummary, evidenceView, explainFailure } from "./evidence.js";
import { environmentState } from "./environment.js";
import {
  cameraForNode,
  graphKey,
  layoutGraph,
  panCamera,
  readGraph,
  selectGraphNode,
  zoomCamera,
} from "./graph-layout.js";
import { hudText, readCompute, resourcePressure } from "./hud.js";
import { lifecycleStages } from "./lifecycle.js";
import { groupWorkers, inspectMission, taskMark } from "./mission-view.js";
import { noticesFromEvents } from "./notify.js";
import { permissionPrompt } from "./permission-view.js";
import { presenceView } from "./presence.js";
import { matchShortcut } from "./shortcuts.js";

test("environment follows mission status and a real routing event", () => {
  assert.equal(
    environmentState({ coreOk: true, voiceListening: false, statuses: ["WAITING"] }),
    "PLANNING",
  );
  assert.equal(
    environmentState({ coreOk: true, voiceListening: false, statuses: ["RUNNING"] }),
    "WORKING",
  );
  assert.equal(
    environmentState({ coreOk: true, voiceListening: false, statuses: ["COMPLETED"] }),
    "SUCCESS",
  );
  assert.equal(
    environmentState({ coreOk: true, voiceListening: false, statuses: ["FAILED"] }),
    "ERROR",
  );
  assert.equal(environmentState({ coreOk: false, voiceListening: true, statuses: [] }), "ERROR");
  assert.equal(
    environmentState({
      coreOk: true,
      voiceListening: false,
      statuses: [],
      missionStatuses: ["ANALYZING"],
    }),
    "UNDERSTANDING",
  );
  assert.equal(
    environmentState({
      coreOk: true,
      voiceListening: false,
      statuses: [],
      missionStatuses: ["PLANNING"],
    }),
    "PLANNING",
  );
  assert.equal(
    environmentState({
      coreOk: true,
      voiceListening: false,
      statuses: [],
      missionStatuses: ["PLANNING"],
      latestEvent: "decision.selected",
    }),
    "ROUTING",
  );
  assert.equal(
    environmentState({
      coreOk: true,
      voiceListening: false,
      statuses: [],
      missionStatuses: ["VERIFYING"],
    }),
    "VERIFYING",
  );
});

test("presence keeps a visible label and does not invent an asset", () => {
  const idle = presenceView({ coreOk: true, voiceListening: false, statuses: [] });
  const working = presenceView({ coreOk: true, voiceListening: false, statuses: ["RUNNING"] });

  assert.equal(idle.state, "IDLE");
  assert.equal(idle.label, "IDLE");
  assert.equal(idle.motion, "still");
  assert.equal(idle.asset, null);
  assert.equal(working.motion, "steady");
  assert.equal(working.label, "WORKING");
});

test("lifecycle stays pending until selection evidence exists", () => {
  const planning = lifecycleStages({
    objective: "write file notes.txt with content hello",
    missionStatus: "PLANNING",
    decision: "DIRECT_TOOL",
    assignedAgents: [],
    assignedModels: [],
    waitingOn: "none",
    hasActivity: false,
    verificationStatus: null,
    errorMessage: null,
  });
  assert.equal(planning.find((stage) => stage.id === "planning")?.mark, "active");
  assert.equal(planning.find((stage) => stage.id === "agent")?.mark, "pending");
  assert.equal(planning.find((stage) => stage.id === "model")?.mark, "pending");

  const running = lifecycleStages({
    objective: "write file notes.txt with content hello",
    missionStatus: "RUNNING",
    decision: "DIRECT_TOOL",
    assignedAgents: ["coding"],
    assignedModels: ["mock-default"],
    waitingOn: "none",
    hasActivity: true,
    verificationStatus: null,
    errorMessage: null,
  });
  assert.equal(running.find((stage) => stage.id === "agent")?.mark, "done");
  assert.equal(running.find((stage) => stage.id === "model")?.mark, "done");
  assert.equal(running.find((stage) => stage.id === "execution")?.mark, "active");
  assert.equal(running.find((stage) => stage.id === "verification")?.detail, "");

  const done = lifecycleStages({
    objective: "write file notes.txt with content hello",
    missionStatus: "COMPLETED",
    decision: "DIRECT_TOOL",
    assignedAgents: ["coding"],
    assignedModels: [],
    waitingOn: "none",
    hasActivity: true,
    verificationStatus: "PASS",
    errorMessage: null,
  });
  assert.equal(done.find((stage) => stage.id === "model")?.mark, "pending");
  assert.equal(done.find((stage) => stage.id === "verification")?.detail, "PASSED");
  assert.equal(done.find((stage) => stage.id === "result")?.mark, "done");
});

test("mission inspection uses child activity and does not invent workers", () => {
  const view = inspectMission(
    {
      id: "mission-1",
      objective: "write file notes.txt with content hello",
      status: "COMPLETED",
      task_id: "parent-1",
      decision: "DIRECT_TOOL",
    },
    {
      activity: [
        {
          id: "child-1",
          parent_task: "parent-1",
          objective: "write notes",
          status: "COMPLETED",
          assigned_agent: "coding",
          assigned_model: "mock-default",
          mission_id: "mission-1",
          verification: {
            status: "PASS",
            evidence: ["exists notes.txt"],
            checks: ["written file exists"],
            errors: [],
          },
          errors: [],
        },
      ],
      workers: [
        {
          worker_id: "worker-1",
          agent_id: "coding",
          status: "IDLE",
          current_mission: "mission-1",
        },
        {
          worker_id: "worker-2",
          agent_id: "research",
          status: "IDLE",
          current_mission: "other",
        },
      ],
      models: [
        {
          id: "mock-default",
          provider: "mock",
          local: false,
          lifecycle: "AVAILABLE",
          loaded: false,
        },
      ],
      questions: [],
      resources: [{ label: "CPU", value: "unknown" }],
    },
  );

  assert.equal(view.workers.length, 1);
  assert.equal(view.workers[0]?.status, "IDLE");
  assert.equal(view.models[0]?.lifecycle, "AVAILABLE");
  assert.equal(view.models[0]?.loaded, false);
  assert.equal(view.tasks[0]?.mark, "done");
  assert.equal(view.verification.status, "PASSED");
  assert.equal(view.verification.lines.includes("exists notes.txt"), true);
  assert.equal(view.resources[0]?.value, "unknown");
  assert.equal(taskMark("QUEUED"), "pending");
});

test("workers stay grouped under the agents that own them", () => {
  const groups = groupWorkers([
    { worker_id: "b", agent_id: "coding", status: "IDLE" },
    { worker_id: "a", agent_id: "coding", status: "RUNNING" },
    { worker_id: "c", agent_id: "research", status: "WAITING" },
  ]);

  assert.deepEqual(
    groups.map((group) => group.agentId),
    ["coding", "research"],
  );
  assert.equal(groups[0]?.workers.length, 2);
  assert.equal(groups[1]?.workers[0]?.status, "WAITING");
});

test("permission copy names the command and the agent", () => {
  const install = permissionPrompt({
    taskId: "task-1",
    toolId: "terminal.execute",
    command: "npm install",
    agentId: "coding",
    missionObjective: "Build website",
  });
  assert.equal(install.command, "npm install");
  assert.equal(install.impact, "Downloads packages and modifies node_modules.");
  assert.equal(install.requester, "coding");
  assert.equal(install.mission, "Build website");
  assert.equal(install.reason.includes("requires confirmation"), false);

  const echo = permissionPrompt({
    taskId: "task-2",
    toolId: "terminal.execute",
    command: "echo hello",
    agentId: null,
    missionObjective: null,
  });
  assert.equal(echo.impact, "Runs the command inside the workspace.");
  assert.equal(echo.requester, "OMNE");
});

test("verification evidence is not a pass when it is missing or inconclusive", () => {
  assert.equal(evidenceView(null).status, "NONE");
  assert.equal(
    evidenceView({
      status: "INCONCLUSIVE",
      evidence: [],
      checks: ["no file evidence was required"],
      errors: [],
    }).status,
    "INCONCLUSIVE",
  );
  const summary = evidenceSummary([
    evidenceView({
      status: "PASS",
      evidence: ["exists index.html"],
      checks: ["written file exists"],
      errors: [],
    }),
    evidenceView({
      status: "FAIL",
      evidence: [],
      checks: ["written file exists"],
      errors: ["missing file index.html"],
    }),
  ]);
  assert.equal(summary.status, "FAILED");
  assert.equal(summary.lines.includes("exists index.html"), true);
});

test("errors explain the failure and keep tracebacks out of the summary", () => {
  const error = explainFailure({
    code: "execution_failed",
    message: 'Traceback (most recent call last):\n  File "executor.py"',
    decision: "DIRECT_TOOL",
    alternatives: ["HYBRID"],
  });

  assert.equal(error.what.includes("Traceback"), false);
  assert.equal(error.why.includes("Traceback"), false);
  assert.equal(error.why, "OMNE recorded an internal error.");
  assert.equal(error.tried[0], "HYBRID");
  assert.equal(error.technical.includes("Traceback"), true);
});

test("notifications come from event types and link to a mission", () => {
  const notices = noticesFromEvents([
    {
      id: "1",
      type: "permission.requested",
      mission_id: "mission-1",
      task_id: "task-1",
    },
    { id: "2", type: "verification.recorded", payload: { status: "FAIL" } },
    { id: "3", type: "decision.selected", payload: { decision: "LOCAL_MODEL" } },
    { id: "4", type: "cache.hit" },
  ]);

  assert.equal(notices[0]?.text, "OMNE needs your permission.");
  assert.equal(notices[0]?.missionId, "mission-1");
  assert.equal(notices[1]?.text, "Verification failed.");
  assert.equal(notices[2]?.text, "OMNE selected a local model.");
  assert.equal(notices[2]?.text.includes("Switching"), false);
  assert.equal(notices[3]?.text, "cache.hit");
});

test("the graph places only the nodes it was given", () => {
  const layout = layoutGraph(
    [
      { id: "core", type: "core", label: "OMNE Core" },
      { id: "mission-1", type: "mission", label: "write notes" },
      { id: "task-1", type: "task", label: "write notes" },
    ],
    [{ from: "core", to: "mission-1", type: "owns" }],
  );
  assert.deepEqual(
    layout.nodes.map((node) => node.id),
    ["core", "mission-1", "task-1"],
  );
  assert.equal(layout.edges.length, 1);
  assert.equal((layout.nodes[0]?.column ?? 0) < (layout.nodes[2]?.column ?? 0), true);

  const sparse = readGraph({
    nodes: [{ id: "core", type: "core", label: "OMNE Core" }],
    edges: [],
  });
  assert.equal(sparse.nodes.length, 1);
  const moved = panCamera(selectGraphNode(layoutCamera(sparse), "core"), 4, -2);
  assert.equal(moved.selectedId, "core");
  assert.equal(moved.x, 20);
  assert.equal(zoomCamera(moved, 10).scale, 2.5);
  const focused = cameraForNode(moved, sparse.nodes[0] ?? null, { width: 200, height: 100 });
  assert.equal(focused.selectedId, "core");
  assert.equal(graphKey(sparse, new Map()) === graphKey(layout, new Map()), false);
});

test("resource lines keep unknown and unavailable values", () => {
  const lines = readCompute({
    compute: {
      cpu: { usage_percent: null },
      memory: { used_mb: 8400, total_mb: 16000 },
      gpu: { available: false, usage_percent: null, vram_used_mb: null, vram_total_mb: null },
      disk: { used_mb: null, total_mb: null },
      network: { available: true, interfaces: [{ name: "lo", rx_bytes: 1, tx_bytes: 1 }] },
    },
  });
  assert.equal(lines.find((line) => line.label === "CPU")?.value, "unknown");
  assert.equal(lines.find((line) => line.label === "GPU")?.value, "unavailable");
  assert.equal(lines.find((line) => line.label === "VRAM")?.value, "unknown");
  assert.equal(lines.find((line) => line.label === "RAM")?.value, "8.2 GB / 15.6 GB");
  assert.equal(lines.find((line) => line.label === "Network")?.value, "1 interface");
  assert.equal(lines.find((line) => line.label === "Thermal")?.value, "unknown");
  assert.equal(resourcePressure(lines), null);
  assert.equal(resourcePressure([{ label: "CPU", value: "94%" }]), "CPU pressure 94%");
  assert.equal(hudText(lines).includes("unavailable"), true);
});

test("keyboard shortcuts open the palette and the desktop windows", () => {
  assert.equal(
    matchShortcut({ key: " ", metaKey: true, ctrlKey: false, shiftKey: false, altKey: false })
      ?.target,
    "palette",
  );
  assert.equal(
    matchShortcut({ key: "m", metaKey: false, ctrlKey: true, shiftKey: true, altKey: false })
      ?.target,
    "missions",
  );
  assert.equal(
    matchShortcut({ key: "g", metaKey: true, ctrlKey: false, shiftKey: true, altKey: false })
      ?.target,
    "graph",
  );
  assert.equal(
    matchShortcut({ key: "m", metaKey: false, ctrlKey: false, shiftKey: false, altKey: false }),
    null,
  );
  assert.equal(
    matchShortcut({ key: "m", metaKey: false, ctrlKey: true, shiftKey: false, altKey: false }),
    null,
  );
});

function layoutCamera(layout: ReturnType<typeof layoutGraph>) {
  return selectGraphNode({ x: 16, y: 16, scale: 1, selectedId: null }, layout.nodes[0]?.id ?? null);
}
