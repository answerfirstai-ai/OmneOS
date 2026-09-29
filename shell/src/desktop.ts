/** Pure helpers for the desktop panels. */

import type { VoiceStatus } from "./voice.js";

export interface TaskDocument {
  id: string;
  objective: string;
  status: string;
  metadata?: { role?: string };
}

export interface AgentDocument {
  id: string;
  state: string;
  enabled: boolean;
}

export interface ModelDocument {
  id: string;
  provider: string;
  local: boolean;
}

export interface EventDocument {
  id: string;
  type: string;
}

export interface MissionDocument {
  id: string;
  objective: string;
  status: string;
}

export interface WorkerDocument {
  worker_id: string;
  agent_id: string;
  status: string;
}

export interface DesktopView {
  tasks: TaskDocument[];
  agents: AgentDocument[];
  models: ModelDocument[];
  events: EventDocument[];
  voice: VoiceStatus;
  missions: MissionDocument[];
  workers: WorkerDocument[];
}

export function parentTasks(tasks: readonly TaskDocument[]): TaskDocument[] {
  return tasks.filter((task) => task.metadata?.role === "parent");
}

export function taskLine(task: TaskDocument): string {
  return `${task.status} ${task.objective}`;
}

export function agentLine(agent: AgentDocument): string {
  const enabled = agent.enabled ? "enabled" : "disabled";
  return `${agent.id} ${agent.state} ${enabled}`;
}

export function modelLine(model: ModelDocument): string {
  const location = model.local ? "local" : "cloud";
  return `${model.id} ${model.provider} ${location}`;
}

export function notificationLine(event: EventDocument): string {
  return `${event.type}`;
}

export function missionLine(mission: MissionDocument): string {
  return `${mission.status} ${mission.objective}`;
}

export function workerLine(worker: WorkerDocument): string {
  return `${worker.agent_id} ${worker.status}`;
}

/** Read one `/desktop` document. Missing fields stay empty. */
export function readDesktop(payload: unknown): DesktopView {
  const record = isRecord(payload) ? payload : {};
  return {
    tasks: arrayOf(record["tasks"], isTask),
    agents: arrayOf(record["agents"], isAgent),
    models: arrayOf(record["models"], isModel),
    events: arrayOf(record["events"], isEvent).slice(-8),
    voice: readVoice(record["voice"]),
    missions: arrayOf(record["missions"], isMission),
    workers: arrayOf(record["workers"], isWorker),
  };
}

function arrayOf<T>(value: unknown, guard: (item: unknown) => item is T): T[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter(guard);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isTask(value: unknown): value is TaskDocument {
  if (!isRecord(value)) {
    return false;
  }
  return (
    typeof value["id"] === "string" &&
    typeof value["objective"] === "string" &&
    typeof value["status"] === "string"
  );
}

function isAgent(value: unknown): value is AgentDocument {
  if (!isRecord(value)) {
    return false;
  }
  return (
    typeof value["id"] === "string" &&
    typeof value["state"] === "string" &&
    typeof value["enabled"] === "boolean"
  );
}

function isModel(value: unknown): value is ModelDocument {
  if (!isRecord(value)) {
    return false;
  }
  return (
    typeof value["id"] === "string" &&
    typeof value["provider"] === "string" &&
    typeof value["local"] === "boolean"
  );
}

function isMission(value: unknown): value is MissionDocument {
  if (!isRecord(value)) {
    return false;
  }
  return (
    typeof value["id"] === "string" &&
    typeof value["objective"] === "string" &&
    typeof value["status"] === "string"
  );
}

function isWorker(value: unknown): value is WorkerDocument {
  if (!isRecord(value)) {
    return false;
  }
  return (
    typeof value["worker_id"] === "string" &&
    typeof value["agent_id"] === "string" &&
    typeof value["status"] === "string"
  );
}

function isEvent(value: unknown): value is EventDocument {
  if (!isRecord(value)) {
    return false;
  }
  return typeof value["id"] === "string" && typeof value["type"] === "string";
}

function readVoice(value: unknown): VoiceStatus {
  if (!isRecord(value)) {
    return {
      provider: "unavailable",
      hardware: "unavailable",
      permission: "unknown",
      listening: false,
      reason: "voice status was not returned",
    };
  }
  const status: VoiceStatus = {
    provider: typeof value["provider"] === "string" ? value["provider"] : "unavailable",
    hardware: typeof value["hardware"] === "string" ? value["hardware"] : "unavailable",
    permission: typeof value["permission"] === "string" ? value["permission"] : "unknown",
    listening: value["listening"] === true,
  };
  if (typeof value["reason"] === "string") {
    status.reason = value["reason"];
  }
  return status;
}
