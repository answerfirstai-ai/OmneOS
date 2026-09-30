/** Live mission inspection assembled from desktop records. */

import type {
  ActivityDocument,
  DecisionBrief,
  MissionDocument,
  ModelDocument,
  QuestionDocument,
  WorkerDocument,
} from "./desktop.js";
import {
  evidenceSummary,
  evidenceView,
  explainFailure,
  type ErrorView,
  type EvidenceView,
} from "./evidence.js";
import type { HudLine } from "./hud.js";
import { lifecycleStages, type LifecycleStage } from "./lifecycle.js";

export interface MissionTaskRow {
  id: string;
  label: string;
  mark: "done" | "active" | "pending" | "failed";
  status: string;
}

export interface MissionWorkerRow {
  workerId: string;
  agentId: string;
  status: string;
  model: string | null;
}

export interface MissionModelRow {
  id: string;
  provider: string;
  local: boolean;
  lifecycle: string;
  loaded: boolean;
}

export interface WorkerGroup {
  agentId: string;
  workers: { workerId: string; status: string }[];
}

export interface MissionInspection {
  id: string;
  objective: string;
  status: string;
  workers: MissionWorkerRow[];
  models: MissionModelRow[];
  tasks: MissionTaskRow[];
  resources: HudLine[];
  verification: EvidenceView;
  error: ErrorView | null;
  question: string | null;
  path: string[];
  lifecycle: LifecycleStage[];
}

export function inspectMission(
  mission: MissionDocument,
  input: {
    activity: readonly ActivityDocument[];
    workers: readonly WorkerDocument[];
    models: readonly ModelDocument[];
    questions: readonly QuestionDocument[];
    resources: readonly HudLine[];
  },
): MissionInspection {
  const activity = input.activity.filter(
    (item) => item.mission_id === mission.id || item.parent_task === mission.task_id,
  );
  const workers = input.workers
    .filter((worker) => worker.current_mission === mission.id)
    .map((worker) => ({
      workerId: worker.worker_id,
      agentId: worker.agent_id,
      status: worker.status,
      model: worker.model ?? null,
    }));
  const modelIds = unique(
    activity.flatMap((item) => (item.assigned_model === null ? [] : [item.assigned_model])),
  );
  const models = modelIds.map((id) => {
    const known = input.models.find((model) => model.id === id);
    return {
      id,
      provider: known?.provider ?? "unknown",
      local: known?.local ?? false,
      lifecycle: known?.lifecycle ?? "unknown",
      loaded: known?.loaded === true,
    };
  });
  const verification = evidenceSummary(activity.map((item) => evidenceView(item.verification)));
  const error =
    mission.status === "FAILED"
      ? explainFailure({
          code: mission.errors?.[0]?.code ?? null,
          message: mission.errors?.[0]?.message ?? mission.decisionReason ?? "",
          decision: mission.decision ?? null,
          alternatives: mission.alternatives ?? [],
        })
      : null;
  const question = input.questions.find((item) => item.mission_id === mission.id)?.question ?? null;
  const waitingOn =
    mission.status !== "WAITING" ? "none" : question !== null ? "question" : "confirmation";
  const decision = activity.find((item) => item.decision != null)?.decision ?? null;
  return {
    id: mission.id,
    objective: mission.objective,
    status: mission.status,
    workers,
    models,
    tasks: activity.map((item) => ({
      id: item.id,
      label: item.objective,
      mark: taskMark(item.status),
      status: item.status,
    })),
    resources: [...input.resources],
    verification,
    error,
    question,
    path: decisionLines(decision),
    lifecycle: lifecycleStages({
      objective: mission.objective,
      missionStatus: mission.status,
      decision: mission.decision ?? null,
      assignedAgents: unique(
        activity.flatMap((item) => (item.assigned_agent === null ? [] : [item.assigned_agent])),
      ),
      assignedModels: modelIds,
      waitingOn,
      hasActivity: activity.length > 0,
      verificationStatus: aggregateStatus(verification.status),
      errorMessage: mission.errors?.[0]?.message ?? null,
    }),
  };
}

/** Group real workers under their agent definition. */
export function groupWorkers(workers: readonly WorkerDocument[]): WorkerGroup[] {
  const groups = new Map<string, { workerId: string; status: string }[]>();
  for (const worker of workers) {
    const rows = groups.get(worker.agent_id) ?? [];
    rows.push({ workerId: worker.worker_id, status: worker.status });
    groups.set(worker.agent_id, rows);
  }
  return [...groups.entries()]
    .sort((left, right) => left[0].localeCompare(right[0]))
    .map(([agentId, rows]) => ({ agentId, workers: rows }));
}

export function taskMark(status: string): MissionTaskRow["mark"] {
  if (status === "COMPLETED") {
    return "done";
  }
  if (status === "FAILED" || status === "CANCELLED") {
    return "failed";
  }
  if (status === "QUEUED" || status === "PLANNING") {
    return "pending";
  }
  return "active";
}

/** Lines for the request, model, tools, observation, and result. */
export function decisionLines(decision: DecisionBrief | null | undefined): string[] {
  if (decision === null || decision === undefined) {
    return [];
  }
  const model = [decision.provider, decision.model].filter((item) => item !== "").join(" ");
  const lines = [`Model: ${model === "" ? "unknown" : model}`];
  if (decision.intent !== "") {
    lines.push(`Intent: ${decision.intent}`);
  }
  if (decision.plan.length > 0) {
    lines.push(`Plan: ${decision.plan.join("; ")}`);
  }
  lines.push(decision.tools.length > 0 ? `Tools: ${decision.tools.join(", ")}` : "Tools: none");
  if (decision.rejected_tools.length > 0) {
    lines.push(`Rejected: ${decision.rejected_tools.join(", ")}`);
  }
  if (decision.observation !== "") {
    lines.push(`Observation: ${decision.observation}`);
  }
  if (decision.final_response !== "") {
    lines.push(`Result: ${decision.final_response}`);
  }
  return lines;
}

function aggregateStatus(status: EvidenceView["status"]): string | null {
  if (status === "PASSED") {
    return "PASS";
  }
  if (status === "FAILED") {
    return "FAIL";
  }
  if (status === "INCONCLUSIVE") {
    return "INCONCLUSIVE";
  }
  return null;
}

function unique(values: readonly string[]): string[] {
  return [...new Set(values)];
}
