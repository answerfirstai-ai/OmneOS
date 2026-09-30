/** Visual states the shell can show. Assets are optional. */

export type CharacterState =
  | "idle"
  | "listening"
  | "thinking"
  | "working"
  | "success"
  | "error"
  | "analyzing"
  | "planning"
  | "routing"
  | "verifying"
  | "waiting";

export type CharacterMode =
  "IDLE" | "THINKING" | "RESEARCHING" | "EXECUTING" | "WAITING" | "WARNING" | "ERROR" | "OFFLINE";

export interface CharacterInput {
  coreOk: boolean;
  voiceListening: boolean;
  statuses: readonly string[];
  missionStatuses?: readonly string[];
  activeAgents?: readonly string[];
  recovery?: string | null;
  waitingForUser?: boolean;
}

const LIVE = new Set([
  "ANALYZING",
  "PLANNING",
  "RUNNING",
  "RECOVERING",
  "VERIFYING",
  "WAITING",
  "FAILED",
]);

const ASSETS: Record<CharacterState, string | null> = {
  idle: null,
  listening: null,
  thinking: null,
  working: null,
  success: null,
  error: null,
  analyzing: null,
  planning: null,
  routing: null,
  verifying: null,
  waiting: null,
};

/** The visible character. Completed work returns to idle. An unread core is offline. */
export function characterMode(input: CharacterInput): CharacterMode {
  if (!input.coreOk) {
    return "OFFLINE";
  }
  const missions = (input.missionStatuses ?? []).filter((status) => LIVE.has(status));
  const tasks = input.statuses.filter((status) => LIVE.has(status));
  if (missions.includes("FAILED") || tasks.includes("FAILED")) {
    return "ERROR";
  }
  if (missions.includes("WAITING") || tasks.includes("WAITING") || input.waitingForUser === true) {
    return "WAITING";
  }
  const executing =
    missions.some(
      (status) => status === "RUNNING" || status === "RECOVERING" || status === "VERIFYING",
    ) ||
    tasks.some(
      (status) => status === "RUNNING" || status === "RECOVERING" || status === "VERIFYING",
    );
  const thinking =
    input.voiceListening ||
    missions.some((status) => status === "ANALYZING" || status === "PLANNING") ||
    tasks.some((status) => status === "PLANNING");
  if ((executing || thinking) && (input.activeAgents ?? []).includes("research")) {
    return "RESEARCHING";
  }
  if (executing) {
    return "EXECUTING";
  }
  if (thinking) {
    return "THINKING";
  }
  if (
    input.recovery === "DEGRADED" ||
    input.recovery === "SAFE_MODE" ||
    input.recovery === "RECOVERY"
  ) {
    return "WARNING";
  }
  return "IDLE";
}

/** Choose a character state from core health, voice, and task statuses. */
export function characterState(input: CharacterInput): CharacterState {
  if (!input.coreOk) {
    return "error";
  }
  if (input.voiceListening) {
    return "listening";
  }
  const missions = input.missionStatuses;
  if (missions !== undefined && missions.length > 0) {
    if (missions.includes("FAILED")) {
      return "error";
    }
    if (missions.includes("ANALYZING")) {
      return "analyzing";
    }
    if (missions.includes("PLANNING")) {
      return "planning";
    }
    if (missions.includes("VERIFYING")) {
      return "verifying";
    }
    if (missions.includes("WAITING")) {
      return "waiting";
    }
    if (missions.some((status) => status === "RUNNING" || status === "RECOVERING")) {
      return "working";
    }
    if (missions.includes("COMPLETED")) {
      return "success";
    }
  }
  if (input.statuses.includes("FAILED")) {
    return "error";
  }
  if (input.statuses.some((status) => status === "PLANNING" || status === "WAITING")) {
    return "thinking";
  }
  if (
    input.statuses.some(
      (status) => status === "RUNNING" || status === "RECOVERING" || status === "VERIFYING",
    )
  ) {
    return "working";
  }
  if (input.statuses.includes("COMPLETED")) {
    return "success";
  }
  return "idle";
}

/** Return a character asset path, or null when that asset is not shipped. */
export function characterAsset(state: CharacterState): string | null {
  return ASSETS[state];
}
