/** Pure helpers for the desktop panels. */

export interface TaskDocument {
  id: string;
  objective: string;
  status: string;
  metadata?: { role?: string };
}

export interface AgentDocument {
  id: string;
  state: string;
  enabled: boolean;
}

export interface ModelDocument {
  id: string;
  provider: string;
  local: boolean;
}

export interface EventDocument {
  id: string;
  type: string;
}

export function parentTasks(tasks: readonly TaskDocument[]): TaskDocument[] {
  return tasks.filter((task) => task.metadata?.role === "parent");
}

export function taskLine(task: TaskDocument): string {
  return `${task.status} ${task.objective}`;
}

export function agentLine(agent: AgentDocument): string {
  const enabled = agent.enabled ? "enabled" : "disabled";
  return `${agent.id} ${agent.state} ${enabled}`;
}

export function modelLine(model: ModelDocument): string {
  const location = model.local ? "local" : "cloud";
  return `${model.id} ${model.provider} ${location}`;
}

export function notificationLine(event: EventDocument): string {
  return `${event.type}`;
}
