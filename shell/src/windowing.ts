/** Window record published by OMNE Core. The shell does not place these windows yet. */

export interface ManagedWindowState {
  id: string;
  title: string;
  app_id: string;
  workspace_id: string;
  monitor_id: string | null;
  x: number | null;
  y: number | null;
  width: number | null;
  height: number | null;
  fullscreen: boolean;
  minimized: boolean;
  maximized: boolean;
  focused: boolean;
  mapped: boolean;
  owner: string | null;
}

export interface WorkspaceState {
  id: string;
  name: string;
  active: boolean;
  window_ids: string[];
}

export interface MonitorState {
  id: string;
  name: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface WindowingState {
  provider: "mock" | "labwc";
  known: boolean;
  compositor: string;
  compositor_commanded: false;
  focused_window_id: string | null;
  active_workspace_id: string | null;
  windows: ManagedWindowState[];
  workspaces: WorkspaceState[];
  monitors: MonitorState[];
  fullscreen_window_id: string | null;
  detail: string | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requireString(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`Windowing payload field "${key}" must be a non-empty string`);
  }
  return value;
}

function requireStringOrNull(record: Record<string, unknown>, key: string): string | null {
  const value = record[key];
  if (value === null) {
    return null;
  }
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`Windowing payload field "${key}" must be a string or null`);
  }
  return value;
}

function requireBoolean(record: Record<string, unknown>, key: string): boolean {
  const value = record[key];
  if (typeof value !== "boolean") {
    throw new Error(`Windowing payload field "${key}" must be a boolean`);
  }
  return value;
}

function requireInteger(record: Record<string, unknown>, key: string): number {
  const value = record[key];
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new Error(`Windowing payload field "${key}" must be an integer`);
  }
  return value;
}

function requireIntegerOrNull(record: Record<string, unknown>, key: string): number | null {
  const value = record[key];
  if (value === null) {
    return null;
  }
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new Error(`Windowing payload field "${key}" must be an integer or null`);
  }
  return value;
}

function requireStringList(record: Record<string, unknown>, key: string): string[] {
  const value = record[key];
  if (
    !Array.isArray(value) ||
    value.some((item) => typeof item !== "string" || item.length === 0)
  ) {
    throw new Error(`Windowing payload field "${key}" must be a list of strings`);
  }
  return value;
}

function parseWindow(value: unknown): ManagedWindowState {
  if (!isRecord(value)) {
    throw new Error("Windowing window must be an object");
  }
  return {
    id: requireString(value, "id"),
    title: requireString(value, "title"),
    app_id: requireString(value, "app_id"),
    workspace_id: requireString(value, "workspace_id"),
    monitor_id: requireStringOrNull(value, "monitor_id"),
    x: requireIntegerOrNull(value, "x"),
    y: requireIntegerOrNull(value, "y"),
    width: requireIntegerOrNull(value, "width"),
    height: requireIntegerOrNull(value, "height"),
    fullscreen: requireBoolean(value, "fullscreen"),
    minimized: requireBoolean(value, "minimized"),
    maximized: requireBoolean(value, "maximized"),
    focused: requireBoolean(value, "focused"),
    mapped: requireBoolean(value, "mapped"),
    owner: requireStringOrNull(value, "owner"),
  };
}

function parseWorkspace(value: unknown): WorkspaceState {
  if (!isRecord(value)) {
    throw new Error("Windowing workspace must be an object");
  }
  return {
    id: requireString(value, "id"),
    name: requireString(value, "name"),
    active: requireBoolean(value, "active"),
    window_ids: requireStringList(value, "window_ids"),
  };
}

function parseMonitor(value: unknown): MonitorState {
  if (!isRecord(value)) {
    throw new Error("Windowing monitor must be an object");
  }
  const width = requireInteger(value, "width");
  const height = requireInteger(value, "height");
  if (width <= 0 || height <= 0) {
    throw new Error("Windowing monitor size must be positive");
  }
  return {
    id: requireString(value, "id"),
    name: requireString(value, "name"),
    x: requireInteger(value, "x"),
    y: requireInteger(value, "y"),
    width,
    height,
  };
}

function parseProvider(record: Record<string, unknown>): "mock" | "labwc" {
  const provider = requireString(record, "provider");
  if (provider !== "mock" && provider !== "labwc") {
    throw new Error('Windowing payload provider must be "mock" or "labwc"');
  }
  return provider;
}

/** Validate the window record returned inside GET /windowing. */
export function parseWindowing(payload: unknown): WindowingState {
  if (!isRecord(payload)) {
    throw new Error("Windowing payload must be an object");
  }
  if (payload.compositor_commanded !== false) {
    throw new Error("Windowing payload compositor_commanded must be false");
  }
  const windows = payload.windows;
  const workspaces = payload.workspaces;
  const monitors = payload.monitors;
  if (!Array.isArray(windows) || !Array.isArray(workspaces) || !Array.isArray(monitors)) {
    throw new Error("Windowing payload windows, workspaces, and monitors must be lists");
  }
  return {
    provider: parseProvider(payload),
    known: requireBoolean(payload, "known"),
    compositor: requireString(payload, "compositor"),
    compositor_commanded: false,
    focused_window_id: requireStringOrNull(payload, "focused_window_id"),
    active_workspace_id: requireStringOrNull(payload, "active_workspace_id"),
    windows: windows.map(parseWindow),
    workspaces: workspaces.map(parseWorkspace),
    monitors: monitors.map(parseMonitor),
    fullscreen_window_id: requireStringOrNull(payload, "fullscreen_window_id"),
    detail: requireStringOrNull(payload, "detail"),
  };
}

/** Validate the GET /windowing response envelope. */
export function parseWindowingResponse(payload: unknown): WindowingState {
  if (!isRecord(payload)) {
    throw new Error("Windowing response must be an object");
  }
  return parseWindowing(payload.windowing);
}
