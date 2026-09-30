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
  lifecycle?: string;
  loaded?: boolean;
  model_name?: string;
}

export interface EventDocument {
  id: string;
  type: string;
  mission_id?: string;
  task_id?: string;
  payload?: Record<string, unknown>;
}

export interface MissionErrorDocument {
  code: string;
  message: string;
}

export interface MissionDocument {
  id: string;
  objective: string;
  status: string;
  updated_at?: string;
  task_id?: string;
  errors?: MissionErrorDocument[];
  decision?: string;
  decisionReason?: string;
  alternatives?: string[];
}

export interface WorkerDocument {
  worker_id: string;
  agent_id: string;
  status: string;
  current_task?: string;
  current_mission?: string;
  model?: string;
}

export interface VerificationBrief {
  status: string;
  evidence: string[];
  checks: string[];
  errors: string[];
}

export interface DecisionBrief {
  provider: string;
  model: string;
  intent: string;
  plan: string[];
  tools: string[];
  rejected_tools: string[];
  final_response: string;
  observation: string;
}

export interface ActivityDocument {
  id: string;
  parent_task: string | null;
  objective: string;
  status: string;
  assigned_agent: string | null;
  assigned_model: string | null;
  mission_id: string | null;
  verification: VerificationBrief | null;
  decision?: DecisionBrief | null;
  errors: MissionErrorDocument[];
}

export interface ConfirmationDocument {
  task_id: string;
  objective: string;
  tool_id: string;
  command: string;
  agent_id: string | null;
  mission_id: string | null;
}

export interface QuestionDocument {
  question_id: string;
  mission_id: string;
  question: string;
  task_id?: string;
}

export interface ProjectDocument {
  name: string;
  type: string;
  git_branch: string | null;
  languages: string[];
}

export interface DesktopView {
  tasks: TaskDocument[];
  agents: AgentDocument[];
  models: ModelDocument[];
  events: EventDocument[];
  voice: VoiceStatus;
  missions: MissionDocument[];
  workers: WorkerDocument[];
  activity: ActivityDocument[];
  confirmations: ConfirmationDocument[];
  questions: QuestionDocument[];
  project: ProjectDocument | null;
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

/** Describe a model from its recorded lifecycle. Missing lifecycle is not loaded. */
export function describeModel(model: ModelDocument): string {
  const location = model.local ? "local" : "cloud";
  const lifecycle = model.lifecycle ?? "unknown";
  const loaded = model.loaded === true ? "loaded" : "not loaded";
  const name = model.model_name ?? model.id;
  return `${name} ${model.provider} ${location} ${lifecycle} ${loaded}`;
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
    models: arrayOf(record["models"], isModelRecord).map(readModel),
    events: arrayOf(record["events"], isEvent).slice(-8).map(readEvent),
    voice: readVoice(record["voice"]),
    missions: arrayOf(record["missions"], isMissionRecord).map(readMission),
    workers: arrayOf(record["workers"], isWorkerRecord).map(readWorker),
    activity: arrayOf(record["activity"], isRecord).flatMap(readActivity),
    confirmations: arrayOf(record["confirmations"], isRecord).flatMap(readConfirmation),
    questions: arrayOf(record["questions"], isRecord).flatMap(readQuestion),
    project: readProject(record["project"]),
  };
}

/** Keep the last good desktop document when a later fetch fails. */
export function retainDesktop(
  current: DesktopView | null,
  update: DesktopView | null,
): DesktopView | null {
  return update ?? current;
}

/** Skip a panel repaint when its text has not changed. */
export function shouldRepaint(previous: string | null, next: string): boolean {
  return previous !== next;
}

const ACTIVE_MISSION = [
  "WAITING",
  "RUNNING",
  "RECOVERING",
  "VERIFYING",
  "PLANNING",
  "ANALYZING",
  "READY",
  "PAUSED",
];

/** Prefer the mission that currently needs attention. */
export function activeMission(missions: readonly MissionDocument[]): MissionDocument | null {
  for (const status of ACTIVE_MISSION) {
    const match = missions.find((mission) => mission.status === status);
    if (match !== undefined) {
      return match;
    }
  }
  return null;
}

/** The mission the user just submitted, otherwise the most recently updated one. */
export function chooseMission(
  missions: readonly MissionDocument[],
  objective: string | null,
): MissionDocument | null {
  if (missions.length === 0) {
    return null;
  }
  if (objective !== null && objective !== "") {
    const matches = missions.filter((mission) => mission.objective === objective);
    if (matches.length > 0) {
      return latestMission(matches);
    }
  }
  return latestMission(missions);
}

export function attentionLine(
  questions: readonly QuestionDocument[],
  confirmations: readonly ConfirmationDocument[],
): string | null {
  const confirmation = confirmations[0];
  if (confirmation !== undefined) {
    return `Permission: ${confirmation.command}`;
  }
  const question = questions[0];
  if (question !== undefined) {
    return question.question;
  }
  return null;
}

/** The waiting confirmation or question the cancel action should stop. */
export function waitingCancelTarget(input: {
  confirmations: readonly ConfirmationDocument[];
  questions: readonly QuestionDocument[];
}): { kind: "task" | "mission"; id: string } | null {
  const confirmation = input.confirmations[0];
  if (confirmation !== undefined && confirmation.task_id !== "") {
    return { kind: "task", id: confirmation.task_id };
  }
  const question = input.questions[0];
  if (question === undefined) {
    return null;
  }
  if (question.task_id !== undefined && question.task_id !== "") {
    return { kind: "task", id: question.task_id };
  }
  if (question.mission_id !== "") {
    return { kind: "mission", id: question.mission_id };
  }
  return null;
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

function isModelRecord(value: unknown): value is Record<string, unknown> {
  return (
    isRecord(value) &&
    typeof value["id"] === "string" &&
    typeof value["provider"] === "string" &&
    typeof value["local"] === "boolean"
  );
}

function readModel(value: Record<string, unknown>): ModelDocument {
  const model: ModelDocument = {
    id: stringField(value, "id"),
    provider: stringField(value, "provider"),
    local: value["local"] === true,
  };
  if (typeof value["lifecycle"] === "string") {
    model.lifecycle = value["lifecycle"];
  }
  if (typeof value["loaded"] === "boolean") {
    model.loaded = value["loaded"];
  }
  if (typeof value["model_name"] === "string") {
    model.model_name = value["model_name"];
  }
  return model;
}

function readEvent(value: Record<string, unknown>): EventDocument {
  const event: EventDocument = {
    id: stringField(value, "id"),
    type: stringField(value, "type"),
  };
  if (typeof value["mission_id"] === "string") {
    event.mission_id = value["mission_id"];
  }
  if (typeof value["task_id"] === "string") {
    event.task_id = value["task_id"];
  }
  if (isRecord(value["payload"])) {
    event.payload = value["payload"];
  }
  return event;
}

function isMissionRecord(value: unknown): value is Record<string, unknown> {
  return (
    isRecord(value) &&
    typeof value["id"] === "string" &&
    typeof value["objective"] === "string" &&
    typeof value["status"] === "string"
  );
}

function isWorkerRecord(value: unknown): value is Record<string, unknown> {
  return (
    isRecord(value) &&
    typeof value["worker_id"] === "string" &&
    typeof value["agent_id"] === "string" &&
    typeof value["status"] === "string"
  );
}

function isEvent(value: unknown): value is Record<string, unknown> {
  return isRecord(value) && typeof value["id"] === "string" && typeof value["type"] === "string";
}

function readMission(value: Record<string, unknown>): MissionDocument {
  const mission: MissionDocument = {
    id: stringField(value, "id"),
    objective: stringField(value, "objective"),
    status: stringField(value, "status"),
  };
  if (typeof value["updated_at"] === "string") {
    mission.updated_at = value["updated_at"];
  }
  if (typeof value["task_id"] === "string") {
    mission.task_id = value["task_id"];
  }
  const errors = readErrors(value["errors"]);
  if (errors.length > 0) {
    mission.errors = errors;
  }
  const metadata = isRecord(value["metadata"]) ? value["metadata"] : null;
  const decision =
    metadata !== null && isRecord(metadata["decision"]) ? metadata["decision"] : null;
  if (decision !== null && typeof decision["decision"] === "string") {
    mission.decision = decision["decision"];
  }
  if (decision !== null && typeof decision["reason"] === "string") {
    mission.decisionReason = decision["reason"];
  }
  if (decision !== null && Array.isArray(decision["alternatives"])) {
    const alternatives = decision["alternatives"].filter(
      (item): item is string => typeof item === "string",
    );
    if (alternatives.length > 0) {
      mission.alternatives = alternatives;
    }
  }
  return mission;
}

function readWorker(value: Record<string, unknown>): WorkerDocument {
  const worker: WorkerDocument = {
    worker_id: stringField(value, "worker_id"),
    agent_id: stringField(value, "agent_id"),
    status: stringField(value, "status"),
  };
  if (typeof value["current_task"] === "string") {
    worker.current_task = value["current_task"];
  }
  if (typeof value["current_mission"] === "string") {
    worker.current_mission = value["current_mission"];
  }
  if (typeof value["model"] === "string") {
    worker.model = value["model"];
  }
  return worker;
}

function readActivity(value: Record<string, unknown>): ActivityDocument[] {
  if (
    typeof value["id"] !== "string" ||
    typeof value["objective"] !== "string" ||
    typeof value["status"] !== "string"
  ) {
    return [];
  }
  const activity: ActivityDocument = {
    id: value["id"],
    parent_task: typeof value["parent_task"] === "string" ? value["parent_task"] : null,
    objective: value["objective"],
    status: value["status"],
    assigned_agent: typeof value["assigned_agent"] === "string" ? value["assigned_agent"] : null,
    assigned_model: typeof value["assigned_model"] === "string" ? value["assigned_model"] : null,
    mission_id: typeof value["mission_id"] === "string" ? value["mission_id"] : null,
    verification: readVerification(value["verification"]),
    decision: readDecision(value["decision"]),
    errors: readErrors(value["errors"]),
  };
  return [activity];
}

function readConfirmation(value: Record<string, unknown>): ConfirmationDocument[] {
  if (
    typeof value["task_id"] !== "string" ||
    typeof value["objective"] !== "string" ||
    typeof value["tool_id"] !== "string" ||
    typeof value["command"] !== "string"
  ) {
    return [];
  }
  return [
    {
      task_id: value["task_id"],
      objective: value["objective"],
      tool_id: value["tool_id"],
      command: value["command"],
      agent_id: typeof value["agent_id"] === "string" ? value["agent_id"] : null,
      mission_id: typeof value["mission_id"] === "string" ? value["mission_id"] : null,
    },
  ];
}

function readQuestion(value: Record<string, unknown>): QuestionDocument[] {
  if (
    typeof value["question_id"] !== "string" ||
    typeof value["mission_id"] !== "string" ||
    typeof value["question"] !== "string"
  ) {
    return [];
  }
  return [
    {
      question_id: value["question_id"],
      mission_id: value["mission_id"],
      question: value["question"],
      ...(typeof value["task_id"] === "string" ? { task_id: value["task_id"] } : {}),
    },
  ];
}

function readProject(value: unknown): ProjectDocument | null {
  if (!isRecord(value) || typeof value["name"] !== "string" || typeof value["type"] !== "string") {
    return null;
  }
  const languages = Array.isArray(value["languages"])
    ? value["languages"].filter((item): item is string => typeof item === "string")
    : [];
  return {
    name: value["name"],
    type: value["type"],
    git_branch: typeof value["git_branch"] === "string" ? value["git_branch"] : null,
    languages,
  };
}

function readDecision(value: unknown): DecisionBrief | null {
  if (!isRecord(value)) {
    return null;
  }
  return {
    provider: typeof value["provider"] === "string" ? value["provider"] : "",
    model: typeof value["model"] === "string" ? value["model"] : "",
    intent: typeof value["intent"] === "string" ? value["intent"] : "",
    plan: stringList(value["plan"]),
    tools: stringList(value["tools"]),
    rejected_tools: stringList(value["rejected_tools"]),
    final_response: typeof value["final_response"] === "string" ? value["final_response"] : "",
    observation: typeof value["observation"] === "string" ? value["observation"] : "",
  };
}

function readVerification(value: unknown): VerificationBrief | null {
  if (!isRecord(value) || typeof value["status"] !== "string") {
    return null;
  }
  return {
    status: value["status"],
    evidence: stringList(value["evidence"]),
    checks: stringList(value["checks"]),
    errors: stringList(value["errors"]),
  };
}

function readErrors(value: unknown): MissionErrorDocument[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.flatMap((item) => {
    if (
      !isRecord(item) ||
      typeof item["code"] !== "string" ||
      typeof item["message"] !== "string"
    ) {
      return [];
    }
    return [{ code: item["code"], message: item["message"] }];
  });
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is string => typeof item === "string");
}

function stringField(value: Record<string, unknown>, key: string): string {
  const field = value[key];
  return typeof field === "string" ? field : "";
}

function latestMission(missions: readonly MissionDocument[]): MissionDocument {
  return [...missions].sort((left, right) =>
    (left.updated_at ?? "").localeCompare(right.updated_at ?? ""),
  )[missions.length - 1]!;
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
