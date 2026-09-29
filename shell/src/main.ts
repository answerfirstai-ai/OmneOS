import { coreApiUrl, fetchJson } from "./api.js";
import { characterAsset, characterState } from "./character.js";
import {
  agentLine,
  modelLine,
  notificationLine,
  parentTasks,
  taskLine,
  type AgentDocument,
  type EventDocument,
  type ModelDocument,
  type TaskDocument,
} from "./desktop.js";
import { coreHealthUrl, parseHealth, type CoreHealth } from "./health.js";
import { voiceControlEnabled, voiceSummary, type VoiceStatus } from "./voice.js";

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

function listElement(id: string): HTMLElement | null {
  const element = document.getElementById(id);
  return element instanceof HTMLElement ? element : null;
}

function renderList(id: string, lines: string[], empty: string): void {
  const element = listElement(id);
  if (element === null) {
    return;
  }
  element.replaceChildren();
  const values = lines.length > 0 ? lines : [empty];
  for (const line of values) {
    const item = document.createElement("li");
    item.textContent = line;
    element.append(item);
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asTasks(payload: unknown): TaskDocument[] {
  if (!isRecord(payload) || !Array.isArray(payload["tasks"])) {
    return [];
  }
  return payload["tasks"].filter(isTask);
}

function isTask(value: unknown): value is TaskDocument {
  if (!isRecord(value)) {
    return false;
  }
  return (
    typeof value["id"] === "string" &&
    typeof value["objective"] === "string" &&
    typeof value["status"] === "string"
  );
}

function asAgents(payload: unknown): AgentDocument[] {
  if (!isRecord(payload) || !Array.isArray(payload["agents"])) {
    return [];
  }
  return payload["agents"].filter(isAgent);
}

function isAgent(value: unknown): value is AgentDocument {
  if (!isRecord(value)) {
    return false;
  }
  return (
    typeof value["id"] === "string" &&
    typeof value["state"] === "string" &&
    typeof value["enabled"] === "boolean"
  );
}

function asModels(payload: unknown): ModelDocument[] {
  if (!isRecord(payload) || !Array.isArray(payload["models"])) {
    return [];
  }
  return payload["models"].filter(isModel);
}

function isModel(value: unknown): value is ModelDocument {
  if (!isRecord(value)) {
    return false;
  }
  return (
    typeof value["id"] === "string" &&
    typeof value["provider"] === "string" &&
    typeof value["local"] === "boolean"
  );
}

function asEvents(payload: unknown): EventDocument[] {
  if (!isRecord(payload) || !Array.isArray(payload["events"])) {
    return [];
  }
  return payload["events"].filter(isEvent).slice(-8);
}

function isEvent(value: unknown): value is EventDocument {
  if (!isRecord(value)) {
    return false;
  }
  return typeof value["id"] === "string" && typeof value["type"] === "string";
}

function asVoice(payload: unknown): VoiceStatus {
  const voice = isRecord(payload) ? payload["voice"] : null;
  if (!isRecord(voice)) {
    return {
      provider: "unavailable",
      hardware: "unavailable",
      permission: "unknown",
      listening: false,
      reason: "voice status was not returned",
    };
  }
  return {
    provider: typeof voice["provider"] === "string" ? voice["provider"] : "unavailable",
    hardware: typeof voice["hardware"] === "string" ? voice["hardware"] : "unavailable",
    permission: typeof voice["permission"] === "string" ? voice["permission"] : "unknown",
    listening: voice["listening"] === true,
    reason: typeof voice["reason"] === "string" ? voice["reason"] : "voice is unavailable",
  };
}

function showCharacter(statuses: string[], coreOk: boolean, listening: boolean): void {
  const element = listElement("character");
  if (element === null) {
    return;
  }
  const state = characterState({ coreOk, voiceListening: listening, statuses });
  element.dataset["state"] = state;
  element.textContent = characterAsset(state) === null ? state : state;
}

function showVoice(status: VoiceStatus): void {
  const element = listElement("voice-status");
  const button = document.getElementById("voice-listen");
  if (element !== null) {
    element.textContent = voiceSummary(status);
  }
  if (button instanceof HTMLButtonElement) {
    button.disabled = !voiceControlEnabled(status);
  }
}

async function refreshDesktop(coreUrl: string, coreOk: boolean): Promise<void> {
  if (listElement("tasks") === null) {
    return;
  }
  try {
    const [tasksPayload, agentsPayload, modelsPayload, eventsPayload, voicePayload] =
      await Promise.all([
        fetchJson(coreApiUrl(coreUrl, "/tasks")),
        fetchJson(coreApiUrl(coreUrl, "/agents")),
        fetchJson(coreApiUrl(coreUrl, "/models")),
        fetchJson(coreApiUrl(coreUrl, "/events")),
        fetchJson(coreApiUrl(coreUrl, "/voice")),
      ]);
    const tasks = parentTasks(asTasks(tasksPayload));
    const voice = asVoice(voicePayload);
    renderList("tasks", tasks.map(taskLine), "no tasks");
    renderList("agents", asAgents(agentsPayload).map(agentLine), "no agents");
    renderList("models", asModels(modelsPayload).map(modelLine), "no models");
    renderList("notifications", asEvents(eventsPayload).map(notificationLine), "no notifications");
    showCharacter(
      tasks.map((task) => task.status),
      coreOk,
      voice.listening,
    );
    showVoice(voice);
  } catch (error) {
    const message = error instanceof Error ? error.message : "desktop data is unavailable";
    renderList("tasks", [message], message);
    showCharacter([], false, false);
  }
}

async function submitObjective(coreUrl: string, objective: string): Promise<void> {
  const result = listElement("launch-result");
  if (result !== null) {
    result.textContent = "running";
  }
  const payload = await fetchJson(coreApiUrl(coreUrl, "/tasks"), fetch, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ objective }),
  });
  const task = isRecord(payload) ? payload["task"] : null;
  const status = isRecord(task) && typeof task["status"] === "string" ? task["status"] : "unknown";
  if (result !== null) {
    result.textContent = status;
  }
}

async function refresh(status: HTMLElement, detail: HTMLElement): Promise<void> {
  const coreUrl = readCoreUrl(window.location.search);
  status.dataset["state"] = "checking";
  status.textContent = "checking";
  detail.textContent = coreHealthUrl(coreUrl);
  let coreOk = false;
  try {
    const health = await fetchHealth(coreUrl);
    coreOk = true;
    status.dataset["state"] = "ok";
    status.textContent = health.status;
    detail.textContent = `${health.service} ${health.version} · ${health.environment}`;
  } catch (error) {
    status.dataset["state"] = "unavailable";
    status.textContent = "unavailable";
    detail.textContent = error instanceof Error ? error.message : "Unknown error";
  }
  await refreshDesktop(coreUrl, coreOk);
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
    const launcher = document.getElementById("launcher");
    const objective = document.getElementById("objective");
    if (launcher instanceof HTMLFormElement && objective instanceof HTMLInputElement) {
      launcher.addEventListener("submit", (event) => {
        event.preventDefault();
        const text = objective.value.trim();
        if (text === "") {
          return;
        }
        void submitObjective(readCoreUrl(window.location.search), text)
          .then(() => refresh(status, detail))
          .catch((error: unknown) => {
            const result = listElement("launch-result");
            if (result !== null) {
              result.textContent = error instanceof Error ? error.message : "run failed";
            }
          });
      });
    }
    const listen = document.getElementById("voice-listen");
    if (listen instanceof HTMLButtonElement) {
      listen.disabled = true;
    }
    void refresh(status, detail);
  } catch (error) {
    console.error(error);
  }
}

if (typeof document !== "undefined") {
  bootstrap();
}
