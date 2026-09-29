/** Shell-level visual state derived from core, voice, and mission status. */

import { characterState, type CharacterInput } from "./character.js";

export type EnvironmentState =
  | "IDLE"
  | "LISTENING"
  | "UNDERSTANDING"
  | "PLANNING"
  | "ROUTING"
  | "WORKING"
  | "WAITING"
  | "VERIFYING"
  | "SUCCESS"
  | "ERROR";

export interface EnvironmentInput extends CharacterInput {
  latestEvent?: string;
}

const FROM_CHARACTER: Record<ReturnType<typeof characterState>, EnvironmentState> = {
  idle: "IDLE",
  listening: "LISTENING",
  analyzing: "UNDERSTANDING",
  planning: "PLANNING",
  thinking: "PLANNING",
  routing: "ROUTING",
  working: "WORKING",
  verifying: "VERIFYING",
  waiting: "WAITING",
  success: "SUCCESS",
  error: "ERROR",
};

/** Map backend status onto one environment state. Routing needs a real decision event. */
export function environmentState(input: EnvironmentInput): EnvironmentState {
  const missions = input.missionStatuses;
  if (
    input.latestEvent === "decision.selected" &&
    missions !== undefined &&
    missions.includes("PLANNING")
  ) {
    return "ROUTING";
  }
  return FROM_CHARACTER[characterState(input)];
}
