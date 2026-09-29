/** Public health document returned by JARVIS Core. */
export interface CoreHealth {
  status: "ok";
  service: string;
  version: string;
  environment: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requireString(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`Health payload field "${key}" must be a non-empty string`);
  }
  return value;
}

/** Validate an unknown JSON value as a core health document. */
export function parseHealth(payload: unknown): CoreHealth {
  if (!isRecord(payload)) {
    throw new Error("Health payload must be an object");
  }
  const status = requireString(payload, "status");
  if (status !== "ok") {
    throw new Error('Health payload status must be "ok"');
  }
  return {
    status: "ok",
    service: requireString(payload, "service"),
    version: requireString(payload, "version"),
    environment: requireString(payload, "environment"),
  };
}

/** Build the health endpoint URL for a core base URL. */
export function coreHealthUrl(coreUrl: string): string {
  let url: URL;
  try {
    url = new URL(coreUrl);
  } catch {
    throw new Error(`Invalid core URL: ${coreUrl}`);
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error(`Unsupported core URL protocol: ${url.protocol}`);
  }
  url.pathname = "/health";
  url.search = "";
  url.hash = "";
  return url.toString();
}
