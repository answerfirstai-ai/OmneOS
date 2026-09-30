/** Recovery states reported by OMNE Core. */
export const RECOVERY_STATES = ["NORMAL", "DEGRADED", "SAFE_MODE", "RECOVERY"] as const;

export type RecoveryState = (typeof RECOVERY_STATES)[number];

export interface RecoveryStatus {
  state: RecoveryState;
  explanation: string;
  shell_reduced: boolean;
  diagnostics_available: boolean;
  data_erased: boolean;
  os_reinstalled: boolean;
}

const FULL_SURFACES = [
  "diagnostics",
  "recovery",
  "tasks",
  "agents",
  "models",
  "missions",
  "voice",
] as const;

const REDUCED_SURFACES = ["diagnostics", "recovery"] as const;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requireString(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`Recovery payload field "${key}" must be a non-empty string`);
  }
  return value;
}

function requireBoolean(record: Record<string, unknown>, key: string): boolean {
  const value = record[key];
  if (typeof value !== "boolean") {
    throw new Error(`Recovery payload field "${key}" must be a boolean`);
  }
  return value;
}

/** Validate a recovery document. Erase and reinstall stay false. */
export function readRecovery(payload: unknown): RecoveryStatus {
  if (!isRecord(payload)) {
    throw new Error("Recovery payload must be an object");
  }
  const state = requireString(payload, "state");
  if (!RECOVERY_STATES.includes(state as RecoveryState)) {
    throw new Error(`Recovery payload state must be one of ${RECOVERY_STATES.join(", ")}`);
  }
  const status: RecoveryStatus = {
    state: state as RecoveryState,
    explanation: requireString(payload, "explanation"),
    shell_reduced: requireBoolean(payload, "shell_reduced"),
    diagnostics_available: requireBoolean(payload, "diagnostics_available"),
    data_erased: requireBoolean(payload, "data_erased"),
    os_reinstalled: requireBoolean(payload, "os_reinstalled"),
  };
  if (!status.diagnostics_available) {
    throw new Error("diagnostics stay available");
  }
  if (status.data_erased || status.os_reinstalled) {
    throw new Error("recovery must not erase user data or reinstall");
  }
  return status;
}

/** Surfaces the shell may show. Safe mode and recovery keep diagnostics only. */
export function shellSurfaces(status: RecoveryStatus): readonly string[] {
  if (status.shell_reduced || status.state === "SAFE_MODE" || status.state === "RECOVERY") {
    return REDUCED_SURFACES;
  }
  return FULL_SURFACES;
}
