/** Tray text for the network record. A missing fact stays unknown, and secrets are not shown. */

export interface NetworkStatusView {
  text: string;
  state: "unknown" | "up" | "down" | "unreachable";
}

const SECRET_KEYS = new Set(["secret", "password", "psk", "passphrase"]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function rejectSecrets(value: unknown): void {
  if (Array.isArray(value)) {
    for (const item of value) {
      rejectSecrets(item);
    }
    return;
  }
  if (!isRecord(value)) {
    return;
  }
  for (const key of Object.keys(value)) {
    if (SECRET_KEYS.has(key)) {
      throw new Error("Network payload must not include a secret");
    }
    rejectSecrets(value[key]);
  }
}

function stringOrNull(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

/** Format GET /network for the desktop tray. */
export function readNetworkStatus(payload: unknown): NetworkStatusView {
  rejectSecrets(payload);
  if (!isRecord(payload)) {
    return { text: "network unknown", state: "unknown" };
  }
  const network = isRecord(payload["network"]) ? payload["network"] : payload;
  if (network["observed"] !== true) {
    return { text: "network unknown", state: "unknown" };
  }
  const interfaces = Array.isArray(network["interfaces"]) ? network["interfaces"] : [];
  if (interfaces.length === 0) {
    return { text: "no interfaces", state: "down" };
  }
  const chosen = chooseInterface(network, interfaces);
  if (!isRecord(chosen)) {
    return { text: "network unknown", state: "unknown" };
  }
  const name = stringOrNull(chosen["name"]) ?? "interface";
  const link = stringOrNull(chosen["state"]) ?? "unknown";
  const address = firstAddress(chosen["addresses"]);
  const signal = chosen["wifi_signal_dbm"];
  const parts = [name, link];
  if (address !== null) {
    parts.push(address);
  }
  if (typeof signal === "number" && Number.isFinite(signal)) {
    parts.push(`${Math.round(signal)} dBm`);
  }
  if (network["internet"] === "unreachable") {
    parts.push("no route");
  }
  if (network["internet"] === "reachable") {
    parts.push("internet");
  }
  let state: NetworkStatusView["state"] = "down";
  if (network["internet"] === "unreachable") {
    state = "unreachable";
  } else if (link === "up") {
    state = "up";
  }
  return { text: parts.join(" "), state };
}

function chooseInterface(
  network: Record<string, unknown>,
  interfaces: readonly unknown[],
): Record<string, unknown> | null {
  const route = isRecord(network["default_route"]) ? network["default_route"] : null;
  const routeName = route === null ? null : stringOrNull(route["interface"]);
  const records = interfaces.filter(isRecord);
  if (routeName !== null) {
    const match = records.find((item) => item["name"] === routeName);
    if (match !== undefined) {
      return match;
    }
  }
  const up = records.find((item) => item["state"] === "up" && item["kind"] !== "loopback");
  return up ?? records[0] ?? null;
}

function firstAddress(value: unknown): string | null {
  if (!Array.isArray(value)) {
    return null;
  }
  for (const item of value) {
    if (!isRecord(item)) {
      continue;
    }
    if (item["scope"] === "link" || item["scope"] === "host") {
      continue;
    }
    const address = stringOrNull(item["address"]);
    if (address !== null) {
      return address;
    }
  }
  return null;
}
