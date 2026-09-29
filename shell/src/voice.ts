/** Voice panel model. The shell does not open a microphone. */

export interface VoiceStatus {
  provider: string;
  hardware: string;
  permission: string;
  listening: boolean;
  reason?: string;
}

/** Listen control is enabled only when policy, provider, and hardware all allow it. */
export function voiceControlEnabled(status: VoiceStatus): boolean {
  return (
    status.permission === "ALLOW" &&
    status.provider === "available" &&
    status.hardware === "available" &&
    status.listening === false
  );
}

/** Describe the voice panel without claiming that audio was captured. */
export function voiceSummary(status: VoiceStatus): string {
  if (!voiceControlEnabled(status)) {
    const reason = status.reason ?? "voice is unavailable";
    return `${status.permission} · provider ${status.provider} · hardware ${status.hardware} · ${reason}`;
  }
  return "voice is ready";
}
