/** Tray text and chord matching. Unmatched keys are ignored and are not stored. */

import type { ShortcutEvent } from "./shortcuts.js";

export interface InputStatusView {
  text: string;
  state: "unknown" | "unbound" | "ready" | "command";
  activation: string;
  cancel: string;
  pushToTalk: string;
  attention: "idle" | "command";
  revision: number;
}

const SAMPLE_KEYS = new Set(["keycodes", "scancodes", "keylog", "pressed_keys"]);
const MODIFIERS = ["ctrl", "alt", "shift", "super"] as const;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function rejectCapture(value: unknown): void {
  if (Array.isArray(value)) {
    for (const item of value) {
      rejectCapture(item);
    }
    return;
  }
  if (!isRecord(value)) {
    return;
  }
  for (const key of Object.keys(value)) {
    if (SAMPLE_KEYS.has(key)) {
      throw new Error("Input payload must not include a key log");
    }
    rejectCapture(value[key]);
  }
}

function chordLabel(value: unknown): string {
  if (!isRecord(value)) {
    return "";
  }
  const modifiers = Array.isArray(value["modifiers"])
    ? value["modifiers"].filter((item): item is string => typeof item === "string")
    : [];
  const key = typeof value["key"] === "string" ? value["key"] : "";
  const button = typeof value["button"] === "string" ? value["button"] : "";
  const token = key || button;
  if (modifiers.length === 0 || token.length === 0) {
    return "";
  }
  return [...modifiers, token].join("+");
}

/** Format GET /input for the desktop tray. */
export function readInputStatus(payload: unknown): InputStatusView {
  rejectCapture(payload);
  const empty: InputStatusView = {
    text: "input unknown",
    state: "unknown",
    activation: "",
    cancel: "",
    pushToTalk: "",
    attention: "idle",
    revision: 0,
  };
  if (!isRecord(payload)) {
    return empty;
  }
  const input = isRecord(payload["input"]) ? payload["input"] : payload;
  if (
    input["key_stream"] === true ||
    input["pointer_stream"] === true ||
    input["listening"] === true ||
    input["host_grab"] === true
  ) {
    throw new Error("Input payload must not capture keys");
  }
  if (input["observed"] !== true) {
    return empty;
  }
  const activation = chordLabel(input["activation"]);
  const cancel = chordLabel(input["cancel"]);
  const pushToTalk = chordLabel(input["push_to_talk"]);
  const attention = input["attention"] === "command" ? "command" : "idle";
  const revision = typeof input["revision"] === "number" ? input["revision"] : 0;
  if (activation.length === 0) {
    return { ...empty, text: "input unbound", state: "unbound", cancel, pushToTalk, revision };
  }
  if (attention === "command") {
    return {
      text: "command",
      state: "command",
      activation,
      cancel,
      pushToTalk,
      attention,
      revision,
    };
  }
  return {
    text: activation,
    state: "ready",
    activation,
    cancel,
    pushToTalk,
    attention,
    revision,
  };
}

/** Match one configured chord. A key that is not that chord returns false. */
export function chordMatches(event: ShortcutEvent, chord: string): boolean {
  const parsed = parseChord(chord);
  if (parsed === null || parsed.button !== null) {
    return false;
  }
  const held = heldModifiers(event);
  if (!sameModifiers(held, parsed.modifiers)) {
    return false;
  }
  return eventToken(event.key) === parsed.key;
}

/** Match a configured pointer chord. Other clicks are ignored. */
export function pointerMatches(event: ShortcutEvent & { button: number }, chord: string): boolean {
  const parsed = parseChord(chord);
  if (parsed === null || parsed.button === null) {
    return false;
  }
  let button = "";
  if (event.button === 0) {
    button = "left";
  } else if (event.button === 1) {
    button = "middle";
  } else if (event.button === 2) {
    button = "right";
  }
  if (button !== parsed.button) {
    return false;
  }
  return sameModifiers(heldModifiers(event), parsed.modifiers);
}

function parseChord(
  chord: string,
): { modifiers: string[]; key: string | null; button: string | null } | null {
  const text = chord.trim().toLowerCase();
  if (text.length === 0) {
    return null;
  }
  const parts = text.split("+");
  const modifiers: string[] = [];
  let key: string | null = null;
  let button: string | null = null;
  for (const part of parts) {
    if ((MODIFIERS as readonly string[]).includes(part)) {
      modifiers.push(part);
      continue;
    }
    if (part === "left" || part === "right" || part === "middle") {
      button = part;
      continue;
    }
    key = part;
  }
  if (modifiers.length === 0 || (key === null && button === null)) {
    return null;
  }
  return { modifiers, key, button };
}

function heldModifiers(event: ShortcutEvent): string[] {
  const held: string[] = [];
  if (event.ctrlKey) {
    held.push("ctrl");
  }
  if (event.altKey) {
    held.push("alt");
  }
  if (event.shiftKey) {
    held.push("shift");
  }
  if (event.metaKey) {
    held.push("super");
  }
  return held;
}

function sameModifiers(held: readonly string[], expected: readonly string[]): boolean {
  if (held.length !== expected.length) {
    return false;
  }
  return expected.every((modifier) => held.includes(modifier));
}

function eventToken(key: string): string {
  if (key === " ") {
    return "space";
  }
  return key.length === 1 ? key.toLowerCase() : key.toLowerCase();
}
