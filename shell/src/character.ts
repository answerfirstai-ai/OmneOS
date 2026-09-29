/** Visual states the shell can show. Assets are optional. */

export type CharacterState = "idle" | "listening" | "thinking" | "working" | "success" | "error";

export interface CharacterInput {
  coreOk: boolean;
  voiceListening: boolean;
  statuses: readonly string[];
}

const ASSETS: Record<CharacterState, string | null> = {
  idle: null,
  listening: null,
  thinking: null,
  working: null,
  success: null,
  error: null,
};

/** Choose a character state from core health, voice, and task statuses. */
export function characterState(input: CharacterInput): CharacterState {
  if (!input.coreOk) {
    return "error";
  }
  if (input.voiceListening) {
    return "listening";
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
