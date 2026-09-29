/** Global desktop shortcuts. The command palette is the primary entry. */

import type { WindowId } from "./windows.js";

export type ShortcutTarget = WindowId | "palette";

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
];

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
