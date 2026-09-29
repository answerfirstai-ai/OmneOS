/**
 * Character presence.
 *
 * The shell asks a renderer to paint `PresenceView`. The current renderer is a
 * simple core mark. A later animated character can replace the renderer
 * without changing backend state.
 */

import { characterAsset, characterState } from "./character.js";
import { environmentState, type EnvironmentInput, type EnvironmentState } from "./environment.js";

export type PresenceMotion = "still" | "steady";

export interface PresenceView {
  state: EnvironmentState;
  label: string;
  motion: PresenceMotion;
  asset: string | null;
}

export interface CharacterRenderer {
  render(host: HTMLElement, view: PresenceView): void;
}

const STEADY: ReadonlySet<EnvironmentState> = new Set([
  "LISTENING",
  "UNDERSTANDING",
  "PLANNING",
  "ROUTING",
  "WORKING",
  "VERIFYING",
  "WAITING",
]);

/** Build the view a renderer paints. Motion is optional; the label is the state. */
export function presenceView(input: EnvironmentInput): PresenceView {
  const state = environmentState(input);
  return {
    state,
    label: state,
    motion: STEADY.has(state) ? "steady" : "still",
    asset: characterAsset(characterState(input)),
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
