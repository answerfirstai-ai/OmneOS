/** Lightweight resource lines. Unknown measurements stay unknown. */

export interface HudLine {
  label: string;
  value: string;
}

/** Read a `/compute` document. A missing sample does not become a number. */
export function readCompute(payload: unknown): HudLine[] {
  const root = isRecord(payload) ? payload : {};
  const snapshot = isRecord(root["compute"]) ? root["compute"] : root;
  const cpu = record(snapshot, "cpu");
  const memory = record(snapshot, "memory");
  const gpu = record(snapshot, "gpu");
  const disk = record(snapshot, "disk");
  const network = record(snapshot, "network");
  return [
    { label: "CPU", value: percent(cpu["usage_percent"]) },
    { label: "RAM", value: pair(memory["used_mb"], memory["total_mb"]) },
    { label: "GPU", value: gpuValue(gpu) },
    { label: "VRAM", value: pair(gpu["vram_used_mb"], gpu["vram_total_mb"]) },
    { label: "Disk", value: pair(disk["used_mb"], disk["total_mb"]) },
    { label: "Network", value: networkValue(network) },
  ];
}

export function hudText(lines: readonly HudLine[]): string {
  return lines.map((line) => `${line.label} ${line.value}`).join("\n");
}

/** Mention pressure only when a real percentage is high. */
export function resourcePressure(lines: readonly HudLine[]): string | null {
  const cpu = lines.find((line) => line.label === "CPU");
  const gpu = lines.find((line) => line.label === "GPU");
  if (cpu !== undefined && percentValue(cpu.value) >= 90) {
    return `CPU pressure ${cpu.value}`;
  }
  if (gpu !== undefined && percentValue(gpu.value) >= 90) {
    return `GPU pressure ${gpu.value}`;
  }
  return null;
}

function gpuValue(gpu: Record<string, unknown>): string {
  if (gpu["available"] === false) {
    return "unavailable";
  }
  if (gpu["available"] === true) {
    return percent(gpu["usage_percent"]);
  }
  return "unknown";
}

function networkValue(network: Record<string, unknown>): string {
  if (network["available"] === false) {
    return "unavailable";
  }
  if (network["available"] !== true) {
    return "unknown";
  }
  const interfaces = Array.isArray(network["interfaces"]) ? network["interfaces"] : [];
  return interfaces.length === 1 ? "1 interface" : `${interfaces.length} interfaces`;
}

function percent(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? `${Math.round(value)}%` : "unknown";
}

function pair(used: unknown, total: unknown): string {
  if (typeof used !== "number" || typeof total !== "number") {
    return "unknown";
  }
  if (!Number.isFinite(used) || !Number.isFinite(total)) {
    return "unknown";
  }
  return `${formatMb(used)} / ${formatMb(total)}`;
}

function formatMb(value: number): string {
  if (value >= 1024) {
    return `${(value / 1024).toFixed(1)} GB`;
  }
  return `${Math.round(value)} MB`;
}

function percentValue(value: string): number {
  if (!value.endsWith("%")) {
    return -1;
  }
  const parsed = Number(value.slice(0, -1));
  return Number.isFinite(parsed) ? parsed : -1;
}

function record(source: Record<string, unknown>, key: string): Record<string, unknown> {
  const value = source[key];
  return isRecord(value) ? value : {};
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
