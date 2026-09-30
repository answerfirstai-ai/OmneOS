/** Objectives the launcher sends to the intelligence layer. */

export interface LauncherAction {
  id: string;
  label: string;
  objective: string;
}

export const LAUNCHER_ACTIONS: readonly LauncherAction[] = [
  {
    id: "research-models",
    label: "Research NVIDIA's latest AI models",
    objective: "Research NVIDIA's latest AI models",
  },
  {
    id: "open-chrome",
    label: "Open Chrome",
    objective: "Open Chrome",
  },
  {
    id: "build-project",
    label: "Build my project",
    objective: "Build my project",
  },
  {
    id: "system-resources",
    label: "Check system resources",
    objective: "Check system resources",
  },
  {
    id: "coding-agent",
    label: "Start coding agent",
    objective: "Start coding agent",
  },
  {
    id: "find-files",
    label: "Find my files",
    objective: "Find my files",
  },
];

/** The objective posted to the core for one launcher action. */
export function launcherObjective(id: string): string | null {
  const action = LAUNCHER_ACTIONS.find((item) => item.id === id);
  return action === undefined ? null : action.objective;
}
