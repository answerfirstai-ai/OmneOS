import { coreApiUrl, fetchJson } from "./api.js";
import { characterAsset, characterState } from "./character.js";
import {
  agentLine,
  modelLine,
  notificationLine,
  parentTasks,
  readDesktop,
  taskLine,
} from "./desktop.js";
import { coreHealthUrl, parseHealth, type CoreHealth } from "./health.js";
import { voiceControlEnabled, voiceSummary, type VoiceStatus } from "./voice.js";
import {
  activateWindow,
  closeWindow,
  focusedWindow,
  focusWindow,
  initialWindowState,
  isWindowId,
  openWindow,
  windowZ,
  WINDOW_IDS,
  type WindowId,
  type WindowState,
} from "./windows.js";

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
    throw new Error(`Unable to reach OMNE Core: ${message}`);
  }
  if (!response.ok) {
    throw new Error(`OMNE Core health request failed with status ${response.status}`);
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new Error("OMNE Core health response was not JSON");
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
  const values = lines.length > 0 ? lines : [empty];
  const rendered = values.join("\n");
  if (element.dataset["rendered"] === rendered) {
    return;
  }
  element.dataset["rendered"] = rendered;
  element.replaceChildren();
  for (const line of values) {
    const item = document.createElement("li");
    item.textContent = line;
    element.append(item);
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
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
    const desktop = readDesktop(await fetchJson(coreApiUrl(coreUrl, "/desktop")));
    const tasks = parentTasks(desktop.tasks);
    const voice = desktop.voice;
    renderList("tasks", tasks.map(taskLine), "no tasks");
    renderList("agents", desktop.agents.map(agentLine), "no agents");
    renderList("models", desktop.models.map(modelLine), "no models");
    renderList("notifications", desktop.events.map(notificationLine), "no notifications");
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

function showCoreStatus(
  status: HTMLElement,
  detail: HTMLElement,
  state: string,
  text: string,
  detailText: string,
): void {
  status.dataset["state"] = state;
  status.textContent = text;
  detail.textContent = detailText;
  const tray = listElement("tray-status");
  if (tray !== null) {
    tray.dataset["state"] = state;
    tray.textContent = text;
  }
}

async function refresh(status: HTMLElement, detail: HTMLElement): Promise<void> {
  const coreUrl = readCoreUrl(window.location.search);
  const alreadyOk = status.dataset["state"] === "ok";
  if (!alreadyOk) {
    showCoreStatus(status, detail, "checking", "checking", coreHealthUrl(coreUrl));
  }
  let coreOk = false;
  try {
    const health = await fetchHealth(coreUrl);
    coreOk = true;
    showCoreStatus(
      status,
      detail,
      "ok",
      health.status,
      `${health.service} ${health.version} · ${health.environment}`,
    );
  } catch (error) {
    showCoreStatus(
      status,
      detail,
      "unavailable",
      "unavailable",
      error instanceof Error ? error.message : "Unknown error",
    );
  }
  await refreshDesktop(coreUrl, coreOk);
}

function paintWindows(state: WindowState): void {
  const focus = focusedWindow(state);
  for (const id of WINDOW_IDS) {
    const frame = document.querySelector(`[data-window="${id}"]`);
    if (frame instanceof HTMLElement) {
      const open = state.open.includes(id);
      frame.hidden = !open;
      frame.style.zIndex = String(windowZ(state, id));
      frame.classList.toggle("is-focused", id === focus);
    }
    const task = document.querySelector(`[data-task="${id}"]`);
    if (task instanceof HTMLButtonElement) {
      task.hidden = !state.open.includes(id);
      task.setAttribute("aria-pressed", id === focus ? "true" : "false");
    }
    const icon = document.querySelector(`[data-launch="${id}"]`);
    if (icon instanceof HTMLButtonElement) {
      icon.setAttribute("aria-pressed", state.open.includes(id) ? "true" : "false");
    }
  }
}

function bindWindow(id: WindowId, onFocus: (id: WindowId) => void): void {
  const frame = document.querySelector(`[data-window="${id}"]`);
  if (!(frame instanceof HTMLElement)) {
    return;
  }
  frame.addEventListener("pointerdown", () => {
    onFocus(id);
  });
  const titlebar = frame.querySelector(".titlebar");
  if (!(titlebar instanceof HTMLElement)) {
    return;
  }
  titlebar.addEventListener("pointerdown", (event) => {
    if (!(event instanceof PointerEvent)) {
      return;
    }
    if (event.target instanceof Element && event.target.closest("button") !== null) {
      return;
    }
    const bounds = frame.getBoundingClientRect();
    const originX = event.clientX;
    const originY = event.clientY;
    const startLeft = bounds.left;
    const startTop = bounds.top;
    titlebar.setPointerCapture(event.pointerId);
    const move = (moveEvent: PointerEvent): void => {
      const nextLeft = Math.min(
        window.innerWidth - 72,
        Math.max(-bounds.width + 72, startLeft + moveEvent.clientX - originX),
      );
      const nextTop = Math.min(
        window.innerHeight - 92,
        Math.max(0, startTop + moveEvent.clientY - originY),
      );
      frame.style.left = `${nextLeft}px`;
      frame.style.top = `${nextTop}px`;
    };
    const stop = (stopEvent: PointerEvent): void => {
      titlebar.removeEventListener("pointermove", move);
      titlebar.removeEventListener("pointerup", stop);
      titlebar.removeEventListener("pointercancel", stop);
      if (titlebar.hasPointerCapture(stopEvent.pointerId)) {
        titlebar.releasePointerCapture(stopEvent.pointerId);
      }
    };
    titlebar.addEventListener("pointermove", move);
    titlebar.addEventListener("pointerup", stop);
    titlebar.addEventListener("pointercancel", stop);
  });
}

function bindDesktop(): void {
  if (document.getElementById("desktop") === null) {
    return;
  }
  let state = initialWindowState();
  const apply = (next: WindowState): void => {
    state = next;
    paintWindows(state);
  };
  apply(state);
  for (const id of WINDOW_IDS) {
    bindWindow(id, (windowId) => {
      apply(focusWindow(state, windowId));
    });
  }
  document.querySelectorAll("[data-launch]").forEach((node) => {
    node.addEventListener("click", () => {
      const id = node.getAttribute("data-launch");
      if (id !== null && isWindowId(id)) {
        apply(openWindow(state, id));
        hideStartMenu();
      }
    });
  });
  document.querySelectorAll("[data-task]").forEach((node) => {
    node.addEventListener("click", () => {
      const id = node.getAttribute("data-task");
      if (id !== null && isWindowId(id)) {
        apply(activateWindow(state, id));
      }
    });
  });
  document.querySelectorAll("[data-close]").forEach((node) => {
    node.addEventListener("click", () => {
      const id = node.getAttribute("data-close");
      if (id !== null && isWindowId(id)) {
        apply(closeWindow(state, id));
      }
    });
  });
  const start = document.getElementById("start");
  const menu = document.getElementById("start-menu");
  if (start instanceof HTMLButtonElement && menu instanceof HTMLElement) {
    start.addEventListener("click", () => {
      const open = menu.hidden;
      menu.hidden = !open;
      start.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      hideStartMenu();
    }
  });
  document.getElementById("desktop")?.addEventListener("pointerdown", (event) => {
    if (!(event.target instanceof Element)) {
      return;
    }
    if (event.target.closest(".window, .icons") !== null) {
      return;
    }
    hideStartMenu();
  });
  const clock = document.getElementById("clock");
  if (clock instanceof HTMLTimeElement) {
    const paintClock = (): void => {
      const now = new Date();
      clock.dateTime = now.toISOString();
      clock.textContent = now.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    };
    paintClock();
    window.setInterval(paintClock, 1000);
  }
}

function hideStartMenu(): void {
  const menu = document.getElementById("start-menu");
  const start = document.getElementById("start");
  if (menu instanceof HTMLElement) {
    menu.hidden = true;
  }
  if (start instanceof HTMLButtonElement) {
    start.setAttribute("aria-expanded", "false");
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
    const launcher = document.getElementById("launcher");
    const objective = document.getElementById("objective");
    if (launcher instanceof HTMLFormElement && objective instanceof HTMLInputElement) {
      launcher.addEventListener("submit", (event) => {
        event.preventDefault();
        const submit = launcher.querySelector("button[type='submit']");
        if (submit instanceof HTMLButtonElement && submit.disabled) {
          return;
        }
        const text = objective.value.trim();
        if (text === "") {
          return;
        }
        if (submit instanceof HTMLButtonElement) {
          submit.disabled = true;
        }
        void submitObjective(readCoreUrl(window.location.search), text)
          .then(() => refresh(status, detail))
          .catch((error: unknown) => {
            const result = listElement("launch-result");
            if (result !== null) {
              result.textContent = error instanceof Error ? error.message : "run failed";
            }
          })
          .finally(() => {
            if (submit instanceof HTMLButtonElement) {
              submit.disabled = false;
            }
          });
      });
    }
    const listen = document.getElementById("voice-listen");
    if (listen instanceof HTMLButtonElement) {
      listen.disabled = true;
    }
    bindDesktop();
    void refresh(status, detail);
  } catch (error) {
    console.error(error);
  }
}

if (typeof document !== "undefined") {
  bootstrap();
}
