/**
 * Character presence.
 *
 * The shell asks a renderer to paint `PresenceView`. The current renderer is a
 * simple core mark. A later animated character can replace the renderer
 * without changing backend state.
 */

import { characterAsset, characterMode, characterState, type CharacterMode } from "./character.js";
import { type EnvironmentInput } from "./environment.js";

export type PresenceMotion = "still" | "steady";

export interface PresenceView {
  state: CharacterMode;
  label: CharacterMode;
  motion: PresenceMotion;
  asset: string | null;
  ask: string | null;
}

export interface CharacterRenderer {
  render(host: HTMLElement, view: PresenceView): void;
}

const STEADY: ReadonlySet<CharacterMode> = new Set([
  "THINKING",
  "RESEARCHING",
  "EXECUTING",
  "WAITING",
]);

/** Build the view a renderer paints. The label is the live system state. */
export function presenceView(input: EnvironmentInput): PresenceView {
  const state = characterMode(input);
  return {
    state,
    label: state,
    motion: STEADY.has(state) ? "steady" : "still",
    asset: characterAsset(characterState(input)),
    ask: state === "IDLE" ? "What can I do?" : null,
  };
}

/** Paint the placeholder core. The label stays visible when motion is disabled. */
export const coreRenderer: CharacterRenderer = {
  render(host: HTMLElement, view: PresenceView): void {
    if (host.dataset["state"] === view.state && host.dataset["motion"] === view.motion) {
      const existing = host.querySelector("[data-presence-label]");
      if (existing instanceof HTMLElement && existing.textContent === view.label) {
        return;
      }
    }
    host.dataset["state"] = view.state;
    host.dataset["motion"] = view.motion;
    const label = host.querySelector("[data-presence-label]");
    if (label instanceof HTMLElement) {
      label.textContent = view.label;
    }
  },
};
