/** The shell's desktop compositor.

labwc is not commanded from here. These are the windows the OMNE desktop draws:
move, resize, minimize, maximize, fullscreen, monitors, workspaces, focus, and
the app switcher.
*/

import {
  focusWindow,
  focusedWindow,
  initialWindowState,
  clampSize,
  type WindowId,
  type WindowState,
  WINDOW_IDS,
} from "./windows.js";

export interface Monitor {
  id: string;
  name: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface Workspace {
  id: string;
  name: string;
}

export interface Frame {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface Placement {
  workspaceId: string;
  monitorId: string;
}

export interface Toast {
  id: string;
  text: string;
}

export interface CompositorState {
  windows: WindowState;
  frames: Partial<Record<WindowId, Frame>>;
  placement: Partial<Record<WindowId, Placement>>;
  monitors: readonly Monitor[];
  workspaces: readonly Workspace[];
  activeWorkspace: string;
  fullscreen: WindowId | null;
  switcher: readonly WindowId[];
  toasts: readonly Toast[];
  shown: readonly string[];
}

export interface ViewBox {
  width: number;
  height: number;
}

export interface Transform {
  scale: number;
  offsetX: number;
  offsetY: number;
  originX: number;
  originY: number;
}

export interface Painted {
  x: number;
  y: number;
  width: number;
  height: number;
}

export const WINDOW_TITLES: Record<WindowId, string> = {
  core: "Core",
  launcher: "OMNE",
  tasks: "Tasks",
  agents: "Agents",
  models: "Models",
  notifications: "Notices",
  voice: "Voice",
  missions: "Missions",
  workers: "Workers",
  graph: "System",
  projects: "Project",
};

const MAIN: Monitor = { id: "main", name: "Main", x: 0, y: 0, width: 1600, height: 900 };
const SIDE: Monitor = { id: "side", name: "Side", x: 1600, y: 0, width: 1280, height: 900 };

const PLACED: Record<WindowId, Frame> = {
  core: { x: 96, y: 56, width: 420, height: 360 },
  launcher: { x: 120, y: 64, width: 440, height: 560 },
  tasks: { x: 860, y: 64, width: 400, height: 320 },
  agents: { x: 220, y: 140, width: 420, height: 360 },
  models: { x: 520, y: 160, width: 420, height: 360 },
  notifications: { x: 1680, y: 80, width: 420, height: 320 },
  voice: { x: 640, y: 220, width: 420, height: 280 },
  missions: { x: 400, y: 96, width: 480, height: 400 },
  workers: { x: 480, y: 240, width: 420, height: 360 },
  graph: { x: 240, y: 48, width: 640, height: 460 },
  projects: { x: 360, y: 180, width: 420, height: 360 },
};

/** Two outputs and two workspaces. Notices start on the side display. */
export function initialCompositor(): CompositorState {
  const placement: Partial<Record<WindowId, Placement>> = {};
  for (const id of WINDOW_IDS) {
    placement[id] = {
      workspaceId: "one",
      monitorId: id === "notifications" ? "side" : "main",
    };
  }
  return {
    windows: initialWindowState(),
    frames: { ...PLACED },
    placement,
    monitors: [MAIN, SIDE],
    workspaces: [
      { id: "one", name: "Desktop" },
      { id: "two", name: "Work" },
    ],
    activeWorkspace: "one",
    fullscreen: null,
    switcher: [],
    toasts: [],
    shown: [],
  };
}

export function frameOf(state: CompositorState, id: WindowId): Frame {
  return state.frames[id] ?? PLACED[id];
}

export function windowWorkspace(state: CompositorState, id: WindowId): string {
  return state.placement[id]?.workspaceId ?? state.workspaces[0]?.id ?? "one";
}

export function windowMonitor(state: CompositorState, id: WindowId): string {
  return state.placement[id]?.monitorId ?? state.monitors[0]?.id ?? "main";
}

export function isVisible(state: CompositorState, id: WindowId): boolean {
  return (
    state.windows.open.includes(id) &&
    !state.windows.minimized.includes(id) &&
    windowWorkspace(state, id) === state.activeWorkspace
  );
}

/** The front window on the workspace that is showing. */
export function focusedOnWorkspace(state: CompositorState): WindowId | null {
  for (let index = state.windows.order.length - 1; index >= 0; index -= 1) {
    const id = state.windows.order[index];
    if (id !== undefined && isVisible(state, id)) {
      return id;
    }
  }
  return null;
}

export function union(monitors: readonly Monitor[]): {
  x: number;
  y: number;
  width: number;
  height: number;
} {
  const first = monitors[0];
  if (first === undefined) {
    return { x: 0, y: 0, width: 1, height: 1 };
  }
  const minX = Math.min(...monitors.map((monitor) => monitor.x));
  const minY = Math.min(...monitors.map((monitor) => monitor.y));
  const maxX = Math.max(...monitors.map((monitor) => monitor.x + monitor.width));
  const maxY = Math.max(...monitors.map((monitor) => monitor.y + monitor.height));
  return { x: minX, y: minY, width: Math.max(1, maxX - minX), height: Math.max(1, maxY - minY) };
}

export function viewTransform(monitors: readonly Monitor[], view: ViewBox): Transform {
  const box = union(monitors);
  const scale = Math.min(view.width / box.width, view.height / box.height);
  return {
    scale: scale === 0 ? 1 : scale,
    offsetX: (view.width - box.width * scale) / 2,
    offsetY: (view.height - box.height * scale) / 2,
    originX: box.x,
    originY: box.y,
  };
}

export function toView(transform: Transform, frame: Frame): Painted {
  return {
    x: transform.offsetX + (frame.x - transform.originX) * transform.scale,
    y: transform.offsetY + (frame.y - transform.originY) * transform.scale,
    width: frame.width * transform.scale,
    height: frame.height * transform.scale,
  };
}

export function logicalDelta(
  transform: Transform,
  dx: number,
  dy: number,
): { x: number; y: number } {
  return { x: dx / transform.scale, y: dy / transform.scale };
}

export function paintedFrame(state: CompositorState, id: WindowId, view: ViewBox): Painted | null {
  if (!isVisible(state, id)) {
    return null;
  }
  const transform = viewTransform(state.monitors, view);
  const monitor = monitorById(state, windowMonitor(state, id));
  if (state.fullscreen === id && monitor !== null) {
    return toView(transform, {
      x: monitor.x,
      y: monitor.y,
      width: monitor.width,
      height: monitor.height,
    });
  }
  if (state.windows.maximized.includes(id) && monitor !== null) {
    return toView(transform, {
      x: monitor.x + 8,
      y: monitor.y + 8,
      width: Math.max(280, monitor.width - 16),
      height: Math.max(160, monitor.height - 16),
    });
  }
  return toView(transform, frameOf(state, id));
}

/** Keep a window's title inside the outputs, and record which output holds its center. */
export function moveFrame(
  state: CompositorState,
  id: WindowId,
  x: number,
  y: number,
): CompositorState {
  if (!state.windows.open.includes(id)) {
    return state;
  }
  const frame = frameOf(state, id);
  const box = union(state.monitors);
  const nextX = Math.min(box.x + box.width - 72, Math.max(box.x - frame.width + 72, x));
  const nextY = Math.min(box.y + box.height - 36, Math.max(box.y, y));
  const centerX = nextX + frame.width / 2;
  const centerY = nextY + Math.min(frame.height / 2, 24);
  const monitor = monitorAt(state.monitors, centerX, centerY) ?? state.monitors[0];
  return {
    ...state,
    fullscreen: state.fullscreen === id ? null : state.fullscreen,
    windows: focusWindow(
      {
        ...state.windows,
        maximized: state.windows.maximized.filter((item) => item !== id),
      },
      id,
    ),
    frames: { ...state.frames, [id]: { ...frame, x: nextX, y: nextY } },
    placement: monitor
      ? {
          ...state.placement,
          [id]: { workspaceId: windowWorkspace(state, id), monitorId: monitor.id },
        }
      : state.placement,
  };
}

export function resizeFrame(
  state: CompositorState,
  id: WindowId,
  width: number,
  height: number,
): CompositorState {
  if (!state.windows.open.includes(id)) {
    return state;
  }
  const monitor = monitorById(state, windowMonitor(state, id));
  const limit = monitor ?? union(state.monitors);
  const size = clampSize(width, height, {
    minWidth: 280,
    minHeight: 160,
    maxWidth: Math.max(280, limit.width),
    maxHeight: Math.max(160, limit.height),
  });
  const frame = frameOf(state, id);
  return {
    ...state,
    fullscreen: state.fullscreen === id ? null : state.fullscreen,
    windows: {
      ...state.windows,
      maximized: state.windows.maximized.filter((item) => item !== id),
    },
    frames: { ...state.frames, [id]: { ...frame, width: size.width, height: size.height } },
  };
}

export function toggleFullscreen(state: CompositorState, id: WindowId): CompositorState {
  if (!state.windows.open.includes(id)) {
    return state;
  }
  if (state.fullscreen === id) {
    return { ...state, fullscreen: null, windows: focusWindow(state.windows, id) };
  }
  return {
    ...state,
    fullscreen: id,
    windows: focusWindow(
      {
        ...state.windows,
        minimized: state.windows.minimized.filter((item) => item !== id),
        maximized: state.windows.maximized.filter((item) => item !== id),
      },
      id,
    ),
  };
}

export function activateWorkspace(state: CompositorState, workspaceId: string): CompositorState {
  if (!state.workspaces.some((workspace) => workspace.id === workspaceId)) {
    return state;
  }
  const next: CompositorState = { ...state, activeWorkspace: workspaceId, switcher: [] };
  const fullscreenHere =
    next.fullscreen !== null && windowWorkspace(next, next.fullscreen) === workspaceId;
  const cleared = { ...next, fullscreen: fullscreenHere ? next.fullscreen : null };
  const focus = focusedOnWorkspace(cleared);
  if (focus === null) {
    return cleared;
  }
  return { ...cleared, windows: focusWindow(cleared.windows, focus) };
}

export function cycleWorkspace(state: CompositorState, direction: 1 | -1): CompositorState {
  const index = state.workspaces.findIndex((workspace) => workspace.id === state.activeWorkspace);
  const count = state.workspaces.length;
  if (count === 0 || index < 0) {
    return state;
  }
  const next = state.workspaces[(index + direction + count) % count];
  return next === undefined ? state : activateWorkspace(state, next.id);
}

export function moveToWorkspace(
  state: CompositorState,
  id: WindowId,
  workspaceId: string,
): CompositorState {
  if (!state.windows.open.includes(id)) {
    return state;
  }
  if (!state.workspaces.some((workspace) => workspace.id === workspaceId)) {
    return state;
  }
  return {
    ...state,
    fullscreen: state.fullscreen === id ? null : state.fullscreen,
    placement: {
      ...state.placement,
      [id]: { workspaceId, monitorId: windowMonitor(state, id) },
    },
  };
}

/** Move a window to another workspace and follow it. */
export function shiftWindowWorkspace(
  state: CompositorState,
  id: WindowId,
  direction: 1 | -1,
): CompositorState {
  const index = state.workspaces.findIndex(
    (workspace) => workspace.id === windowWorkspace(state, id),
  );
  const count = state.workspaces.length;
  const next = state.workspaces[(index + direction + count) % count];
  if (next === undefined) {
    return state;
  }
  return activateWorkspace(moveToWorkspace(state, id, next.id), next.id);
}

export function moveToMonitor(
  state: CompositorState,
  id: WindowId,
  monitorId: string,
): CompositorState {
  const monitor = monitorById(state, monitorId);
  if (monitor === null || !state.windows.open.includes(id)) {
    return state;
  }
  const moved = moveFrame(state, id, monitor.x + 24, monitor.y + 24);
  return {
    ...moved,
    placement: {
      ...moved.placement,
      [id]: { workspaceId: windowWorkspace(state, id), monitorId: monitor.id },
    },
  };
}

export function cycleMonitor(state: CompositorState, id: WindowId): CompositorState {
  if (state.monitors.length < 2) {
    return state;
  }
  const ids = state.monitors.map((monitor) => monitor.id);
  const index = ids.indexOf(windowMonitor(state, id));
  const next = ids[(index + 1) % ids.length];
  return next === undefined ? state : moveToMonitor(state, id, next);
}

export function cycleSwitcher(state: CompositorState, direction: 1 | -1): CompositorState {
  const order = switcherOrder(state);
  if (order.length === 0) {
    return state;
  }
  if (state.switcher.length === 0) {
    const start = direction === 1 ? (order[1] ?? order[0]) : order[order.length - 1];
    return start === undefined ? state : { ...state, switcher: arrange(order, start) };
  }
  const current = state.switcher[0] ?? order[0];
  const index = Math.max(0, order.indexOf(current ?? order[0] ?? "tasks"));
  const next = order[(index + direction + order.length) % order.length];
  return next === undefined ? state : { ...state, switcher: arrange(order, next) };
}

export function commitSwitcher(state: CompositorState): CompositorState {
  const id = state.switcher[0];
  if (id === undefined) {
    return { ...state, switcher: [] };
  }
  return { ...state, switcher: [], windows: focusWindow(state.windows, id) };
}

export function cancelSwitcher(state: CompositorState): CompositorState {
  return state.switcher.length === 0 ? state : { ...state, switcher: [] };
}

export function publishToasts(state: CompositorState, incoming: readonly Toast[]): CompositorState {
  const fresh = incoming.filter((toast) => !state.shown.includes(toast.id) && toast.text !== "");
  if (fresh.length === 0) {
    return state;
  }
  return {
    ...state,
    shown: [...state.shown, ...fresh.map((toast) => toast.id)].slice(-40),
    toasts: [...fresh, ...state.toasts].slice(0, 4),
  };
}

export function dismissToast(state: CompositorState, id: string): CompositorState {
  return { ...state, toasts: state.toasts.filter((toast) => toast.id !== id) };
}

/** Carry geometry when the open/focus set changes. Drop fullscreen if that window is gone. */
export function syncWindows(state: CompositorState, windows: WindowState): CompositorState {
  const fullscreen =
    state.fullscreen !== null &&
    windows.open.includes(state.fullscreen) &&
    !windows.minimized.includes(state.fullscreen)
      ? state.fullscreen
      : null;
  return { ...state, windows, fullscreen };
}

export function monitorViews(
  state: CompositorState,
  view: ViewBox,
): { id: string; name: string; x: number; y: number; width: number; height: number }[] {
  const transform = viewTransform(state.monitors, view);
  return state.monitors.map((monitor) => ({
    id: monitor.id,
    name: monitor.name,
    ...toView(transform, monitor),
  }));
}

function switcherOrder(state: CompositorState): WindowId[] {
  const front = [...state.windows.order].reverse();
  return front.filter(
    (id) => state.windows.open.includes(id) && windowWorkspace(state, id) === state.activeWorkspace,
  );
}

function arrange(order: readonly WindowId[], first: WindowId): WindowId[] {
  return [first, ...order.filter((id) => id !== first)];
}

function monitorById(state: CompositorState, id: string): Monitor | null {
  return state.monitors.find((monitor) => monitor.id === id) ?? null;
}

function monitorAt(monitors: readonly Monitor[], x: number, y: number): Monitor | null {
  return (
    monitors.find(
      (monitor) =>
        x >= monitor.x &&
        y >= monitor.y &&
        x < monitor.x + monitor.width &&
        y < monitor.y + monitor.height,
    ) ?? null
  );
}

export function focusedWindowId(state: CompositorState): WindowId | null {
  return focusedWindow(state.windows);
}
