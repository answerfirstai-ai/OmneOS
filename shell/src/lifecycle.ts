/** Inspectable mission lifecycle derived from recorded status and assignments. */

export type StageMark = "done" | "active" | "waiting" | "pending" | "failed";

export interface LifecycleStage {
  id: string;
  label: string;
  mark: StageMark;
  detail: string;
}

export interface LifecycleInput {
  objective: string;
  missionStatus: string;
  decision: string | null;
  assignedAgents: readonly string[];
  assignedModels: readonly string[];
  waitingOn: "question" | "confirmation" | "none";
  hasActivity: boolean;
  verificationStatus: string | null;
  errorMessage: string | null;
}

const STAGES: readonly { id: string; label: string }[] = [
  { id: "request", label: "USER REQUEST" },
  { id: "understanding", label: "UNDERSTANDING" },
  { id: "planning", label: "PLANNING" },
  { id: "resources", label: "RESOURCE ANALYSIS" },
  { id: "agent", label: "AGENT SELECTION" },
  { id: "model", label: "MODEL SELECTION" },
  { id: "execution", label: "EXECUTION" },
  { id: "verification", label: "VERIFICATION" },
  { id: "result", label: "RESULT" },
];

const MODEL_DECISIONS = new Set(["LOCAL_MODEL", "CLOUD_MODEL", "HYBRID"]);
const AGENT_DECISIONS = new Set([
  "DIRECT_TOOL",
  "LOCAL_MODEL",
  "CLOUD_MODEL",
  "HYBRID",
  "DEFER",
  "WAIT",
]);

/** Build the nine lifecycle stages. Selection is done only when evidence exists. */
export function lifecycleStages(input: LifecycleInput): LifecycleStage[] {
  const marks = baseMarks(input);
  return STAGES.map((stage) => ({
    id: stage.id,
    label: stage.label,
    mark: marks[stage.id] ?? "pending",
    detail: detailFor(stage.id, input, marks[stage.id] ?? "pending"),
  }));
}

export function stageLine(stage: LifecycleStage): string {
  return stage.detail === ""
    ? `${stage.mark} ${stage.label}`
    : `${stage.mark} ${stage.label} ${stage.detail}`;
}

function baseMarks(input: LifecycleInput): Record<string, StageMark> {
  const phase = phaseIndex(input);
  if (input.missionStatus === "FAILED") {
    return failedMarks(input);
  }
  if (input.missionStatus === "CANCELLED") {
    return cancelledMarks(input);
  }
  const marks: Record<string, StageMark> = {};
  for (const stage of STAGES) {
    const index = STAGES.findIndex((item) => item.id === stage.id);
    if (stage.id === "agent" || stage.id === "model") {
      marks[stage.id] = selectionMark(stage.id, input, phase);
      continue;
    }
    if (index < phase) {
      marks[stage.id] = "done";
    } else if (index === phase) {
      marks[stage.id] =
        input.missionStatus === "WAITING" || input.missionStatus === "PAUSED"
          ? "waiting"
          : "active";
    } else {
      marks[stage.id] = "pending";
    }
  }
  if (input.missionStatus === "COMPLETED") {
    marks["result"] = "done";
  }
  return marks;
}

function failedMarks(input: LifecycleInput): Record<string, StageMark> {
  const early = input.decision === "DENY" || !input.hasActivity;
  return {
    request: "done",
    understanding: "done",
    planning: early ? "pending" : "done",
    resources: early ? "pending" : "done",
    agent: early ? "pending" : selectionMark("agent", input, 6),
    model: early ? "pending" : selectionMark("model", input, 6),
    execution: early ? "pending" : "failed",
    verification: input.verificationStatus === "FAIL" ? "failed" : "pending",
    result: "failed",
  };
}

function cancelledMarks(input: LifecycleInput): Record<string, StageMark> {
  const progressed = input.hasActivity;
  return {
    request: "done",
    understanding: "done",
    planning: progressed ? "done" : "pending",
    resources: progressed ? "done" : "pending",
    agent: progressed ? selectionMark("agent", input, 6) : "pending",
    model: progressed ? selectionMark("model", input, 6) : "pending",
    execution: progressed ? "done" : "pending",
    verification: "pending",
    result: "failed",
  };
}

function selectionMark(stage: string, input: LifecycleInput, phase: number): StageMark {
  if (phase <= 3) {
    return "pending";
  }
  const evidence = stage === "agent" ? agentEvidence(input) : modelEvidence(input);
  return evidence ? "done" : "pending";
}

function agentEvidence(input: LifecycleInput): boolean {
  return (
    input.assignedAgents.length > 0 ||
    (input.decision !== null && AGENT_DECISIONS.has(input.decision))
  );
}

function modelEvidence(input: LifecycleInput): boolean {
  return (
    input.assignedModels.length > 0 ||
    (input.decision !== null && MODEL_DECISIONS.has(input.decision))
  );
}

function phaseIndex(input: LifecycleInput): number {
  switch (input.missionStatus) {
    case "CREATED":
    case "ANALYZING":
      return 1;
    case "PLANNING":
      return 2;
    case "READY":
      return 3;
    case "RUNNING":
    case "RECOVERING":
    case "PAUSED":
      return 6;
    case "WAITING":
      return input.waitingOn === "question" ? 1 : 6;
    case "VERIFYING":
      return 7;
    case "COMPLETED":
      return 8;
    default:
      return 1;
  }
}

function detailFor(id: string, input: LifecycleInput, mark: StageMark): string {
  if (id === "request") {
    return input.objective;
  }
  if (id === "agent" && mark === "done") {
    return input.assignedAgents.join(", ") || input.decision || "";
  }
  if (id === "model" && mark === "done") {
    return input.assignedModels.join(", ") || input.decision || "";
  }
  if (id === "verification" && (mark === "done" || mark === "active" || mark === "failed")) {
    return verificationDetail(input.verificationStatus);
  }
  if (id === "result" && mark === "failed") {
    return input.missionStatus === "CANCELLED" ? "CANCELLED" : input.errorMessage || "FAILED";
  }
  if (id === "result" && mark === "done") {
    return "COMPLETED";
  }
  if (id === "execution" && input.missionStatus === "RECOVERING") {
    return "RECOVERING";
  }
  if (id === "execution" && input.missionStatus === "PAUSED") {
    return "PAUSED";
  }
  return "";
}

function verificationDetail(status: string | null): string {
  if (status === "PASS") {
    return "PASSED";
  }
  if (status === "FAIL") {
    return "FAILED";
  }
  if (status === "INCONCLUSIVE") {
    return "INCONCLUSIVE";
  }
  return "no verification record";
}
