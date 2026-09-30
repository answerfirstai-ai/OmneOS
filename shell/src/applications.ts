/** Installed applications for the launcher. The list does not run a command. */

export interface ApplicationView {
  id: string;
  name: string;
  categories: string[];
  state: string;
}

const COMMAND_KEYS = new Set(["argv", "command", "shell", "exec", "cmd"]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function rejectCommand(value: unknown): void {
  if (Array.isArray(value)) {
    for (const item of value) {
      rejectCommand(item);
    }
    return;
  }
  if (!isRecord(value)) {
    return;
  }
  for (const key of Object.keys(value)) {
    if (COMMAND_KEYS.has(key)) {
      throw new Error("Application payload must not include a shell command");
    }
    rejectCommand(value[key]);
  }
}

/** Read GET /applications. Hidden entries stay out of the launcher. */
export function readApplications(payload: unknown): ApplicationView[] {
  rejectCommand(payload);
  if (!isRecord(payload)) {
    return [];
  }
  const body = isRecord(payload["applications"]) ? payload["applications"] : payload;
  if (body["commanded"] === true) {
    throw new Error("Application payload must not command a shell");
  }
  const rows = Array.isArray(body["applications"]) ? body["applications"] : [];
  const views: ApplicationView[] = [];
  for (const row of rows) {
    if (!isRecord(row) || row["commanded"] === true) {
      throw new Error("Application payload must not command a shell");
    }
    const id = row["id"];
    const name = row["name"];
    const state = row["state"];
    if (typeof id !== "string" || typeof name !== "string" || typeof state !== "string") {
      continue;
    }
    if (state === "hidden") {
      continue;
    }
    const categories = Array.isArray(row["categories"])
      ? row["categories"].filter((item): item is string => typeof item === "string")
      : [];
    views.push({ id, name, categories, state });
  }
  return views;
}

/** The objective the launcher submits for one application. */
export function applicationObjective(name: string): string {
  return `Open ${name}`;
}
