/** Global desktop shortcuts. The command palette is the primary entry. */

import type { WindowId } from "./windows.js";

export type ShortcutTarget = WindowId | "palette" | "detail";

export interface Shortcut {
  target: ShortcutTarget;
  key: string;
  shift: boolean;
}

export interface ShortcutEvent {
  key: string;
  metaKey: boolean;
  ctrlKey: boolean;
  shiftKey: boolean;
  altKey: boolean;
}

export const SHORTCUTS: readonly Shortcut[] = [
  { target: "palette", key: " ", shift: false },
  { target: "missions", key: "m", shift: true },
  { target: "workers", key: "w", shift: true },
  { target: "agents", key: "a", shift: true },
  { target: "models", key: "l", shift: true },
  { target: "notifications", key: "n", shift: true },
  { target: "graph", key: "g", shift: true },
  { target: "core", key: "s", shift: true },
  { target: "projects", key: "p", shift: true },
  { target: "detail", key: ".", shift: true },
];

export type DesktopCommand =
  | "switch-next"
  | "switch-previous"
  | "fullscreen"
  | "maximize"
  | "minimize"
  | "close-window"
  | "workspace-next"
  | "workspace-previous"
  | "window-workspace-next"
  | "window-workspace-previous"
  | "monitor-next";

/** Match Ctrl/Command shortcuts. Plain typing does not open a window. */
export function matchShortcut(event: ShortcutEvent): Shortcut | null {
  const mod = event.metaKey || event.ctrlKey;
  if (!mod || event.altKey) {
    return null;
  }
  const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
  return (
    SHORTCUTS.find((shortcut) => shortcut.key === key && shortcut.shift === event.shiftKey) ?? null
  );
}

/** Window-manager chords. These stay separate from the command palette. */
export function matchDesktopCommand(event: ShortcutEvent): DesktopCommand | null {
  if ((event.altKey || event.metaKey) && !event.ctrlKey && event.key === "Tab") {
    return event.shiftKey ? "switch-previous" : "switch-next";
  }
  if (event.altKey && !event.ctrlKey && !event.metaKey && event.key === "F4") {
    return "close-window";
  }
  if (!event.altKey && !event.ctrlKey && !event.metaKey && event.key === "F11") {
    return "fullscreen";
  }
  if (!event.metaKey || event.ctrlKey || event.altKey) {
    return null;
  }
  if (event.key === "ArrowUp") {
    return "maximize";
  }
  if (event.key === "ArrowDown") {
    return "minimize";
  }
  if (event.key === "ArrowLeft") {
    return event.shiftKey ? "window-workspace-previous" : "workspace-previous";
  }
  if (event.key === "ArrowRight") {
    return event.shiftKey ? "window-workspace-next" : "workspace-next";
  }
  if (event.key.toLowerCase() === "m" && event.shiftKey) {
    return "monitor-next";
  }
  return null;
}
