import { coreApiUrl, fetchJson } from "./api.js";
import {
  COLOR_PRESETS,
  TYPE_PRESETS,
  WALLPAPER_PRESETS,
  bootSurface,
  nextSetupStep,
  postJson,
  previousSetupStep,
  readSetup,
  readTheme,
  stageDependencies,
  surfaceAfterUnlock,
  themeFromDraft,
  themeVariables,
  type SetupDraft,
  type SetupStep,
  type ThemeDocument,
} from "./firstboot.js";
import {
  activeMission,
  agentLine,
  attentionLine,
  waitingCancelTarget,
  chooseMission,
  describeModel,
  parentTasks,
  readDesktop,
  retainDesktop,
  shouldRepaint,
  type DesktopView,
  type MissionDocument,
} from "./desktop.js";
import { cycleDetail, detailLabel, type DetailLevel } from "./detail.js";
import { focusGraph } from "./graph-context.js";
import { stageLine } from "./lifecycle.js";
import {
  agentBoard,
  commandStory,
  desktopOrbit,
  displayName,
  markGlyph,
  missionListLabel,
  modelCards,
  modelLines,
  nameWorkers,
  orbitPoint,
  statusWord,
  taskSurface,
  verificationLine,
  workerName,
} from "./present.js";
import {
  cameraForNode,
  graphKey,
  graphStatuses,
  initialCamera,
  panCamera,
  readGraph,
  selectGraphNode,
  zoomCamera,
  type GraphCamera,
  type GraphLayout,
} from "./graph-layout.js";
import { hudText, readCompute, resourcePressure, type HudLine } from "./hud.js";
import { readAudioStatus, type AudioStatusView } from "./audio-status.js";
import {
  applicationLabel,
  applicationObjective,
  readApplications,
  type ApplicationView,
} from "./applications.js";
import { chordMatches, readInputStatus, type InputStatusView } from "./input-status.js";
import { readNetworkStatus, type NetworkStatusView } from "./network-status.js";
import { coreHealthUrl, parseHealth, type CoreHealth } from "./health.js";
import { inspectMission } from "./mission-view.js";
import { noticesFromEvents } from "./notify.js";
import { permissionPrompt } from "./permission-view.js";
import { LAUNCHER_ACTIONS } from "./launcher.js";
import { coreRenderer, presenceView } from "./presence.js";
import { readRecovery, type RecoveryState } from "./recovery.js";
import { matchDesktopCommand, matchShortcut, type DesktopCommand } from "./shortcuts.js";
import {
  activateWorkspace,
  cancelSwitcher,
  commitSwitcher,
  cycleMonitor,
  cycleSwitcher,
  cycleWorkspace,
  dismissToast,
  focusedOnWorkspace,
  frameOf,
  initialCompositor,
  isVisible,
  logicalDelta,
  monitorViews,
  moveFrame,
  paintedFrame,
  publishToasts,
  resizeFrame,
  shiftWindowWorkspace,
  syncWindows,
  toggleFullscreen,
  viewTransform,
  WINDOW_TITLES,
  windowMonitor,
  windowWorkspace,
  type CompositorState,
} from "./compositor.js";
import { voiceControlEnabled, voiceSummary, type VoiceStatus } from "./voice.js";
import {
  activateWindow,
  closeWindow,
  focusWindow,
  isWindowId,
  minimizeWindow,
  openWindow,
  toggleMaximize,
  windowZ,
  WINDOW_IDS,
  type WindowId,
  type WindowState,
} from "./windows.js";

const DEFAULT_CORE_URL = "http://127.0.0.1:8787";
const SVG_NS = "http://www.w3.org/2000/svg";

export type HealthFetcher = (input: string) => Promise<Response>;

let compositor: CompositorState = initialCompositor();
let windowState: WindowState = compositor.windows;
let desktopView: DesktopView | null = null;
let submittedObjective: string | null = null;
let selectedMissionId: string | null = null;
let graphCamera: GraphCamera = initialCamera();
let graphLayout: GraphLayout | null = null;
let resourceLines: HudLine[] = readCompute({});
let detailLevel: DetailLevel = "normal";
let desktopFlight = false;
let desktopAgain = false;
let computeFlight = false;
let networkFlight = false;
let networkStatus: NetworkStatusView = { text: "network unknown", state: "unknown" };
let audioFlight = false;
let audioStatus: AudioStatusView = { text: "audio unknown", state: "unknown" };
let inputFlight = false;
let inputStatus: InputStatusView = {
  text: "input unknown",
  state: "unknown",
  activation: "",
  cancel: "",
  pushToTalk: "",
  attention: "idle",
  revision: 0,
};
let inputSeen = -1;
let applicationFlight = false;
let applications: ApplicationView[] = [];
let recoveryState: RecoveryState | null = null;
let graphFlight = false;

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
  if (!shouldRepaint(element.dataset["rendered"] ?? null, rendered)) {
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

function showSync(message: string): void {
  const note = listElement("sync-note");
  if (note !== null) {
    note.textContent = message;
  }
}

function paintCharacter(
  host: HTMLElement | null,
  tray: HTMLElement | null,
  view: ReturnType<typeof presenceView>,
): void {
  if (host !== null) {
    coreRenderer.render(host, view);
  }
  if (tray !== null) {
    tray.dataset["state"] = view.state;
    tray.textContent = view.label;
  }
  const ask = listElement("presence-ask");
  if (ask !== null) {
    ask.hidden = view.ask === null;
    ask.textContent = view.ask ?? "";
  }
}

function paintPresence(coreOk: boolean): void {
  const host = listElement("presence");
  const tray = listElement("character");
  if (desktopView === null) {
    const view = presenceView({
      coreOk,
      voiceListening: false,
      statuses: [],
      recovery: recoveryState,
    });
    paintCharacter(host, tray, view);
    return;
  }
  const missions = desktopView.missions.map((mission) => mission.status);
  const latest = desktopView.events[desktopView.events.length - 1];
  const live = new Set(["ANALYZING", "PLANNING", "RUNNING", "RECOVERING", "VERIFYING", "WAITING"]);
  const activeAgents = [
    ...desktopView.activity
      .filter((item) => live.has(item.status) && item.assigned_agent !== null)
      .map((item) => item.assigned_agent ?? ""),
    ...desktopView.workers
      .filter((worker) => worker.status === "RUNNING")
      .map((worker) => worker.agent_id),
  ];
  const view = presenceView({
    coreOk,
    voiceListening: desktopView.voice.listening,
    statuses: parentTasks(desktopView.tasks).map((task) => task.status),
    activeAgents,
    recovery: recoveryState,
    waitingForUser: desktopView.confirmations.length > 0 || desktopView.questions.length > 0,
    ...(missions.length > 0 ? { missionStatuses: missions } : {}),
    ...(latest === undefined ? {} : { latestEvent: latest.type }),
  });
  paintCharacter(host, tray, view);
  const objective = listElement("presence-objective");
  const current = activeMission(desktopView.missions);
  if (objective !== null) {
    objective.textContent = current === null ? "No active mission" : current.objective;
  }
  const attention = listElement("presence-attention");
  if (attention !== null) {
    attention.textContent = attentionLine(desktopView.questions, desktopView.confirmations) ?? "";
  }
  paintOrbit();
}

function paintDesktop(coreOk: boolean): void {
  if (desktopView === null) {
    paintPresence(coreOk);
    return;
  }
  paintTasks();
  paintAgents();
  paintModels();
  paintNotifications();
  paintMissions();
  paintWorkers();
  paintPermissions();
  paintLauncher();
  paintProject();
  paintPresence(coreOk);
  showVoice(desktopView.voice);
  if (graphLayout !== null) {
    paintGraph();
  }
}

function paintTasks(): void {
  const element = listElement("tasks");
  if (element === null || desktopView === null) {
    return;
  }
  const lines = taskSurface(desktopView.tasks, detailLevel);
  renderList("tasks", lines, "Nothing running");
}

function paintAgents(): void {
  const element = listElement("agents");
  if (element === null || desktopView === null) {
    return;
  }
  const board = agentBoard(desktopView.agents, desktopView.workers);
  const rendered = `${detailLevel}\n${board.definitions.map((agent) => agent.id).join(",")}\n${board.active
    .map((worker) => worker.id + worker.status)
    .join(",")}\n${board.paused.map((worker) => worker.id).join(",")}\n${board.idle
    .map((worker) => worker.id)
    .join(",")}`;
  if (!shouldRepaint(element.dataset["rendered"] ?? null, rendered)) {
    return;
  }
  element.dataset["rendered"] = rendered;
  element.replaceChildren();
  element.append(heading("Agent definitions"));
  element.append(
    linesOrEmpty(
      board.definitions.map((agent) => agentDefinition(agent)),
      "no agents",
    ),
  );
  element.append(heading("Active workers"));
  element.append(
    linesOrEmpty(
      board.active.map((worker) => workerBoardLine(worker)),
      "No active workers",
    ),
  );
  if (board.paused.length > 0) {
    element.append(heading("Paused workers"));
    element.append(
      linesOrEmpty(
        board.paused.map((worker) => workerBoardLine(worker)),
        "none",
      ),
    );
  }
  if (detailLevel !== "normal") {
    element.append(heading("Idle workers"));
    element.append(
      linesOrEmpty(
        board.idle.map((worker) => workerBoardLine(worker)),
        "No idle workers",
      ),
    );
  }
}

function agentDefinition(agent: {
  id: string;
  name: string;
  state: string;
  enabled: boolean;
}): string {
  if (detailLevel === "debug") {
    return agentLine({ id: agent.id, state: agent.state, enabled: agent.enabled });
  }
  if (detailLevel === "inspect") {
    return `${agent.name} definition ${agent.state}`;
  }
  return agent.name;
}

function workerBoardLine(worker: { id: string; name: string; status: string }): string {
  const status = statusWord(worker.status);
  if (detailLevel === "debug") {
    return `${worker.name} ${worker.id} ${status}`;
  }
  return `${worker.name} ${status}`;
}

function paintModels(): void {
  const element = listElement("models");
  if (element === null || desktopView === null) {
    return;
  }
  const cards = modelCards(desktopView.models, desktopView.activity);
  const rendered = `${detailLevel}\n${cards.local
    .concat(cards.cloud)
    .map((card) => `${card.id}:${card.state}:${card.work ?? ""}`)
    .join(",")}`;
  if (!shouldRepaint(element.dataset["rendered"] ?? null, rendered)) {
    return;
  }
  element.dataset["rendered"] = rendered;
  element.replaceChildren();
  element.append(heading("Local"));
  element.append(
    linesOrEmpty(
      cards.local.flatMap((card) => modelLines(card, detailLevel)),
      "none",
    ),
  );
  element.append(heading("Cloud"));
  element.append(
    linesOrEmpty(
      cards.cloud.flatMap((card) => modelLines(card, detailLevel)),
      "none",
    ),
  );
  element.append(heading("Active"));
  if (cards.active.length === 0) {
    element.append(linesOrEmpty([], "none"));
  } else {
    for (const card of cards.active) {
      const block = document.createElement("p");
      block.textContent = card.work === null ? card.name : `${card.name} Working on: ${card.work}`;
      if (detailLevel === "debug") {
        block.textContent = `${describeModelLine(card.id)} ${block.textContent}`;
      }
      element.append(block);
    }
  }
}

function describeModelLine(id: string): string {
  const model = desktopView?.models.find((item) => item.id === id);
  return model === undefined ? id : describeModel(model);
}

function paintOrbit(): void {
  const host = listElement("orbit");
  if (host === null || desktopView === null) {
    host?.replaceChildren();
    return;
  }
  const mission = activeMission(desktopView.missions);
  const named = nameWorkers(desktopView.workers);
  const tasks =
    mission === null
      ? []
      : desktopView.activity
          .filter((item) => item.mission_id === mission.id || item.parent_task === mission.task_id)
          .map((item) => ({ id: item.id, label: item.objective, status: item.status }));
  const workers =
    mission === null
      ? []
      : desktopView.workers
          .filter((worker) => worker.current_mission === mission.id)
          .map((worker) => ({
            id: worker.worker_id,
            name: workerName(named, worker.worker_id, worker.agent_id),
            status: worker.status,
          }));
  const items = desktopOrbit({ mission, tasks, workers });
  const rendered = items.map((item) => `${item.id}:${item.status}:${item.label}`).join("\n");
  if (!shouldRepaint(host.dataset["rendered"] ?? null, rendered)) {
    return;
  }
  host.dataset["rendered"] = rendered;
  host.replaceChildren();
  items.forEach((item, index) => {
    const point = orbitPoint(index, items.length, 118);
    const label = document.createElement("span");
    label.textContent = `${statusWord(item.status)} ${item.label}`.slice(0, 42);
    label.style.left = `calc(50% + ${point.x}px)`;
    label.style.top = `calc(46% + ${point.y}px)`;
    host.append(label);
  });
}

function paintNotifications(): void {
  const element = listElement("notifications");
  if (element === null || desktopView === null) {
    return;
  }
  const notices = noticesFromEvents(desktopView.events);
  const toasted = publishToasts(
    compositor,
    notices.map((notice) => ({ id: notice.id, text: notice.text })),
  );
  if (toasted !== compositor) {
    compositor = toasted;
    windowState = toasted.windows;
    paintToasts();
  }
  const rendered = `${detailLevel}\n${notices
    .map((notice) => `${notice.id}:${notice.text}`)
    .join("\n")}`;
  if (!shouldRepaint(element.dataset["rendered"] ?? null, rendered)) {
    return;
  }
  element.dataset["rendered"] = rendered;
  element.replaceChildren();
  if (notices.length === 0) {
    const item = document.createElement("li");
    item.textContent = "no notifications";
    element.append(item);
    return;
  }
  for (const notice of notices) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "linkish";
    button.textContent = detailLevel === "debug" ? `${notice.text} ${notice.id}` : notice.text;
    if (notice.missionId !== null) {
      button.addEventListener("click", () => {
        inspectNotice(notice.missionId);
      });
    }
    item.append(button);
    element.append(item);
  }
}

function inspectNotice(missionId: string | null): void {
  if (missionId === null) {
    return;
  }
  selectedMissionId = missionId;
  applyWindows(openWindow(windowState, "missions"));
  paintMissions();
}

function paintMissions(): void {
  const list = listElement("missions");
  const detail = listElement("mission-detail");
  if (list === null || detail === null || desktopView === null) {
    return;
  }
  const missions = desktopView.missions;
  const rendered = `${detailLevel}\n${missions.map((mission) => `${mission.id}:${mission.status}`).join("\n")}`;
  if (shouldRepaint(list.dataset["rendered"] ?? null, rendered || "empty")) {
    list.dataset["rendered"] = rendered || "empty";
    list.replaceChildren();
    if (missions.length === 0) {
      const item = document.createElement("li");
      item.textContent = "no missions";
      list.append(item);
    } else {
      for (const mission of missions) {
        const item = document.createElement("li");
        const button = document.createElement("button");
        button.type = "button";
        button.className = "linkish";
        button.textContent = missionListLabel(mission, detailLevel);
        button.addEventListener("click", () => {
          selectedMissionId = mission.id;
          paintMissionDetail();
        });
        item.append(button);
        list.append(item);
      }
    }
  }
  paintMissionDetail();
}

function paintMissionDetail(): void {
  const detail = listElement("mission-detail");
  if (detail === null || desktopView === null) {
    return;
  }
  const mission = selectedMission(desktopView.missions);
  if (mission === null) {
    if (shouldRepaint(detail.dataset["rendered"] ?? null, "empty")) {
      detail.dataset["rendered"] = "empty";
      detail.replaceChildren();
      const empty = document.createElement("p");
      empty.textContent = "Select a mission.";
      detail.append(empty);
    }
    return;
  }
  const inspection = inspectMission(mission, {
    activity: desktopView.activity,
    workers: desktopView.workers,
    models: desktopView.models,
    questions: desktopView.questions,
    resources: resourceLines,
  });
  const rendered = `${detailLevel}\n${JSON.stringify(inspection)}`;
  if (!shouldRepaint(detail.dataset["rendered"] ?? null, rendered)) {
    return;
  }
  detail.dataset["rendered"] = rendered;
  const named = nameWorkers(desktopView.workers);
  detail.replaceChildren();
  const title = document.createElement("p");
  title.className = "mission-title";
  title.textContent = inspection.objective;
  detail.append(title);
  detail.append(
    linesOrEmpty(
      inspection.tasks.map((task) => `${markGlyph(task.mark)} ${task.label}`),
      "No tasks yet",
    ),
  );
  detail.append(heading("Workers"));
  detail.append(
    linesOrEmpty(
      inspection.workers.map((worker) => {
        const name = workerName(named, worker.workerId, worker.agentId);
        const line = `${name} ${statusWord(worker.status)}`;
        return detailLevel === "debug" ? `${line} ${worker.workerId}` : line;
      }),
      "No workers on this mission",
    ),
  );
  if (detailLevel !== "normal") {
    detail.append(heading("Models"));
    detail.append(
      linesOrEmpty(
        inspection.models.map((model) =>
          detailLevel === "debug"
            ? `${model.id} ${model.provider} ${model.lifecycle}`
            : `${model.id} ${model.lifecycle}`,
        ),
        "No model assigned",
      ),
    );
  }
  detail.append(heading("Resources"));
  detail.append(
    linesOrEmpty(
      resourceLines.map((line) => `${line.label} ${line.value}`),
      "unknown",
    ),
  );
  detail.append(heading("Verification"));
  const verification = document.createElement("p");
  verification.textContent = verificationLine(inspection.verification);
  detail.append(verification);
  if (detailLevel !== "normal" && inspection.verification.lines.length > 0) {
    detail.append(linesOrEmpty(inspection.verification.lines, ""));
  }
  if (inspection.path.length > 0) {
    detail.append(heading("Decision"));
    detail.append(linesOrEmpty(inspection.path, ""));
  }
  if (inspection.question !== null) {
    detail.append(heading("OMNE needs clarification"));
    const question = document.createElement("p");
    question.textContent = inspection.question;
    detail.append(question);
    const cancel = actionButton("Cancel", () => {
      void cancelTarget({ kind: "mission", id: inspection.id });
    });
    detail.append(cancel);
  }
  const lifecycleDetails = document.createElement("details");
  const lifecycleSummary = document.createElement("summary");
  lifecycleSummary.textContent = "Technical details";
  lifecycleDetails.append(lifecycleSummary, stageList(inspection.lifecycle.map(stageLine)));
  if (detailLevel === "debug") {
    lifecycleDetails.append(fact("Mission", inspection.id));
    lifecycleDetails.append(fact("Status", inspection.status));
  }
  detail.append(lifecycleDetails);
  if (inspection.error !== null) {
    detail.append(heading(inspection.error.what));
    detail.append(fact("Why", inspection.error.why));
    detail.append(fact("Next", inspection.error.next));
    if (inspection.error.tried.length > 0) {
      detail.append(fact("Tried", inspection.error.tried.join(", ")));
    }
    const technical = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "Technical details";
    const body = document.createElement("p");
    body.textContent = inspection.error.technical;
    technical.append(summary, body);
    detail.append(technical);
  }
}

function commandMission(): MissionDocument | null {
  if (desktopView === null) {
    return null;
  }
  if (submittedObjective !== null) {
    return chooseMission(desktopView.missions, submittedObjective);
  }
  return activeMission(desktopView.missions);
}

function selectedMission(missions: readonly MissionDocument[]): MissionDocument | null {
  if (selectedMissionId !== null) {
    const chosen = missions.find((mission) => mission.id === selectedMissionId);
    if (chosen !== undefined) {
      return chosen;
    }
  }
  return chooseMission(missions, submittedObjective);
}

function paintWorkers(): void {
  const element = listElement("workers");
  if (element === null || desktopView === null) {
    return;
  }
  const named = nameWorkers(desktopView.workers);
  const rendered = `${detailLevel}\n${named.map((worker) => `${worker.id}:${worker.status}`).join(",")}`;
  if (!shouldRepaint(element.dataset["rendered"] ?? null, rendered || "empty")) {
    return;
  }
  element.dataset["rendered"] = rendered || "empty";
  element.replaceChildren();
  const board = agentBoard(desktopView.agents, desktopView.workers);
  element.append(heading("Runtime workers"));
  element.append(
    linesOrEmpty(
      board.active.map((worker) => workerBoardLine(worker)),
      "No active workers",
    ),
  );
  if (board.paused.length > 0) {
    element.append(heading("Paused workers"));
    element.append(
      linesOrEmpty(
        board.paused.map((worker) => workerBoardLine(worker)),
        "none",
      ),
    );
  }
  if (detailLevel === "normal" && board.idle.length > 0) {
    element.append(linesOrEmpty([`${board.idle.length} idle`], "none"));
  }
  if (detailLevel !== "normal") {
    element.append(heading("Idle workers"));
    element.append(
      linesOrEmpty(
        board.idle.map((worker) => workerBoardLine(worker)),
        "No idle workers",
      ),
    );
    if (board.stopped.length > 0) {
      element.append(heading("Stopped workers"));
      element.append(
        linesOrEmpty(
          board.stopped.map((worker) => workerBoardLine(worker)),
          "none",
        ),
      );
    }
  }
}

function paintPermissions(): void {
  const element = listElement("permissions");
  if (element === null || desktopView === null) {
    return;
  }
  const prompts = desktopView.confirmations.map((confirmation) => {
    const mission = desktopView?.missions.find((item) => item.id === confirmation.mission_id);
    return permissionPrompt({
      taskId: confirmation.task_id,
      toolId: confirmation.tool_id,
      command: confirmation.command,
      agentId: confirmation.agent_id,
      missionObjective: mission?.objective ?? null,
    });
  });
  const rendered = prompts.map((prompt) => `${prompt.taskId}:${prompt.command}`).join("\n");
  if (!shouldRepaint(element.dataset["rendered"] ?? null, rendered)) {
    return;
  }
  element.dataset["rendered"] = rendered;
  element.replaceChildren();
  for (const prompt of prompts) {
    const block = document.createElement("section");
    block.className = "permission";
    const heading = document.createElement("h3");
    heading.textContent = prompt.heading;
    block.append(heading);
    block.append(fact("Command", prompt.command));
    block.append(fact("Reason", prompt.reason));
    block.append(fact("Impact", prompt.impact));
    block.append(
      fact(
        "Requested by",
        detailLevel === "debug" ? prompt.requester : displayName(prompt.requester),
      ),
    );
    block.append(fact("Mission", prompt.mission));
    const actions = document.createElement("div");
    actions.className = "actions";
    actions.append(
      actionButton("Allow", () => {
        void confirmTask(prompt.taskId, true);
      }),
      actionButton("Deny", () => {
        void confirmTask(prompt.taskId, false);
      }),
      actionButton("Cancel", () => {
        void cancelTarget({ kind: "task", id: prompt.taskId });
      }),
      actionButton("Inspect", () => {
        const confirmation = desktopView?.confirmations.find(
          (item) => item.task_id === prompt.taskId,
        );
        inspectNotice(confirmation?.mission_id ?? null);
      }),
    );
    block.append(actions);
    element.append(block);
  }
}

function paintLauncher(): void {
  const story = listElement("command-story");
  const list = listElement("launch-lifecycle");
  const result = listElement("launch-result");
  if (story === null || list === null || desktopView === null) {
    return;
  }
  const mission = commandMission();
  if (mission === null) {
    if (shouldRepaint(story.dataset["rendered"] ?? null, "empty")) {
      story.dataset["rendered"] = "empty";
      story.replaceChildren();
      list.replaceChildren();
      if (result !== null) {
        result.textContent = "";
      }
    }
    return;
  }
  const inspection = inspectMission(mission, {
    activity: desktopView.activity,
    workers: desktopView.workers,
    models: desktopView.models,
    questions: desktopView.questions,
    resources: resourceLines,
  });
  const named = nameWorkers(desktopView.workers);
  const beats = commandStory({
    lifecycle: inspection.lifecycle,
    taskCount: inspection.tasks.length,
    workers: inspection.workers.map((worker) => ({
      name: workerName(named, worker.workerId, worker.agentId),
      status: worker.status,
    })),
    verification: inspection.verification,
  });
  const rendered = `${detailLevel}\n${JSON.stringify(beats)}\n${inspection.path.join("|")}`;
  if (shouldRepaint(story.dataset["rendered"] ?? null, rendered)) {
    story.dataset["rendered"] = rendered;
    story.replaceChildren();
    const request = document.createElement("p");
    request.className = "command-request";
    request.textContent = inspection.objective;
    story.append(request);
    for (const beat of beats) {
      const block = document.createElement("section");
      const title = document.createElement("h3");
      title.textContent = beat.title;
      const items = document.createElement("ul");
      for (const line of beat.lines) {
        const item = document.createElement("li");
        item.textContent = `${markGlyph(line.mark)} ${line.text}`;
        items.append(item);
      }
      block.append(title, items);
      story.append(block);
    }
    const lines = inspection.lifecycle.map(stageLine);
    list.replaceChildren();
    for (const line of lines) {
      const item = document.createElement("li");
      item.textContent = line;
      list.append(item);
    }
    if (inspection.path.length > 0) {
      const decision = document.createElement("section");
      const title = document.createElement("h3");
      title.textContent = "Decision";
      const items = document.createElement("ul");
      for (const line of inspection.path) {
        const item = document.createElement("li");
        item.textContent = line;
        items.append(item);
      }
      decision.append(title, items);
      story.append(decision);
    }
    if (result !== null) {
      const evidence = inspection.verification.lines[0];
      result.textContent =
        detailLevel === "normal" || evidence === undefined
          ? verificationLine(inspection.verification)
          : `${verificationLine(inspection.verification)} ${evidence}`;
    }
  }
}

function paintProject(): void {
  const element = listElement("project-facts");
  if (element === null || desktopView === null) {
    return;
  }
  const project = desktopView.project;
  const rendered =
    project === null
      ? "empty"
      : `${project.name}|${project.type}|${project.git_branch ?? ""}|${project.languages.join(",")}`;
  if (!shouldRepaint(element.dataset["rendered"] ?? null, rendered)) {
    return;
  }
  element.dataset["rendered"] = rendered;
  element.replaceChildren();
  if (project === null) {
    const empty = document.createElement("p");
    empty.textContent = "no project";
    element.append(empty);
    return;
  }
  element.append(fact("Name", project.name));
  element.append(fact("Type", project.type));
  element.append(fact("Branch", project.git_branch ?? "unknown"));
  element.append(
    fact("Languages", project.languages.length > 0 ? project.languages.join(", ") : "unknown"),
  );
}

function paintLauncherActions(): void {
  const list = document.getElementById("launcher-actions");
  if (!(list instanceof HTMLUListElement) || list.childElementCount > 0) {
    return;
  }
  for (const action of LAUNCHER_ACTIONS) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.dataset["launcherAction"] = action.id;
    button.textContent = action.label;
    button.addEventListener("click", () => {
      const objective = document.getElementById("objective");
      if (objective instanceof HTMLInputElement) {
        objective.value = action.objective;
      }
      void runObjective(action.objective);
    });
    item.append(button);
    list.append(item);
  }
}

function paintApplications(): void {
  const list = document.getElementById("applications");
  if (!(list instanceof HTMLUListElement)) {
    return;
  }
  list.replaceChildren();
  for (const app of applications) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.dataset["application"] = app.id;
    button.textContent = applicationLabel(app);
    button.addEventListener("click", () => {
      const objective = document.getElementById("objective");
      if (objective instanceof HTMLInputElement) {
        objective.value = applicationObjective(app.name);
        objective.focus();
      }
    });
    item.append(button);
    list.append(item);
  }
}

function paintInput(): void {
  const element = listElement("input-status");
  if (element === null) {
    return;
  }
  if (!shouldRepaint(element.dataset["rendered"] ?? null, inputStatus.text)) {
    return;
  }
  element.dataset["rendered"] = inputStatus.text;
  element.dataset["state"] = inputStatus.state;
  element.dataset["talk"] = inputStatus.pushToTalk.length > 0 ? "prepared" : "unconfigured";
  element.textContent = inputStatus.text;
}

function openCommand(): void {
  applyWindows(openWindow(windowState, "launcher"));
  const objective = document.getElementById("objective");
  if (objective instanceof HTMLInputElement) {
    objective.focus();
  }
}

function cancelCommand(): void {
  const target = desktopView === null ? null : waitingCancelTarget(desktopView);
  applyWindows(closeWindow(windowState, "launcher"));
  const objective = document.getElementById("objective");
  if (objective instanceof HTMLInputElement) {
    objective.blur();
  }
  hideStartMenu();
  if (target !== null) {
    void cancelTarget(target);
  }
}

function paintAudio(): void {
  const element = listElement("audio-status");
  if (element === null) {
    return;
  }
  if (!shouldRepaint(element.dataset["rendered"] ?? null, audioStatus.text)) {
    return;
  }
  element.dataset["rendered"] = audioStatus.text;
  element.dataset["state"] = audioStatus.state;
  element.textContent = audioStatus.text;
}

function paintNetwork(): void {
  const element = listElement("network-status");
  if (element === null) {
    return;
  }
  if (!shouldRepaint(element.dataset["rendered"] ?? null, networkStatus.text)) {
    return;
  }
  element.dataset["rendered"] = networkStatus.text;
  element.dataset["state"] = networkStatus.state;
  element.textContent = networkStatus.text;
}

function paintHud(): void {
  const element = listElement("hud");
  if (element === null) {
    return;
  }
  const rendered = hudText(resourceLines);
  if (!shouldRepaint(element.dataset["rendered"] ?? null, rendered)) {
    return;
  }
  element.dataset["rendered"] = rendered;
  element.replaceChildren();
  for (const line of resourceLines) {
    const item = document.createElement("span");
    item.textContent = `${line.label} ${line.value}`;
    element.append(item);
  }
  const pressure = resourcePressure(resourceLines);
  const note = listElement("graph-pressure");
  if (note !== null) {
    note.textContent = pressure ?? "";
  }
}

function paintGraph(): void {
  const host = listElement("graph-view");
  if (host === null || graphLayout === null || desktopView === null) {
    return;
  }
  const statuses = graphStatuses({
    missions: desktopView.missions,
    activity: desktopView.activity,
    workers: desktopView.workers,
  });
  const missionId = graphMissionId();
  const shown = focusGraph(graphLayout, missionId);
  const key = `${detailLevel}:${missionId ?? "core"}:${graphKey(shown, statuses)}`;
  if (shouldRepaint(host.dataset["rendered"] ?? null, key)) {
    host.dataset["rendered"] = key;
    host.replaceChildren();
    const scene = document.createElementNS(SVG_NS, "svg");
    scene.setAttribute("class", "graph-svg");
    scene.setAttribute("role", "img");
    scene.setAttribute("aria-label", "OMNE system graph");
    const group = document.createElementNS(SVG_NS, "g");
    group.id = "graph-scene";
    const byId = new Map(shown.nodes.map((node) => [node.id, node]));
    for (const edge of shown.edges) {
      const from = byId.get(edge.from);
      const to = byId.get(edge.to);
      if (from === undefined || to === undefined) {
        continue;
      }
      const line = document.createElementNS(SVG_NS, "line");
      line.setAttribute("x1", String(from.x));
      line.setAttribute("y1", String(from.y));
      line.setAttribute("x2", String(to.x));
      line.setAttribute("y2", String(to.y));
      line.setAttribute("class", "graph-edge");
      group.append(line);
    }
    for (const node of shown.nodes) {
      const item = document.createElementNS(SVG_NS, "g");
      item.setAttribute("class", "graph-node");
      item.dataset["id"] = node.id;
      item.setAttribute("tabindex", "0");
      item.setAttribute("role", "button");
      item.setAttribute("aria-label", `${node.type} ${node.label}`);
      const status = statuses.get(node.id);
      if (status !== undefined) {
        item.dataset["status"] = status;
      }
      const circle = document.createElementNS(SVG_NS, "circle");
      circle.setAttribute("cx", String(node.x));
      circle.setAttribute("cy", String(node.y));
      circle.setAttribute("r", "8");
      const text = document.createElementNS(SVG_NS, "text");
      text.setAttribute("x", String(node.x + 12));
      text.setAttribute("y", String(node.y + 4));
      text.textContent = graphNodeLabel(node).slice(0, 32);
      item.append(circle, text);
      item.addEventListener("click", () => {
        graphCamera = selectGraphNode(graphCamera, node.id);
        applyGraphCamera();
      });
      item.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          graphCamera = selectGraphNode(graphCamera, node.id);
          applyGraphCamera();
        }
      });
      group.append(item);
    }
    scene.append(group);
    host.append(scene);
    if (host.dataset["wheel"] !== "1") {
      host.dataset["wheel"] = "1";
      host.addEventListener(
        "wheel",
        (event) => {
          event.preventDefault();
          graphCamera = zoomCamera(graphCamera, event.deltaY > 0 ? 0.9 : 1.1);
          applyGraphCamera();
        },
        { passive: false },
      );
    }
    scene.addEventListener("pointerdown", (event) => {
      if (!(event.target instanceof Element) || event.target.closest(".graph-node") !== null) {
        return;
      }
      const originX = event.clientX;
      const originY = event.clientY;
      const start = graphCamera;
      const move = (moveEvent: PointerEvent): void => {
        graphCamera = panCamera(start, moveEvent.clientX - originX, moveEvent.clientY - originY);
        applyGraphCamera();
      };
      const stop = (): void => {
        scene.removeEventListener("pointermove", move);
        scene.removeEventListener("pointerup", stop);
      };
      scene.addEventListener("pointermove", move);
      scene.addEventListener("pointerup", stop);
    });
  }
  applyGraphCamera();
}

function applyGraphCamera(): void {
  const group = document.getElementById("graph-scene");
  if (group instanceof SVGGElement) {
    group.setAttribute(
      "transform",
      `translate(${graphCamera.x} ${graphCamera.y}) scale(${graphCamera.scale})`,
    );
  }
  document.querySelectorAll(".graph-node").forEach((node) => {
    if (node instanceof SVGElement) {
      node.classList.toggle("is-selected", node.dataset["id"] === graphCamera.selectedId);
    }
  });
}

function graphMissionId(): string | null {
  if (desktopView === null) {
    return null;
  }
  const active = activeMission(desktopView.missions);
  if (active !== null) {
    return active.id;
  }
  if (detailLevel === "normal") {
    return null;
  }
  return selectedMission(desktopView.missions)?.id ?? null;
}

function graphNodeLabel(node: { id: string; type: string; label: string }): string {
  if (desktopView !== null && node.type === "worker") {
    const named = nameWorkers(desktopView.workers);
    const worker = desktopView.workers.find((item) => item.worker_id === node.id);
    if (worker !== undefined) {
      return workerName(named, worker.worker_id, worker.agent_id);
    }
  }
  if (detailLevel !== "debug" && (node.type === "agent" || node.type === "model")) {
    return displayName(node.label);
  }
  return node.label;
}

function focusActiveMission(): void {
  const host = listElement("graph-view");
  if (host === null || graphLayout === null || desktopView === null) {
    return;
  }
  const missionId = graphMissionId();
  if (missionId === null) {
    return;
  }
  const node =
    focusGraph(graphLayout, missionId).nodes.find((item) => item.id === missionId) ?? null;
  graphCamera = cameraForNode(selectGraphNode(graphCamera, missionId), node, {
    width: host.clientWidth || 320,
    height: host.clientHeight || 240,
  });
  applyGraphCamera();
}

function fact(label: string, value: string): HTMLElement {
  const paragraph = document.createElement("p");
  const name = document.createElement("span");
  name.className = "fact-label";
  name.textContent = label;
  paragraph.append(name, document.createTextNode(` ${value}`));
  return paragraph;
}

function heading(text: string): HTMLElement {
  const title = document.createElement("h3");
  title.textContent = text;
  return title;
}

function linesOrEmpty(lines: readonly string[], empty: string): HTMLElement {
  const list = document.createElement("ul");
  const values = lines.length > 0 ? lines : [empty];
  for (const line of values) {
    if (line === "") {
      continue;
    }
    const item = document.createElement("li");
    item.textContent = line;
    list.append(item);
  }
  return list;
}

function stageList(lines: readonly string[]): HTMLElement {
  const list = document.createElement("ol");
  list.className = "lifecycle";
  for (const line of lines) {
    const item = document.createElement("li");
    item.textContent = line;
    list.append(item);
  }
  return list;
}

function actionButton(label: string, onClick: () => void): HTMLButtonElement {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.addEventListener("click", onClick);
  return button;
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
  if (desktopFlight) {
    desktopAgain = true;
    return;
  }
  desktopFlight = true;
  try {
    do {
      desktopAgain = false;
      try {
        const next = readDesktop(await fetchJson(coreApiUrl(coreUrl, "/desktop")));
        desktopView = retainDesktop(desktopView, next);
        showSync("");
      } catch (error) {
        desktopView = retainDesktop(desktopView, null);
        const message = error instanceof Error ? error.message : "desktop data is unavailable";
        showSync(message);
        if (desktopView === null) {
          paintPresence(false);
        }
      }
      paintDesktop(coreOk && desktopView !== null);
    } while (desktopAgain);
  } finally {
    desktopFlight = false;
  }
}

async function refreshApplications(coreUrl: string): Promise<void> {
  if (applicationFlight) {
    return;
  }
  applicationFlight = true;
  try {
    applications = readApplications(await fetchJson(coreApiUrl(coreUrl, "/applications")));
  } catch {
    applications = [];
  } finally {
    applicationFlight = false;
  }
  paintApplications();
}

async function refreshInput(coreUrl: string): Promise<void> {
  if (inputFlight) {
    return;
  }
  inputFlight = true;
  try {
    inputStatus = readInputStatus(await fetchJson(coreApiUrl(coreUrl, "/input")));
  } catch {
    inputStatus = {
      text: "input unknown",
      state: "unknown",
      activation: inputStatus.activation,
      cancel: inputStatus.cancel,
      pushToTalk: inputStatus.pushToTalk,
      attention: inputStatus.attention,
      revision: inputSeen < 0 ? 0 : inputSeen,
    };
  } finally {
    inputFlight = false;
  }
  const revision = inputStatus.revision;
  if (inputSeen >= 0 && revision !== inputSeen) {
    if (inputStatus.attention === "command") {
      openCommand();
    } else {
      cancelCommand();
    }
  }
  inputSeen = revision;
  paintInput();
}

async function refreshAudio(coreUrl: string): Promise<void> {
  if (audioFlight) {
    return;
  }
  audioFlight = true;
  try {
    audioStatus = readAudioStatus(await fetchJson(coreApiUrl(coreUrl, "/audio")));
  } catch {
    audioStatus = { text: "audio unknown", state: "unknown" };
  } finally {
    audioFlight = false;
  }
  paintAudio();
}

async function refreshNetwork(coreUrl: string): Promise<void> {
  if (networkFlight) {
    return;
  }
  networkFlight = true;
  try {
    networkStatus = readNetworkStatus(await fetchJson(coreApiUrl(coreUrl, "/network")));
  } catch {
    networkStatus = { text: "network unknown", state: "unknown" };
  } finally {
    networkFlight = false;
  }
  paintNetwork();
}

async function refreshCompute(coreUrl: string): Promise<void> {
  if (computeFlight) {
    return;
  }
  computeFlight = true;
  try {
    resourceLines = readCompute(await fetchJson(coreApiUrl(coreUrl, "/compute")));
    paintHud();
    paintMissionDetail();
    paintLauncher();
  } catch {
    resourceLines = readCompute({});
    paintHud();
  } finally {
    computeFlight = false;
  }
}

async function refreshGraph(coreUrl: string): Promise<void> {
  const visible = windowState.open.includes("graph") && !windowState.minimized.includes("graph");
  if (!visible || graphFlight) {
    return;
  }
  graphFlight = true;
  try {
    const next = readGraph(await fetchJson(coreApiUrl(coreUrl, "/graph")));
    const statuses =
      desktopView === null
        ? new Map<string, string>()
        : graphStatuses({
            missions: desktopView.missions,
            activity: desktopView.activity,
            workers: desktopView.workers,
          });
    if (graphLayout === null || graphKey(graphLayout, statuses) !== graphKey(next, statuses)) {
      graphLayout = next;
    }
    paintGraph();
  } catch {
    paintGraph();
  } finally {
    graphFlight = false;
  }
}

async function cancelTarget(target: { kind: "task" | "mission"; id: string }): Promise<void> {
  const coreUrl = readCoreUrl(window.location.search);
  const path =
    target.kind === "task" ? `/tasks/${target.id}/cancel` : `/missions/${target.id}/cancel`;
  await fetchJson(coreApiUrl(coreUrl, path), fetch, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  const status = listElement("status");
  const detail = listElement("detail");
  if (status !== null && detail !== null) {
    await refresh(status, detail);
  }
}

async function confirmTask(taskId: string, approved: boolean): Promise<void> {
  const coreUrl = readCoreUrl(window.location.search);
  await fetchJson(coreApiUrl(coreUrl, `/tasks/${taskId}/confirm`), fetch, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approved }),
  });
  const status = listElement("status");
  const detail = listElement("detail");
  if (status !== null && detail !== null) {
    await refresh(status, detail);
  }
}

function runObjective(objective: string): Promise<void> {
  const launcher = document.getElementById("launcher");
  const submit = launcher?.querySelector("button[type='submit']");
  const actions = Array.from(
    document.querySelectorAll<HTMLButtonElement>("[data-launcher-action]"),
  );
  if (submit instanceof HTMLButtonElement && submit.disabled) {
    return Promise.resolve();
  }
  if (submit instanceof HTMLButtonElement) {
    submit.disabled = true;
  }
  for (const action of actions) {
    action.disabled = true;
  }
  const status = requireElement("status");
  const detail = requireElement("detail");
  return submitObjective(readCoreUrl(window.location.search), objective)
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
      for (const action of actions) {
        action.disabled = false;
      }
    });
}

async function loadRecovery(coreUrl: string): Promise<RecoveryState | null> {
  try {
    const payload = await fetchJson(coreApiUrl(coreUrl, "/recovery"));
    if (typeof payload !== "object" || payload === null || !("recovery" in payload)) {
      return null;
    }
    return readRecovery(payload.recovery).state;
  } catch {
    return null;
  }
}

async function submitObjective(coreUrl: string, objective: string): Promise<void> {
  const result = listElement("launch-result");
  if (result !== null) {
    result.textContent = "running";
  }
  submittedObjective = objective;
  await fetchJson(coreApiUrl(coreUrl, "/tasks"), fetch, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ objective }),
  });
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
    recoveryState = await loadRecovery(coreUrl);
  } catch (error) {
    recoveryState = null;
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

function desktopViewport(): { width: number; height: number } {
  const desktop = document.getElementById("desktop");
  if (!(desktop instanceof HTMLElement)) {
    return { width: 1280, height: 720 };
  }
  return { width: Math.max(1, desktop.clientWidth), height: Math.max(1, desktop.clientHeight) };
}

function paintWindows(): void {
  const state = compositor.windows;
  const focus = compositor.switcher[0] ?? focusedOnWorkspace(compositor);
  const view = desktopViewport();
  for (const id of WINDOW_IDS) {
    const frame = document.querySelector(`[data-window="${id}"]`);
    const visible = isVisible(compositor, id);
    const onWorkspace = windowWorkspace(compositor, id) === compositor.activeWorkspace;
    if (frame instanceof HTMLElement) {
      frame.hidden = !visible;
      frame.style.zIndex = String(windowZ(state, id));
      frame.classList.toggle("is-focused", id === focus);
      frame.classList.toggle(
        "is-maximized",
        state.maximized.includes(id) && compositor.fullscreen !== id,
      );
      frame.classList.toggle("is-fullscreen", compositor.fullscreen === id);
      const painted = paintedFrame(compositor, id, view);
      if (painted !== null) {
        frame.style.left = `${painted.x}px`;
        frame.style.top = `${painted.y}px`;
        frame.style.width = `${painted.width}px`;
        frame.style.height = `${painted.height}px`;
        frame.style.right = "auto";
      }
    }
    const task = document.querySelector(`[data-task="${id}"]`);
    if (task instanceof HTMLButtonElement) {
      task.hidden = !state.open.includes(id) || !onWorkspace;
      task.setAttribute("aria-pressed", id === focus ? "true" : "false");
    }
    const icon = document.querySelector(`.icons [data-launch="${id}"]`);
    if (icon instanceof HTMLButtonElement) {
      icon.setAttribute("aria-pressed", visible ? "true" : "false");
    }
  }
  document
    .getElementById("desktop")
    ?.classList.toggle("has-fullscreen", compositor.fullscreen !== null);
  paintMonitors(view);
  paintPager();
  paintSwitcher();
  paintToasts();
  const presence = document.getElementById("presence");
  const regions = monitorViews(compositor, view);
  const monitorId =
    focus === null || focus === undefined
      ? compositor.monitors[0]?.id
      : windowMonitor(compositor, focus);
  const region = regions.find((item) => item.id === monitorId) ?? regions[0];
  if (presence instanceof HTMLElement && region !== undefined) {
    presence.style.left = `${region.x + region.width / 2}px`;
    presence.style.top = `${region.y + region.height / 2}px`;
    presence.style.transform = "translate(-50%, -54%)";
  }
  const icons = document.querySelector(".icons");
  const main = regions.find((item) => item.id === "main") ?? regions[0];
  if (icons instanceof HTMLElement && main !== undefined) {
    icons.style.left = `${main.x + 14}px`;
    icons.style.top = `${main.y + 18}px`;
  }
}

function paintMonitors(view: { width: number; height: number }): void {
  const layer = document.getElementById("monitor-layer");
  if (!(layer instanceof HTMLElement)) {
    return;
  }
  layer.replaceChildren();
  for (const monitor of monitorViews(compositor, view)) {
    const region = document.createElement("div");
    region.className = "monitor-region";
    region.style.left = `${monitor.x}px`;
    region.style.top = `${monitor.y}px`;
    region.style.width = `${monitor.width}px`;
    region.style.height = `${monitor.height}px`;
    const label = document.createElement("span");
    label.textContent = monitor.name;
    region.append(label);
    layer.append(region);
  }
}

function paintPager(): void {
  const host = document.getElementById("workspaces");
  if (!(host instanceof HTMLElement)) {
    return;
  }
  host.replaceChildren();
  for (const workspace of compositor.workspaces) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = workspace.name;
    button.setAttribute(
      "aria-pressed",
      workspace.id === compositor.activeWorkspace ? "true" : "false",
    );
    button.addEventListener("click", () => {
      applyCompositor(activateWorkspace(compositor, workspace.id));
    });
    host.append(button);
  }
}

function paintSwitcher(): void {
  const host = document.getElementById("switcher");
  if (!(host instanceof HTMLElement)) {
    return;
  }
  host.hidden = compositor.switcher.length === 0;
  host.replaceChildren();
  for (const id of compositor.switcher) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = WINDOW_TITLES[id];
    button.setAttribute("aria-selected", id === compositor.switcher[0] ? "true" : "false");
    button.addEventListener("click", () => {
      applyCompositor(commitSwitcher({ ...compositor, switcher: [id] }));
    });
    host.append(button);
  }
}

function paintToasts(): void {
  const host = document.getElementById("toasts");
  if (!(host instanceof HTMLElement)) {
    return;
  }
  host.replaceChildren();
  for (const toast of compositor.toasts) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "toast";
    button.textContent = toast.text;
    button.addEventListener("click", () => {
      applyCompositor(dismissToast(compositor, toast.id));
    });
    host.append(button);
  }
}

function applyCompositor(next: CompositorState): void {
  const wasGraph = windowState.open.includes("graph") && !windowState.minimized.includes("graph");
  compositor = next;
  windowState = next.windows;
  paintWindows();
  const graphVisible =
    windowState.open.includes("graph") && !windowState.minimized.includes("graph");
  if (graphVisible && !wasGraph) {
    void refreshGraph(readCoreUrl(window.location.search));
  }
}

function applyWindows(next: WindowState): void {
  applyCompositor(syncWindows(compositor, next));
}

function runDesktopCommand(command: DesktopCommand): void {
  const focus = focusedOnWorkspace(compositor);
  if (command === "switch-next" || command === "switch-previous") {
    applyCompositor(cycleSwitcher(compositor, command === "switch-next" ? 1 : -1));
    return;
  }
  if (command === "fullscreen" && focus !== null) {
    applyCompositor(toggleFullscreen(compositor, focus));
    return;
  }
  if (command === "maximize" && focus !== null) {
    applyWindows(toggleMaximize(windowState, focus));
    return;
  }
  if (command === "minimize" && focus !== null) {
    applyWindows(minimizeWindow(windowState, focus));
    return;
  }
  if (command === "close-window" && focus !== null) {
    applyWindows(closeWindow(windowState, focus));
    return;
  }
  if (command === "workspace-next" || command === "workspace-previous") {
    applyCompositor(cycleWorkspace(compositor, command === "workspace-next" ? 1 : -1));
    return;
  }
  if (
    (command === "window-workspace-next" || command === "window-workspace-previous") &&
    focus !== null
  ) {
    applyCompositor(
      shiftWindowWorkspace(compositor, focus, command === "window-workspace-next" ? 1 : -1),
    );
    return;
  }
  if (command === "monitor-next" && focus !== null) {
    applyCompositor(cycleMonitor(compositor, focus));
  }
}

function bindWindow(id: WindowId): void {
  const frame = document.querySelector(`[data-window="${id}"]`);
  if (!(frame instanceof HTMLElement)) {
    return;
  }
  frame.addEventListener("pointerdown", () => {
    applyWindows(focusWindow(windowState, id));
  });
  const titlebar = frame.querySelector(".titlebar");
  if (titlebar instanceof HTMLElement) {
    titlebar.addEventListener("pointerdown", (event) => {
      if (!(event instanceof PointerEvent)) {
        return;
      }
      if (event.target instanceof Element && event.target.closest("button") !== null) {
        return;
      }
      const start = frameOf(compositor, id);
      const originX = event.clientX;
      const originY = event.clientY;
      titlebar.setPointerCapture(event.pointerId);
      const move = (moveEvent: PointerEvent): void => {
        const delta = logicalDelta(
          viewTransform(compositor.monitors, desktopViewport()),
          moveEvent.clientX - originX,
          moveEvent.clientY - originY,
        );
        applyCompositor(moveFrame(compositor, id, start.x + delta.x, start.y + delta.y));
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
  const handle = frame.querySelector("[data-resize]");
  if (handle instanceof HTMLElement) {
    handle.addEventListener("pointerdown", (event) => {
      if (!(event instanceof PointerEvent) || frame.classList.contains("is-maximized")) {
        return;
      }
      if (frame.classList.contains("is-fullscreen")) {
        return;
      }
      event.stopPropagation();
      const start = frameOf(compositor, id);
      const originX = event.clientX;
      const originY = event.clientY;
      handle.setPointerCapture(event.pointerId);
      const move = (moveEvent: PointerEvent): void => {
        const delta = logicalDelta(
          viewTransform(compositor.monitors, desktopViewport()),
          moveEvent.clientX - originX,
          moveEvent.clientY - originY,
        );
        applyCompositor(resizeFrame(compositor, id, start.width + delta.x, start.height + delta.y));
      };
      const stop = (stopEvent: PointerEvent): void => {
        handle.removeEventListener("pointermove", move);
        handle.removeEventListener("pointerup", stop);
        handle.removeEventListener("pointercancel", stop);
        if (handle.hasPointerCapture(stopEvent.pointerId)) {
          handle.releasePointerCapture(stopEvent.pointerId);
        }
      };
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", stop);
      handle.addEventListener("pointercancel", stop);
    });
  }
  const fullscreen = frame.querySelector("[data-close]");
  if (fullscreen instanceof HTMLElement && frame.querySelector("[data-fullscreen]") === null) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "frame";
    button.dataset["fullscreen"] = id;
    button.setAttribute("aria-label", `Fullscreen ${WINDOW_TITLES[id]}`);
    button.textContent = "⛶";
    fullscreen.before(button);
  }
}

function bindDesktop(): void {
  if (document.getElementById("desktop") === null) {
    return;
  }
  applyCompositor(initialCompositor());
  window.addEventListener("resize", () => {
    paintWindows();
  });
  for (const id of WINDOW_IDS) {
    bindWindow(id);
  }
  document.querySelectorAll("[data-launch]").forEach((node) => {
    node.addEventListener("click", () => {
      const id = node.getAttribute("data-launch");
      if (id !== null && isWindowId(id)) {
        applyWindows(openWindow(windowState, id));
        hideStartMenu();
      }
    });
  });
  document.querySelectorAll("[data-task]").forEach((node) => {
    node.addEventListener("click", () => {
      const id = node.getAttribute("data-task");
      if (id !== null && isWindowId(id)) {
        applyWindows(activateWindow(windowState, id));
      }
    });
  });
  document.querySelectorAll("[data-close]").forEach((node) => {
    node.addEventListener("click", (event) => {
      event.stopPropagation();
      const id = node.getAttribute("data-close");
      if (id !== null && isWindowId(id)) {
        applyWindows(closeWindow(windowState, id));
      }
    });
  });
  document.querySelectorAll("[data-minimize]").forEach((node) => {
    node.addEventListener("click", (event) => {
      event.stopPropagation();
      const id = node.getAttribute("data-minimize");
      if (id !== null && isWindowId(id)) {
        applyWindows(minimizeWindow(windowState, id));
      }
    });
  });
  document.querySelectorAll("[data-maximize]").forEach((node) => {
    node.addEventListener("click", (event) => {
      event.stopPropagation();
      const id = node.getAttribute("data-maximize");
      if (id !== null && isWindowId(id)) {
        applyWindows(toggleMaximize(windowState, id));
      }
    });
  });
  document.querySelectorAll("[data-fullscreen]").forEach((node) => {
    node.addEventListener("click", (event) => {
      event.stopPropagation();
      const id = node.getAttribute("data-fullscreen");
      if (id !== null && isWindowId(id)) {
        applyCompositor(toggleFullscreen(compositor, id));
      }
    });
  });
  const detailButton = document.getElementById("detail-level");
  if (detailButton instanceof HTMLButtonElement) {
    detailButton.addEventListener("click", () => {
      setDetailLevel(cycleDetail(detailLevel));
    });
  }
  const focusGraph = document.getElementById("graph-focus");
  if (focusGraph instanceof HTMLButtonElement) {
    focusGraph.addEventListener("click", () => {
      focusActiveMission();
    });
  }
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
    if (chordMatches(event, inputStatus.activation)) {
      event.preventDefault();
      openCommand();
      return;
    }
    if (chordMatches(event, inputStatus.cancel)) {
      event.preventDefault();
      cancelCommand();
      return;
    }
    if (chordMatches(event, inputStatus.pushToTalk)) {
      event.preventDefault();
      return;
    }
    if (event.key === "Escape") {
      if (compositor.switcher.length > 0) {
        applyCompositor(cancelSwitcher(compositor));
        return;
      }
      if (compositor.fullscreen !== null) {
        applyCompositor(toggleFullscreen(compositor, compositor.fullscreen));
        return;
      }
      hideStartMenu();
      return;
    }
    const desktopCommand = matchDesktopCommand({
      key: event.key,
      metaKey: event.metaKey,
      ctrlKey: event.ctrlKey,
      shiftKey: event.shiftKey,
      altKey: event.altKey,
    });
    if (desktopCommand !== null) {
      event.preventDefault();
      runDesktopCommand(desktopCommand);
      return;
    }
    const shortcut = matchShortcut(event);
    if (shortcut === null) {
      return;
    }
    event.preventDefault();
    if (shortcut.target === "palette") {
      applyWindows(openWindow(windowState, "launcher"));
      const objective = document.getElementById("objective");
      if (objective instanceof HTMLInputElement) {
        objective.focus();
      }
      return;
    }
    if (shortcut.target === "detail") {
      setDetailLevel(cycleDetail(detailLevel));
      return;
    }
    applyWindows(openWindow(windowState, shortcut.target));
  });
  document.addEventListener("keyup", (event) => {
    if ((event.key === "Alt" || event.key === "Meta") && compositor.switcher.length > 0) {
      applyCompositor(commitSwitcher(compositor));
    }
  });
  document.getElementById("desktop")?.addEventListener("pointerdown", (event) => {
    if (!(event.target instanceof Element) || event.target.closest(".window, .icons") !== null) {
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

function setDetailLevel(level: DetailLevel): void {
  detailLevel = level;
  const button = document.getElementById("detail-level");
  if (button instanceof HTMLButtonElement) {
    button.textContent = detailLabel(level);
    button.setAttribute("aria-pressed", level === "normal" ? "false" : "true");
  }
  const coreOk = listElement("tray-status")?.dataset["state"] === "ok";
  paintDesktop(coreOk);
  if (graphLayout !== null) {
    paintGraph();
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

let desktopStarted = false;
let bootFlight = false;
const setupDraft: SetupDraft = {
  name: "",
  color: "dusk",
  type: "interface",
  wallpaper: "dusk",
  password: "",
  confirm: "",
};
let setupStep: SetupStep = "welcome";
let setupWired = false;

function applyTheme(theme: ThemeDocument): void {
  const variables = themeVariables(theme);
  if (variables === null) {
    return;
  }
  for (const [key, value] of Object.entries(variables)) {
    document.documentElement.style.setProperty(key, value);
  }
}

function paintDependencies(step: SetupStep): void {
  const list = document.getElementById("setup-dependencies");
  if (!(list instanceof HTMLElement)) {
    return;
  }
  list.replaceChildren();
  for (const item of stageDependencies(step)) {
    const row = document.createElement("li");
    row.textContent = `${item.state === "staged" ? "Staged" : "Waiting"}  ${item.label}`;
    list.append(row);
  }
}

function paintSetupStep(): void {
  const gate = document.getElementById("boot-gate");
  const setup = document.getElementById("setup-panel");
  const unlock = document.getElementById("unlock-panel");
  const title = document.getElementById("boot-title");
  const copy = document.getElementById("boot-copy");
  const next = document.getElementById("setup-next");
  const back = document.getElementById("setup-back");
  if (
    !(gate instanceof HTMLElement) ||
    !(setup instanceof HTMLElement) ||
    !(unlock instanceof HTMLElement) ||
    !(title instanceof HTMLElement) ||
    !(copy instanceof HTMLElement) ||
    !(next instanceof HTMLButtonElement) ||
    !(back instanceof HTMLButtonElement)
  ) {
    return;
  }
  document.body.dataset["gate"] = "setup";
  gate.hidden = false;
  gate.dataset["surface"] = "setup";
  setup.hidden = false;
  unlock.hidden = true;
  const nameRow = document.getElementById("setup-name-row");
  const look = document.getElementById("setup-look");
  const passwordRow = document.getElementById("setup-password-row");
  if (nameRow instanceof HTMLElement) {
    nameRow.hidden = setupStep !== "name";
  }
  if (look instanceof HTMLElement) {
    look.hidden = setupStep !== "look";
  }
  if (passwordRow instanceof HTMLElement) {
    passwordRow.hidden = setupStep !== "password";
  }
  back.hidden = setupStep === "welcome";
  const titles: Record<SetupStep, [string, string, string]> = {
    welcome: ["Welcome", "Set up OMNE once. Later boots ask only for your password.", "Next"],
    name: ["Your name", "What should OMNE call you?", "Next"],
    look: ["Look", "Choose a color, a type, and a wallpaper.", "Next"],
    password: ["Password", "Choose a password. OMNE stores a hash, not the password.", "Start"],
  };
  const [heading, message, label] = titles[setupStep];
  title.textContent = heading;
  copy.textContent = message;
  next.textContent = label;
  paintDependencies(setupStep);
  applyTheme(themeFromDraft(setupDraft));
  markChoices();
}

function markChoices(): void {
  for (const button of Array.from(document.querySelectorAll("#setup-look button"))) {
    if (!(button instanceof HTMLButtonElement)) {
      continue;
    }
    const group = button.dataset["group"];
    const value = button.dataset["value"];
    const selected =
      (group === "color" && value === setupDraft.color) ||
      (group === "type" && value === setupDraft.type) ||
      (group === "wallpaper" && value === setupDraft.wallpaper);
    button.setAttribute("aria-pressed", selected ? "true" : "false");
  }
}

function showPasswordGate(name: string): void {
  const gate = document.getElementById("boot-gate");
  const setup = document.getElementById("setup-panel");
  const unlock = document.getElementById("unlock-panel");
  const title = document.getElementById("boot-title");
  const copy = document.getElementById("boot-copy");
  if (
    !(gate instanceof HTMLElement) ||
    !(setup instanceof HTMLElement) ||
    !(unlock instanceof HTMLElement) ||
    !(title instanceof HTMLElement) ||
    !(copy instanceof HTMLElement)
  ) {
    return;
  }
  document.body.dataset["gate"] = "password";
  gate.hidden = false;
  gate.dataset["surface"] = "password";
  setup.hidden = true;
  unlock.hidden = false;
  title.textContent = name.trim() === "" ? "Unlock" : name.trim();
  copy.textContent = "Enter your password to unlock OMNE.";
  const error = document.getElementById("unlock-error");
  if (error instanceof HTMLElement) {
    error.textContent = "";
  }
}

function revealDesktop(coreUrl: string): void {
  const gate = document.getElementById("boot-gate");
  if (gate instanceof HTMLElement) {
    gate.hidden = true;
    gate.dataset["surface"] = "desktop";
  }
  document.body.dataset["gate"] = "open";
  document.getElementById("desktop")?.removeAttribute("inert");
  document.querySelector(".taskbar")?.removeAttribute("inert");
  startDesktop(coreUrl);
}

function readDraftFields(): void {
  const name = document.getElementById("setup-name");
  const password = document.getElementById("setup-password");
  const confirm = document.getElementById("setup-confirm");
  if (name instanceof HTMLInputElement) {
    setupDraft.name = name.value;
  }
  if (password instanceof HTMLInputElement) {
    setupDraft.password = password.value;
  }
  if (confirm instanceof HTMLInputElement) {
    setupDraft.confirm = confirm.value;
  }
}

function wireSetup(coreUrl: string): void {
  if (setupWired) {
    return;
  }
  setupWired = true;
  fillChoices("setup-colors", "color", COLOR_PRESETS);
  fillChoices("setup-types", "type", TYPE_PRESETS);
  fillChoices("setup-wallpapers", "wallpaper", WALLPAPER_PRESETS);
  document.getElementById("setup-next")?.addEventListener("click", () => {
    readDraftFields();
    const result = nextSetupStep(setupStep, setupDraft);
    const error = document.getElementById("setup-error");
    if (error instanceof HTMLElement) {
      error.textContent = result.error ?? "";
    }
    if (result.error !== null) {
      return;
    }
    if (result.step === "finish") {
      void finishSetup(coreUrl);
      return;
    }
    setupStep = result.step;
    paintSetupStep();
  });
  document.getElementById("setup-back")?.addEventListener("click", () => {
    readDraftFields();
    setupStep = previousSetupStep(setupStep);
    const error = document.getElementById("setup-error");
    if (error instanceof HTMLElement) {
      error.textContent = "";
    }
    paintSetupStep();
  });
  document.getElementById("unlock-panel")?.addEventListener("submit", (event) => {
    event.preventDefault();
    void submitPassword(coreUrl);
  });
}

function fillChoices(
  id: string,
  group: "color" | "type" | "wallpaper",
  choices: readonly { id: string; label: string }[],
): void {
  const host = document.getElementById(id);
  if (!(host instanceof HTMLElement)) {
    return;
  }
  host.replaceChildren();
  for (const choice of choices) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = choice.label;
    button.dataset["group"] = group;
    button.dataset["value"] = choice.id;
    button.addEventListener("click", () => {
      setupDraft[group] = choice.id;
      applyTheme(themeFromDraft(setupDraft));
      markChoices();
    });
    host.append(button);
  }
}

async function finishSetup(coreUrl: string): Promise<void> {
  const next = document.getElementById("setup-next");
  if (next instanceof HTMLButtonElement) {
    next.disabled = true;
  }
  const error = document.getElementById("setup-error");
  try {
    const result = await postJson(coreApiUrl(coreUrl, "/setup"), {
      name: setupDraft.name.trim(),
      password: setupDraft.password,
      confirm: setupDraft.confirm,
      theme: themeFromDraft(setupDraft),
    });
    if (result.status === 200) {
      const theme = readTheme(isThemePayload(result.body) ? result.body["theme"] : null);
      if (theme !== null) {
        applyTheme(theme);
      }
      revealDesktop(coreUrl);
      return;
    }
    if (result.status === 409) {
      showPasswordGate(setupDraft.name);
      return;
    }
    if (error instanceof HTMLElement) {
      error.textContent = "Setup was not saved.";
    }
  } catch (caught) {
    if (error instanceof HTMLElement) {
      error.textContent = caught instanceof Error ? caught.message : "Setup was not saved.";
    }
  } finally {
    if (next instanceof HTMLButtonElement) {
      next.disabled = false;
    }
  }
}

async function submitPassword(coreUrl: string): Promise<void> {
  const field = document.getElementById("unlock-password");
  const error = document.getElementById("unlock-error");
  const password = field instanceof HTMLInputElement ? field.value : "";
  try {
    const result = await postJson(coreApiUrl(coreUrl, "/unlock"), { password });
    const unlocked =
      result.status === 200 && isRecord(result.body) && result.body["unlocked"] === true;
    if (surfaceAfterUnlock(unlocked) === "desktop") {
      revealDesktop(coreUrl);
      return;
    }
    if (error instanceof HTMLElement) {
      error.textContent = "That password does not unlock OMNE.";
    }
    if (field instanceof HTMLInputElement) {
      field.select();
    }
  } catch (caught) {
    if (error instanceof HTMLElement) {
      error.textContent = caught instanceof Error ? caught.message : "OMNE did not answer.";
    }
  }
}

function isThemePayload(value: unknown): value is Record<string, unknown> {
  return isRecord(value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

async function enterShell(coreUrl: string): Promise<void> {
  if (bootFlight || desktopStarted) {
    return;
  }
  bootFlight = true;
  let settled = false;
  try {
    const payload = await fetchJson(coreApiUrl(coreUrl, "/setup"));
    const view = readSetup(payload);
    const theme = readTheme(isRecord(payload) ? payload["theme"] : null);
    if (theme !== null) {
      applyTheme(theme);
    }
    const surface = bootSurface(view);
    if (surface === "hold") {
      return;
    }
    wireSetup(coreUrl);
    if (surface === "password") {
      showPasswordGate(view?.name ?? "");
    } else {
      setupStep = "welcome";
      paintSetupStep();
    }
    settled = true;
  } catch {
    const copy = document.getElementById("boot-copy");
    if (copy instanceof HTMLElement && document.body.dataset["gate"] !== "setup") {
      copy.textContent = "Waiting for OMNE.";
    }
  } finally {
    bootFlight = false;
  }
  if (!settled && !desktopStarted) {
    window.setTimeout(() => {
      void enterShell(coreUrl);
    }, 800);
  }
}

function startDesktop(coreUrl: string): void {
  if (desktopStarted) {
    return;
  }
  desktopStarted = true;
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
        void runObjective(text);
      });
    }
    paintLauncherActions();
    const listen = document.getElementById("voice-listen");
    if (listen instanceof HTMLButtonElement) {
      listen.disabled = true;
    }
    bindDesktop();
    paintHud();
    void refresh(status, detail);
    void refreshCompute(coreUrl);
    void refreshNetwork(coreUrl);
    void refreshAudio(coreUrl);
    void refreshInput(coreUrl);
    void refreshApplications(coreUrl);
    window.setInterval(() => {
      void refresh(status, detail);
      void refreshGraph(coreUrl);
    }, 2000);
    window.setInterval(() => {
      void refreshCompute(coreUrl);
      void refreshNetwork(coreUrl);
      void refreshAudio(coreUrl);
      void refreshInput(coreUrl);
      void refreshApplications(coreUrl);
    }, 4000);
  } catch (error) {
    console.error(error);
  }
}

function bootstrap(): void {
  const coreUrl = readCoreUrl(window.location.search);
  void enterShell(coreUrl);
}

if (typeof document !== "undefined") {
  bootstrap();
}
