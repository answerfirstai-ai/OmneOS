/** Human permission copy. The gateway remains the authority that allows or denies. */

export interface PermissionView {
  taskId: string;
  heading: string;
  command: string;
  reason: string;
  impact: string;
  requester: string;
  mission: string;
}

export function permissionPrompt(input: {
  taskId: string;
  toolId: string;
  command: string;
  agentId: string | null;
  missionObjective: string | null;
}): PermissionView {
  const command = input.command.trim() === "" ? input.toolId : input.command.trim();
  const requester = input.agentId !== null && input.agentId.trim() !== "" ? input.agentId : "OMNE";
  const mission =
    input.missionObjective !== null && input.missionObjective.trim() !== ""
      ? input.missionObjective
      : "unknown mission";
  return {
    taskId: input.taskId,
    heading: "OMNE wants to run",
    command,
    reason: reasonFor(input.toolId),
    impact: impactFor(input.toolId, command),
    requester,
    mission,
  };
}

function reasonFor(toolId: string): string {
  switch (toolId) {
    case "terminal.execute":
      return "Run a command in the workspace.";
    case "filesystem.write":
      return "Write a file in the workspace.";
    case "filesystem.read":
      return "Read a file in the workspace.";
    case "process.start":
    case "process.stop":
      return "Control a process.";
    case "git.commit":
      return "Create a git commit.";
    default:
      return toolId === "" ? "Use a tool." : `Use ${toolId}.`;
  }
}

function impactFor(toolId: string, command: string): string {
  if (command === "npm install" || command.startsWith("npm install ")) {
    return "Downloads packages and modifies node_modules.";
  }
  switch (toolId) {
    case "terminal.execute":
      return "Runs the command inside the workspace.";
    case "filesystem.write":
      return "Creates or replaces a file in the workspace.";
    case "filesystem.read":
      return "Reads a file and does not modify it.";
    default:
      return "The permission engine still decides whether this runs.";
  }
}
