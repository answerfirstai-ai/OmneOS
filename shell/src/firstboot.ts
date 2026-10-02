/** First boot is setup. A finished setup is a password gate and nothing else. */

import type { JsonFetcher } from "./api.js";

export const SETUP_STEPS = ["welcome", "name", "look", "password"] as const;
export type SetupStep = (typeof SETUP_STEPS)[number];

export interface SetupView {
  complete: boolean;
  gate: "setup" | "password";
  name: string;
}

export interface SetupDraft {
  name: string;
  color: string;
  type: string;
  wallpaper: string;
  password: string;
  confirm: string;
}

export interface ThemeColors {
  ink: string;
  muted: string;
  accent: string;
  glass: string;
  desktop: string;
}

export interface ThemeDocument {
  colors: ThemeColors;
  type: string;
  wallpaper: string;
}

export interface DependencyStage {
  id: string;
  label: string;
  state: "staged" | "waiting";
}

export const COLOR_PRESETS = [
  {
    id: "dusk",
    label: "Dusk",
    ink: "#f3efe6",
    muted: "#c5c0b6",
    accent: "#e4c27a",
    glass: "#12171d",
    desktop: "#152433",
  },
  {
    id: "tide",
    label: "Tide",
    ink: "#e7f1f6",
    muted: "#b7c7d1",
    accent: "#7eb6d6",
    glass: "#101820",
    desktop: "#10202c",
  },
  {
    id: "leaf",
    label: "Leaf",
    ink: "#eef3ea",
    muted: "#c5d0c0",
    accent: "#b7d7a8",
    glass: "#141816",
    desktop: "#1a221c",
  },
] as const;

export const TYPE_PRESETS = [
  {
    id: "interface",
    label: "Interface",
    stack: '"Segoe UI", ui-sans-serif, system-ui, sans-serif',
  },
  {
    id: "editorial",
    label: "Editorial",
    stack: '"Iowan Old Style", Palatino, "Palatino Linotype", serif',
  },
  {
    id: "mono",
    label: "Mono",
    stack: 'ui-monospace, "Cascadia Mono", "Segoe UI Mono", monospace',
  },
] as const;

export const WALLPAPER_PRESETS = [
  {
    id: "dusk",
    label: "Dusk",
    value:
      "radial-gradient(ellipse 70% 45% at 78% 108%, rgba(214, 146, 72, 0.55), transparent 58%), linear-gradient(180deg, #24384c 0%, #152433 46%, #1a1612 100%)",
  },
  {
    id: "night",
    label: "Night",
    value: "linear-gradient(180deg, #0c1218 0%, #1a2430 55%, #101418 100%)",
  },
  {
    id: "paper",
    label: "Paper",
    value: "linear-gradient(180deg, #3a3228 0%, #1c1814 100%)",
  },
] as const;

export const DEPENDENCY_STAGES = [
  { id: "shell", label: "OMNE shell" },
  { id: "core", label: "OMNE core" },
  { id: "session", label: "Desktop session" },
  { id: "catalog", label: "Model catalog" },
] as const;

const STEP_INDEX: Record<SetupStep | "finish", number> = {
  welcome: 0,
  name: 1,
  look: 2,
  password: 3,
  finish: 3,
};

const COLOR = /^#[0-9a-fA-F]{6}$/;
const TYPE = /^[A-Za-z0-9 ,"'-]{1,160}$/;

export function readSetup(payload: unknown): SetupView | null {
  if (!isRecord(payload) || typeof payload["complete"] !== "boolean") {
    return null;
  }
  const name = payload["name"];
  return {
    complete: payload["complete"],
    gate: payload["gate"] === "password" ? "password" : "setup",
    name: typeof name === "string" ? name : "",
  };
}

/** A finished setup never returns to the wizard. */
export function bootSurface(view: SetupView | null): "setup" | "password" | "hold" {
  if (view === null) {
    return "hold";
  }
  if (view.complete) {
    return "password";
  }
  return "setup";
}

/** A wrong password stays on the gate. Only a match opens the desktop. */
export function surfaceAfterUnlock(unlocked: boolean): "desktop" | "password" {
  return unlocked ? "desktop" : "password";
}

export function nextSetupStep(
  step: SetupStep,
  draft: SetupDraft,
): { step: SetupStep | "finish"; error: string | null } {
  if (step === "welcome") {
    return { step: "name", error: null };
  }
  if (step === "name") {
    if (!displayName(draft.name)) {
      return { step, error: "Enter a name" };
    }
    return { step: "look", error: null };
  }
  if (step === "look") {
    return { step: "password", error: null };
  }
  if (draft.password.length < 8) {
    return { step, error: "Use at least 8 characters" };
  }
  if (draft.password !== draft.confirm) {
    return { step, error: "Those passwords do not match" };
  }
  return { step: "finish", error: null };
}

export function previousSetupStep(step: SetupStep): SetupStep {
  if (step === "name") {
    return "welcome";
  }
  if (step === "look") {
    return "name";
  }
  if (step === "password") {
    return "look";
  }
  return "welcome";
}

/** Advance a staged list. Nothing here downloads model weights. */
export function stageDependencies(step: SetupStep | "finish"): DependencyStage[] {
  const ready = STEP_INDEX[step];
  return DEPENDENCY_STAGES.map((item, index) => ({
    id: item.id,
    label: item.label,
    state: index <= ready ? "staged" : "waiting",
  }));
}

export function themeFromDraft(
  draft: Pick<SetupDraft, "color" | "type" | "wallpaper">,
): ThemeDocument {
  const color = COLOR_PRESETS.find((item) => item.id === draft.color) ?? COLOR_PRESETS[0];
  const type = TYPE_PRESETS.find((item) => item.id === draft.type) ?? TYPE_PRESETS[0];
  const wallpaper =
    WALLPAPER_PRESETS.find((item) => item.id === draft.wallpaper) ?? WALLPAPER_PRESETS[0];
  return {
    colors: {
      ink: color.ink,
      muted: color.muted,
      accent: color.accent,
      glass: color.glass,
      desktop: color.desktop,
    },
    type: type.stack,
    wallpaper: wallpaper.value,
  };
}

export function readTheme(payload: unknown): ThemeDocument | null {
  if (!isRecord(payload) || !isRecord(payload["colors"])) {
    return null;
  }
  const colors = payload["colors"];
  const theme: ThemeDocument = {
    colors: {
      ink: text(colors["ink"]),
      muted: text(colors["muted"]),
      accent: text(colors["accent"]),
      glass: text(colors["glass"]),
      desktop: text(colors["desktop"]),
    },
    type: text(payload["type"]),
    wallpaper: text(payload["wallpaper"]),
  };
  if (themeVariables(theme) === null) {
    return null;
  }
  return theme;
}

/** CSS variables for a theme document. A path or url() is not applied. */
export function themeVariables(theme: ThemeDocument): Record<string, string> | null {
  const colors = [
    theme.colors.ink,
    theme.colors.muted,
    theme.colors.accent,
    theme.colors.glass,
    theme.colors.desktop,
  ];
  if (colors.some((color) => !COLOR.test(color))) {
    return null;
  }
  if (
    !TYPE.test(theme.type) ||
    theme.type.includes("/") ||
    theme.type.toLowerCase().includes("url")
  ) {
    return null;
  }
  if (!safeWallpaper(theme.wallpaper)) {
    return null;
  }
  return {
    "--ink": theme.colors.ink,
    "--muted": theme.colors.muted,
    "--accent": theme.colors.accent,
    "--glass": theme.colors.glass,
    "--desktop": theme.colors.desktop,
    "--type": theme.type,
    "--wallpaper": theme.wallpaper,
  };
}

export async function postJson(
  url: string,
  body: unknown,
  fetchImpl: JsonFetcher = fetch,
): Promise<{ status: number; body: unknown }> {
  let response: Response;
  try {
    response = await fetchImpl(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "network request failed";
    throw new Error(`Unable to reach OMNE Core: ${message}`);
  }
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  return { status: response.status, body: payload };
}

function safeWallpaper(value: string): boolean {
  if (value.length === 0 || value.length > 1200 || value.includes("/") || value.includes("\\")) {
    return false;
  }
  if (value.toLowerCase().includes("url")) {
    return false;
  }
  const parts = splitGradients(value);
  if (parts.length === 0 || parts.length > 12) {
    return false;
  }
  return parts.every((part) => {
    const item = part.trim();
    return (
      (item.startsWith("linear-gradient(") || item.startsWith("radial-gradient(")) &&
      item.endsWith(")") &&
      item.length <= 320
    );
  });
}

function splitGradients(value: string): string[] {
  const parts: string[] = [];
  let depth = 0;
  let start = 0;
  for (let index = 0; index < value.length; index += 1) {
    const character = value[index];
    if (character === "(") {
      depth += 1;
    } else if (character === ")") {
      depth -= 1;
    } else if (character === "," && depth === 0) {
      parts.push(value.slice(start, index));
      start = index + 1;
    }
  }
  parts.push(value.slice(start));
  return parts;
}

function displayName(value: string): boolean {
  const name = value.trim();
  if (name.length < 1 || name.length > 40 || name.includes("/") || name.includes("\\")) {
    return false;
  }
  for (const character of name) {
    const code = character.codePointAt(0) ?? 0;
    if (code < 32) {
      return false;
    }
  }
  return true;
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
