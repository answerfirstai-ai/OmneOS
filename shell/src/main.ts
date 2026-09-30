import { coreApiUrl, fetchJson } from "./api.js";
import {
  activeMission,
  agentLine,
  attentionLine,
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
import { readNetworkStatus, type NetworkStatusView } from "./network-status.js";
import { coreHealthUrl, parseHealth, type CoreHealth } from "./health.js";
import { inspectMission } from "./mission-view.js";
import { noticesFromEvents } from "./notify.js";
import { permissionPrompt } from "./permission-view.js";
import { coreRenderer, presenceView } from "./presence.js";
import { matchShortcut } from "./shortcuts.js";
import { voiceControlEnabled, voiceSummary, type VoiceStatus } from "./voice.js";
import {
  activateWindow,
  clampSize,
  closeWindow,
  focusedWindow,
  focusWindow,
  initialWindowState,
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

let windowState: WindowState = initialWindowState();
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

function paintPresence(coreOk: boolean): void {
  const host = listElement("presence");
  const tray = listElement("character");
  if (desktopView === null) {
    const view = presenceView({ coreOk, voiceListening: false, statuses: [] });
    if (host !== null) {
      coreRenderer.render(host, view);
    }
    if (tray !== null) {
      tray.dataset["state"] = view.state;
      tray.textContent = view.label;
    }
    return;
  }
  const missions = desktopView.missions.map((mission) => mission.status);
  const latest = desktopView.events[desktopView.events.length - 1];
  const view = presenceView({
    coreOk,
    voiceListening: desktopView.voice.listening,
    statuses: parentTasks(desktopView.tasks).map((task) => task.status),
    ...(missions.length > 0 ? { missionStatuses: missions } : {}),
    ...(latest === undefined ? {} : { latestEvent: latest.type }),
  });
  if (host !== null) {
    coreRenderer.render(host, view);
  }
  if (tray !== null) {
    tray.dataset["state"] = view.state;
    tray.textContent = view.label;
  }
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
    .join(",")}\n${board.idle.map((worker) => worker.id).join(",")}`;
  if (!shouldRepaint(element.dataset["rendered"] ?? null, rendered)) {
    return;
  }
  element.dataset["rendered"] = rendered;
  element.replaceChildren();
  element.append(heading("Agents"));
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
    return `${agent.name} ${agent.state}`;
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
  if (inspection.question !== null) {
    detail.append(heading("OMNE needs clarification"));
    const question = document.createElement("p");
    question.textContent = inspection.question;
    detail.append(question);
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
  element.append(heading("Active workers"));
  element.append(
    linesOrEmpty(
      board.active.map((worker) => workerBoardLine(worker)),
      "No active workers",
    ),
  );
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
  const rendered = `${detailLevel}\n${JSON.stringify(beats)}`;
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
    const minimized = state.minimized.includes(id);
    const open = state.open.includes(id);
    if (frame instanceof HTMLElement) {
      frame.hidden = !open || minimized;
      frame.style.zIndex = String(windowZ(state, id));
      frame.classList.toggle("is-focused", id === focus);
      frame.classList.toggle("is-maximized", state.maximized.includes(id) && !minimized);
    }
    const task = document.querySelector(`[data-task="${id}"]`);
    if (task instanceof HTMLButtonElement) {
      task.hidden = !open;
      task.setAttribute("aria-pressed", id === focus ? "true" : "false");
    }
    const icon = document.querySelector(`.icons [data-launch="${id}"]`);
    if (icon instanceof HTMLButtonElement) {
      icon.setAttribute("aria-pressed", open ? "true" : "false");
    }
  }
}

function applyWindows(next: WindowState): void {
  const wasGraph = windowState.open.includes("graph") && !windowState.minimized.includes("graph");
  windowState = next;
  paintWindows(windowState);
  const graphVisible =
    windowState.open.includes("graph") && !windowState.minimized.includes("graph");
  if (graphVisible && !wasGraph) {
    void refreshGraph(readCoreUrl(window.location.search));
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
      if (!(event instanceof PointerEvent) || frame.classList.contains("is-maximized")) {
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
  const handle = frame.querySelector("[data-resize]");
  if (handle instanceof HTMLElement) {
    handle.addEventListener("pointerdown", (event) => {
      if (!(event instanceof PointerEvent) || frame.classList.contains("is-maximized")) {
        return;
      }
      event.stopPropagation();
      const bounds = frame.getBoundingClientRect();
      const originX = event.clientX;
      const originY = event.clientY;
      handle.setPointerCapture(event.pointerId);
      const move = (moveEvent: PointerEvent): void => {
        const size = clampSize(
          bounds.width + moveEvent.clientX - originX,
          bounds.height + moveEvent.clientY - originY,
          {
            minWidth: 280,
            minHeight: 160,
            maxWidth: Math.max(280, window.innerWidth - 96),
            maxHeight: Math.max(160, window.innerHeight - 96),
          },
        );
        frame.style.width = `${size.width}px`;
        frame.style.height = `${size.height}px`;
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
}

function bindDesktop(): void {
  if (document.getElementById("desktop") === null) {
    return;
  }
  applyWindows(initialWindowState());
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
    if (event.key === "Escape") {
      hideStartMenu();
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
    paintHud();
    const coreUrl = readCoreUrl(window.location.search);
    void refresh(status, detail);
    void refreshCompute(coreUrl);
    void refreshNetwork(coreUrl);
    void refreshAudio(coreUrl);
    window.setInterval(() => {
      void refresh(status, detail);
      void refreshGraph(coreUrl);
    }, 2000);
    window.setInterval(() => {
      void refreshCompute(coreUrl);
      void refreshNetwork(coreUrl);
      void refreshAudio(coreUrl);
    }, 4000);
  } catch (error) {
    console.error(error);
  }
}

if (typeof document !== "undefined") {
  bootstrap();
}
