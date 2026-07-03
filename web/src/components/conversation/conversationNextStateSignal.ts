import type { ChatNextStateSignalSummary } from "../../api/types";

function isBusyConversationPhase(phase: string) {
  return ["queued", "running", "stopping"].includes(String(phase || "").trim().toLowerCase());
}

export function shouldShowNextStateSignalInConversation(
  signal: ChatNextStateSignalSummary,
  phase: string,
) {
  if (signal.kind === "user_continues") {
    return isBusyConversationPhase(phase);
  }
  return true;
}
