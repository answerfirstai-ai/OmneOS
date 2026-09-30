/** Level 1 copy for the desktop. Inspect and debug add operational detail. */

import type { AgentDocument, ModelDocument, TaskDocument, WorkerDocument } from "./desktop.js";
import type { DetailLevel } from "./detail.js";
import type { EvidenceView } from "./evidence.js";
import type { StageMark, LifecycleStage } from "./lifecycle.js";
import { taskLine } from "./desktop.js";

export interface StoryLine {
  mark: StageMark;
  text: string;
}

export interface StoryBeat {
  title: string;
  lines: StoryLine[];
}

export interface NamedWorker {
  id: string;
  agentId: string;
  name: string;
  status: string;
}

export interface OrbitItem {
  id: string;
  label: string;
  status: string;
}

export function displayName(id: string): string {
  if (id.trim() === "") {
    return "OMNE";
  }
  return id.slice(0, 1).toUpperCase() + id.slice(1);
}

export function statusWord(status: string): string {
  switch (status) {
    case "RUNNING":
    case "RECOVERING":
      return "ACTIVE";
    case "COMPLETED":
      return "COMPLETE";
    case "IDLE":
      return "IDLE";
    case "SPAWNED":
      return "STARTING";
    case "PAUSED":
      return "PAUSED";
    case "TERMINATED":
      return "STOPPED";
    case "DISCOVERED":
    case "AVAILABLE":
      return "READY";
    case "WAITING":
    case "QUEUED":
      return "WAITING";
    case "FAILED":
      return "FAILED";
    case "VERIFYING":
      return "VERIFYING";
    case "PLANNING":
      return "PLANNING";
    default:
      return status;
  }
}

/** Number the workers that exist. The index is their order, not a new worker. */
export function nameWorkers(workers: readonly WorkerDocument[]): NamedWorker[] {
  const byAgent = new Map<string, WorkerDocument[]>();
  for (const worker of workers) {
    const list = byAgent.get(worker.agent_id) ?? [];
    list.push(worker);
    byAgent.set(worker.agent_id, list);
  }
  const named: NamedWorker[] = [];
  for (const [agentId, list] of byAgent) {
    const ordered = [...list].sort((left, right) => left.worker_id.localeCompare(right.worker_id));
    ordered.forEach((worker, index) => {
      named.push({
        id: worker.worker_id,
        agentId,
        name: `${displayName(agentId)} Worker #${index + 1}`,
        status: worker.status,
      });
    });
  }
  return named;
}

export function workerName(
  workers: readonly NamedWorker[],
  workerId: string,
  agentId: string,
): string {
  return workers.find((worker) => worker.id === workerId)?.name ?? `${displayName(agentId)} worker`;
}

export function commandStory(input: {
  lifecycle: readonly LifecycleStage[];
  taskCount: number;
  workers: readonly { name: string; status: string }[];
  verification: EvidenceView;
}): StoryBeat[] {
  const understanding = findStage(input.lifecycle, "understanding");
  const planning = findStage(input.lifecycle, "planning");
  const execution = findStage(input.lifecycle, "execution");
  const verification = findStage(input.lifecycle, "verification");
  return [
    { title: "UNDERSTANDING", lines: understandingLines(understanding?.mark ?? "pending") },
    { title: "PLANNING", lines: planningLines(planning?.mark ?? "pending", input.taskCount) },
    { title: "WORKING", lines: workingLines(execution?.mark ?? "pending", input.workers) },
    {
      title: "VERIFYING",
      lines: verifyingLines(verification?.mark ?? "pending", input.verification),
    },
  ];
}

export function verificationLine(view: EvidenceView): string {
  if (view.status === "NONE") {
    return "No verification record";
  }
  if (view.totalChecks > 0) {
    return `${view.passedChecks} / ${view.totalChecks} ${view.status}`;
  }
  return view.status;
}

export function modelStateLabel(model: { local: boolean; lifecycle?: string }): string {
  const lifecycle = model.lifecycle ?? "unknown";
  if (lifecycle === "UNAVAILABLE" || lifecycle === "FAILED") {
    return "Unavailable";
  }
  if (lifecycle === "LOADING") {
    return "Loading";
  }
  if (lifecycle === "BUSY") {
    return "Busy";
  }
  if (lifecycle === "LOADED" || lifecycle === "IDLE") {
    return "Ready";
  }
  if (lifecycle === "AVAILABLE") {
    return model.local ? "Ready" : "Available";
  }
  if (lifecycle === "unknown") {
    return "Unknown";
  }
  return lifecycle;
}

export interface ModelCard {
  id: string;
  name: string;
  place: "Local" | "Cloud";
  state: string;
  provider: string;
  work: string | null;
}

export function modelCards(
  models: readonly ModelDocument[],
  activity: readonly { assigned_model: string | null; objective: string; status: string }[],
): { local: ModelCard[]; cloud: ModelCard[]; active: ModelCard[] } {
  const cards = models.map((model) => {
    const running = activity.find(
      (item) =>
        item.assigned_model === model.id &&
        (item.status === "RUNNING" || item.status === "VERIFYING" || item.status === "WAITING"),
    );
    const card: ModelCard = {
      id: model.id,
      name: model.model_name ?? model.id,
      place: model.local ? "Local" : "Cloud",
      state: modelStateLabel(model),
      provider: model.provider,
      work: running?.objective ?? null,
    };
    return card;
  });
  return {
    local: cards.filter((card) => card.place === "Local"),
    cloud: cards.filter((card) => card.place === "Cloud"),
    active: cards.filter((card) => card.work !== null || card.state === "Busy"),
  };
}

export function modelLines(card: ModelCard, level: DetailLevel): string[] {
  if (level === "debug") {
    return [`${card.id} ${card.provider} ${card.place.toLowerCase()} ${card.state}`];
  }
  if (level === "inspect") {
    return [`${card.name} ${card.provider} ${card.state}`];
  }
  return [`${card.name} ${card.state}`];
}

export interface AgentBoard {
  definitions: { id: string; name: string; state: string; enabled: boolean }[];
  active: NamedWorker[];
  paused: NamedWorker[];
  idle: NamedWorker[];
  stopped: NamedWorker[];
}

export function agentBoard(
  agents: readonly AgentDocument[],
  workers: readonly WorkerDocument[],
): AgentBoard {
  const named = nameWorkers(workers);
  return {
    definitions: agents.map((agent) => ({
      id: agent.id,
      name: displayName(agent.id),
      state: agent.state,
      enabled: agent.enabled,
    })),
    active: named.filter((worker) => isActiveWorker(worker.status)),
    paused: named.filter((worker) => worker.status === "PAUSED"),
    idle: named.filter((worker) => isIdleWorker(worker.status)),
    stopped: named.filter((worker) => isStoppedWorker(worker.status)),
  };
}

export function taskSurface(tasks: readonly TaskDocument[], level: DetailLevel): string[] {
  const parents = tasks.filter((task) => task.metadata?.role === "parent");
  if (level === "debug") {
    return parents.map((task) => `${task.id} ${taskLine(task)}`);
  }
  if (level === "inspect") {
    return parents.map((task) => taskLine(task));
  }
  const active = parents.filter(
    (task) => task.status !== "COMPLETED" && task.status !== "CANCELLED",
  );
  if (active.length === 0) {
    return ["Nothing running"];
  }
  return active.map((task) => `${statusWord(task.status)} ${task.objective}`);
}

export function missionListLabel(
  mission: { id: string; objective: string; status: string },
  level: DetailLevel,
): string {
  if (level === "debug") {
    return `${mission.status} ${mission.id} ${mission.objective}`;
  }
  if (level === "inspect") {
    return `${statusWord(mission.status)} ${mission.objective}`;
  }
  return mission.objective;
}

/** Entities around the core. An idle desktop has none. */
export function desktopOrbit(input: {
  mission: { id: string; objective: string; status: string } | null;
  tasks: readonly { id: string; label: string; status: string }[];
  workers: readonly { id: string; name: string; status: string }[];
}): OrbitItem[] {
  if (input.mission === null) {
    return [];
  }
  const items: OrbitItem[] = [
    { id: input.mission.id, label: input.mission.objective, status: input.mission.status },
    ...input.tasks.map((task) => ({ id: task.id, label: task.label, status: task.status })),
    ...input.workers.map((worker) => ({
      id: worker.id,
      label: worker.name,
      status: worker.status,
    })),
  ];
  return items.slice(0, 6);
}

export function orbitPoint(index: number, count: number, radius: number): { x: number; y: number } {
  const angle = -Math.PI / 2 + (index * 2 * Math.PI) / Math.max(count, 1);
  return {
    x: Math.round(Math.cos(angle) * radius),
    y: Math.round(Math.sin(angle) * radius),
  };
}

export function markGlyph(mark: StageMark): string {
  switch (mark) {
    case "done":
      return "✓";
    case "active":
      return "●";
    case "waiting":
      return "…";
    case "failed":
      return "×";
    default:
      return "○";
  }
}

function isActiveWorker(status: string): boolean {
  return (
    status === "RUNNING" ||
    status === "SPAWNED" ||
    status === "WAITING" ||
    status === "RECOVERING" ||
    status === "VERIFYING"
  );
}

function isIdleWorker(status: string): boolean {
  return status === "IDLE" || status === "DISCOVERED" || status === "AVAILABLE";
}

function isStoppedWorker(status: string): boolean {
  return status === "FAILED" || status === "TERMINATED";
}

function findStage(stages: readonly LifecycleStage[], id: string): LifecycleStage | undefined {
  return stages.find((stage) => stage.id === id);
}

function understandingLines(mark: StageMark): StoryLine[] {
  if (mark === "done") {
    return [{ mark, text: "Request understood" }];
  }
  if (mark === "active") {
    return [{ mark, text: "Understanding the request" }];
  }
  if (mark === "waiting") {
    return [{ mark, text: "OMNE needs clarification" }];
  }
  if (mark === "failed") {
    return [{ mark, text: "The request failed" }];
  }
  return [{ mark: "pending", text: "Waiting" }];
}

function tasksCreated(taskCount: number): string {
  return taskCount === 1 ? "1 task created" : `${taskCount} tasks created`;
}

function planningLines(mark: StageMark, taskCount: number): StoryLine[] {
  if (mark === "done") {
    return [{ mark, text: taskCount > 0 ? tasksCreated(taskCount) : "Plan ready" }];
  }
  if (mark === "active") {
    return [{ mark, text: "Planning" }];
  }
  if (mark === "failed") {
    return [{ mark, text: "Planning failed" }];
  }
  return [{ mark: "pending", text: "Waiting" }];
}

function workingLines(
  mark: StageMark,
  workers: readonly { name: string; status: string }[],
): StoryLine[] {
  if (workers.length > 0 && (mark === "active" || mark === "done" || mark === "waiting")) {
    return workers.map((worker) => ({
      mark: workerLineMark(worker.status),
      text: worker.name,
    }));
  }
  if (mark === "active") {
    return [{ mark, text: "Working" }];
  }
  if (mark === "done") {
    return [{ mark, text: "Finished" }];
  }
  if (mark === "failed") {
    return [{ mark, text: "Stopped" }];
  }
  if (mark === "waiting") {
    return [{ mark, text: "Waiting" }];
  }
  return [{ mark: "pending", text: "Waiting" }];
}

function verifyingLines(mark: StageMark, verification: EvidenceView): StoryLine[] {
  if (verification.status === "FAILED" || mark === "failed") {
    return [{ mark: "failed", text: "Failed" }];
  }
  if (verification.status === "PASSED") {
    return [
      {
        mark: "done",
        text:
          verification.totalChecks > 0
            ? `${verification.passedChecks} / ${verification.totalChecks} passed`
            : "Passed",
      },
    ];
  }
  if (verification.status === "INCONCLUSIVE") {
    return [{ mark: "done", text: "Inconclusive" }];
  }
  if (mark === "active") {
    return [{ mark, text: "Checking" }];
  }
  return [{ mark: "pending", text: "Waiting" }];
}

function workerLineMark(status: string): StageMark {
  if (status === "FAILED") {
    return "failed";
  }
  if (status === "PAUSED") {
    return "waiting";
  }
  if (
    status === "RUNNING" ||
    status === "SPAWNED" ||
    status === "RECOVERING" ||
    status === "WAITING" ||
    status === "VERIFYING"
  ) {
    return "active";
  }
  if (status === "COMPLETED" || status === "IDLE") {
    return "done";
  }
  return "pending";
}
