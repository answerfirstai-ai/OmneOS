/** What the desktop can do when no model is connected. */

export const DESKTOP_SURFACES = ["browse", "files", "settings", "wifi"] as const;

export interface IntelligenceView {
  enabled: boolean;
  reason: string;
  desktop: boolean;
}

export function readIntelligence(payload: unknown): IntelligenceView {
  if (!isRecord(payload) || payload["desktop"] !== true) {
    return {
      enabled: false,
      desktop: true,
      reason: "Intelligence is off until an API key or a local model is connected.",
    };
  }
  const reason = payload["reason"];
  return {
    enabled: payload["enabled"] === true,
    desktop: true,
    reason:
      typeof reason === "string" && reason.trim() !== ""
        ? reason
        : "Intelligence is off until an API key or a local model is connected.",
  };
}

export function intelligenceBanner(enabled: boolean): string {
  if (enabled) {
    return "Intelligence is connected.";
  }
  return "Intelligence is off until an API key or a local model is connected.";
}

/** Model work waits. Browse, files, settings, and Wi-Fi do not. */
export function maySendObjective(enabled: boolean): boolean {
  return enabled;
}

export function sessionLine(wifi: string): string {
  const status = wifi.trim() === "" ? "unknown" : wifi.trim();
  return `Desktop is available. Files are in Project. Wi-Fi: ${status}.`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
