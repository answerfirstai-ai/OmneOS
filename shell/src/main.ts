import { coreHealthUrl, parseHealth, type CoreHealth } from "./health.js";

const DEFAULT_CORE_URL = "http://127.0.0.1:8787";

export type HealthFetcher = (input: string) => Promise<Response>;

/** Read the core base URL from a page query string. */
export function readCoreUrl(search: string): string {
  const configured = new URLSearchParams(search).get("core");
  if (configured === null || configured.trim() === "") {
    return DEFAULT_CORE_URL;
  }
  return configured.trim();
}

/** Request and validate the core health document. */
export async function fetchHealth(
  coreUrl: string,
  fetchImpl: HealthFetcher = fetch,
): Promise<CoreHealth> {
  const url = coreHealthUrl(coreUrl);
  let response: Response;
  try {
    response = await fetchImpl(url);
  } catch (error) {
    const message = error instanceof Error ? error.message : "network request failed";
    throw new Error(`Unable to reach JARVIS Core: ${message}`);
  }
  if (!response.ok) {
    throw new Error(`JARVIS Core health request failed with status ${response.status}`);
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new Error("JARVIS Core health response was not JSON");
  }
  return parseHealth(payload);
}

function requireElement(id: string): HTMLElement {
  const element = document.getElementById(id);
  if (!(element instanceof HTMLElement)) {
    throw new Error(`Missing shell element #${id}`);
  }
  return element;
}

async function refresh(status: HTMLElement, detail: HTMLElement): Promise<void> {
  const coreUrl = readCoreUrl(window.location.search);
  status.dataset["state"] = "checking";
  status.textContent = "checking";
  detail.textContent = coreHealthUrl(coreUrl);
  try {
    const health = await fetchHealth(coreUrl);
    status.dataset["state"] = "ok";
    status.textContent = health.status;
    detail.textContent = `${health.service} ${health.version} · ${health.environment}`;
  } catch (error) {
    status.dataset["state"] = "unavailable";
    status.textContent = "unavailable";
    detail.textContent = error instanceof Error ? error.message : "Unknown error";
  }
}

function bootstrap(): void {
  try {
    const status = requireElement("status");
    const detail = requireElement("detail");
    const button = document.getElementById("refresh");
    if (button instanceof HTMLButtonElement) {
      button.addEventListener("click", () => {
        void refresh(status, detail);
      });
    }
    void refresh(status, detail);
  } catch (error) {
    console.error(error);
  }
}

if (typeof document !== "undefined") {
  bootstrap();
}
