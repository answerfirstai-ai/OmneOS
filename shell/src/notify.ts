/** Event-driven notices. Unknown events keep their type instead of invented copy. */

import type { EventDocument } from "./desktop.js";

export interface Notice {
  id: string;
  text: string;
  missionId: string | null;
  taskId: string | null;
}

export function noticesFromEvents(events: readonly EventDocument[]): Notice[] {
  return events.map((event) => ({
    id: event.id,
    text: noticeText(event),
    missionId: event.mission_id ?? null,
    taskId: event.task_id ?? null,
  }));
}

function noticeText(event: EventDocument): string {
  switch (event.type) {
    case "mission.completed":
      return "Mission completed.";
    case "mission.failed":
      return "Mission failed.";
    case "mission.waiting":
      return "OMNE needs clarification.";
    case "mission.created":
      return "OMNE accepted a mission.";
    case "mission.started":
      return "A mission started.";
    case "mission.verifying":
      return "OMNE is verifying the result.";
    case "mission.cancelled":
      return "Mission cancelled.";
    case "mission.paused":
      return "Mission paused.";
    case "mission.resumed":
      return "Mission resumed.";
    case "mission.analyzing":
      return "OMNE is understanding the request.";
    case "mission.planned":
      return "OMNE finished a plan.";
    case "permission.requested":
      return "OMNE needs your permission.";
    case "permission.denied":
      return "Permission denied.";
    case "permission.granted":
      return "Permission granted.";
    case "verification.recorded":
      return verificationNotice(event.payload?.["status"]);
    case "decision.selected":
      return decisionNotice(event.payload?.["decision"]);
    case "worker.started":
      return "A worker started.";
    case "worker.completed":
      return "A worker finished.";
    case "worker.failed":
      return "A worker failed.";
    case "task.started":
      return "A task started.";
    case "task.completed":
      return "A task completed.";
    case "task.failed":
      return "A task failed.";
    case "task.recovered":
      return "OMNE recovered a task.";
    case "task.cancelled":
      return "A task was cancelled.";
    default:
      return event.type;
  }
}

function verificationNotice(status: unknown): string {
  if (status === "FAIL") {
    return "Verification failed.";
  }
  if (status === "PASS") {
    return "Verification passed.";
  }
  if (status === "INCONCLUSIVE") {
    return "Verification was inconclusive.";
  }
  return "Verification recorded.";
}

function decisionNotice(decision: unknown): string {
  if (decision === "LOCAL_MODEL") {
    return "OMNE selected a local model.";
  }
  if (decision === "CLOUD_MODEL") {
    return "OMNE selected a cloud model.";
  }
  if (decision === "HYBRID") {
    return "OMNE selected a hybrid model path.";
  }
  if (decision === "DIRECT_TOOL") {
    return "OMNE selected a direct tool.";
  }
  if (decision === "DENY") {
    return "OMNE denied the request.";
  }
  if (decision === "ASK_USER") {
    return "OMNE needs clarification.";
  }
  return "OMNE selected an execution path.";
}
