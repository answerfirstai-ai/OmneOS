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
] as const;

export type WindowId = (typeof WINDOW_IDS)[number];

export interface WindowState {
  open: readonly WindowId[];
  order: readonly WindowId[];
}

export function isWindowId(value: string): value is WindowId {
  return (WINDOW_IDS as readonly string[]).includes(value);
}

/** Launcher and tasks start open. Core stays available from the menu. */
export function initialWindowState(): WindowState {
  return {
    open: ["launcher", "tasks"],
    order: ["core", "launcher", "tasks"],
  };
}

export function focusedWindow(state: WindowState): WindowId | null {
  for (let index = state.order.length - 1; index >= 0; index -= 1) {
    const id = state.order[index];
    if (id !== undefined && state.open.includes(id)) {
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
  return focusWindow({ open, order: state.order }, id);
}

export function focusWindow(state: WindowState, id: WindowId): WindowState {
  if (!state.open.includes(id)) {
    return state;
  }
  return {
    open: state.open,
    order: [...state.order.filter((item) => item !== id), id],
  };
}

export function closeWindow(state: WindowState, id: WindowId): WindowState {
  const open = state.open.filter((item) => item !== id);
  const order = state.order.filter((item) => item !== id);
  const focus = [...order].reverse().find((item) => open.includes(item));
  return {
    open,
    order: focus === undefined ? order : [...order.filter((item) => item !== focus), focus],
  };
}

/** Open a window, or hide it when it is already the one in front. */
export function activateWindow(state: WindowState, id: WindowId): WindowState {
  if (focusedWindow(state) === id) {
    return closeWindow(state, id);
  }
  return openWindow(state, id);
}
