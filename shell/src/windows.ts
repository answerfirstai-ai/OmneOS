/** Which desktop windows are open, and which one is in front. */

export const WINDOW_IDS = [
  "core",
  "launcher",
  "tasks",
  "agents",
  "models",
  "notifications",
  "voice",
  "missions",
  "workers",
  "graph",
  "projects",
] as const;

export type WindowId = (typeof WINDOW_IDS)[number];

export interface WindowState {
  open: readonly WindowId[];
  order: readonly WindowId[];
  minimized: readonly WindowId[];
  maximized: readonly WindowId[];
}

export interface SizeBounds {
  minWidth: number;
  minHeight: number;
  maxWidth: number;
  maxHeight: number;
}

export function isWindowId(value: string): value is WindowId {
  return (WINDOW_IDS as readonly string[]).includes(value);
}

/** Launcher and tasks start open. Core stays available from the menu. */
export function initialWindowState(): WindowState {
  return {
    open: ["launcher", "tasks"],
    order: ["core", "launcher", "tasks"],
    minimized: [],
    maximized: [],
  };
}

/** Keep a window inside the usable desktop. */
export function clampSize(
  width: number,
  height: number,
  bounds: SizeBounds,
): { width: number; height: number } {
  return {
    width: Math.min(bounds.maxWidth, Math.max(bounds.minWidth, width)),
    height: Math.min(bounds.maxHeight, Math.max(bounds.minHeight, height)),
  };
}

export function focusedWindow(state: WindowState): WindowId | null {
  for (let index = state.order.length - 1; index >= 0; index -= 1) {
    const id = state.order[index];
    if (id !== undefined && state.open.includes(id) && !state.minimized.includes(id)) {
      return id;
    }
  }
  return null;
}

export function windowZ(state: WindowState, id: WindowId): number {
  const index = state.order.indexOf(id);
  return index === -1 ? 1 : index + 1;
}

export function openWindow(state: WindowState, id: WindowId): WindowState {
  const open = state.open.includes(id) ? state.open : [...state.open, id];
  return focusWindow({ ...state, open }, id);
}

export function focusWindow(state: WindowState, id: WindowId): WindowState {
  if (!state.open.includes(id)) {
    return state;
  }
  return {
    open: state.open,
    minimized: state.minimized.filter((item) => item !== id),
    maximized: state.maximized,
    order: [...state.order.filter((item) => item !== id), id],
  };
}

export function closeWindow(state: WindowState, id: WindowId): WindowState {
  const open = state.open.filter((item) => item !== id);
  const order = state.order.filter((item) => item !== id);
  const minimized = state.minimized.filter((item) => item !== id);
  const maximized = state.maximized.filter((item) => item !== id);
  const focus = [...order]
    .reverse()
    .find((item) => open.includes(item) && !minimized.includes(item));
  return {
    open,
    minimized,
    maximized,
    order: focus === undefined ? order : [...order.filter((item) => item !== focus), focus],
  };
}

/** Keep the window on the taskbar and reveal the next visible window. */
export function minimizeWindow(state: WindowState, id: WindowId): WindowState {
  if (!state.open.includes(id) || state.minimized.includes(id)) {
    return state;
  }
  const next: WindowState = {
    open: state.open,
    order: state.order,
    minimized: [...state.minimized, id],
    maximized: state.maximized.filter((item) => item !== id),
  };
  const focus = focusedWindow(next);
  return focus === null ? next : focusWindow(next, focus);
}

export function toggleMaximize(state: WindowState, id: WindowId): WindowState {
  if (!state.open.includes(id)) {
    return state;
  }
  const maximized = state.maximized.includes(id)
    ? state.maximized.filter((item) => item !== id)
    : [...state.maximized, id];
  return focusWindow(
    {
      ...state,
      minimized: state.minimized.filter((item) => item !== id),
      maximized,
    },
    id,
  );
}

/** Open a window, or hide it when it is already the one in front. */
export function activateWindow(state: WindowState, id: WindowId): WindowState {
  if (state.minimized.includes(id)) {
    return focusWindow(state, id);
  }
  if (focusedWindow(state) === id) {
    return closeWindow(state, id);
  }
  return openWindow(state, id);
}
