import type { MeetingSourceMessage } from "../../api/types/hypothesisFirst";

const MACHINE_AGENT_ID = /^agent-\d{8}(?:-|$)/i;

export function isMachineAgentId(value: string): boolean {
  return MACHINE_AGENT_ID.test(value.trim());
}

export function meetingSpeakerLabel(message: Pick<MeetingSourceMessage, "agentId" | "role">): string {
  const role = String(message.role ?? "").trim();
  if (role && !isMachineAgentId(role)) return role;
  const agentId = String(message.agentId ?? "").trim();
  if (agentId && !isMachineAgentId(agentId)) return agentId;
  return "发言人";
}

export function displayMeetingMessageText(
  content: string,
  options?: { collapseWhitespace?: boolean },
): string {
  let text = String(content ?? "");
  text = text.replace(/\*\*/g, "");
  text = text.replace(/`([^`]+)`/g, "$1");
  text = text.replace(/^#{1,6}\s+/gm, "");
  text = text.replace(/(^|[^\w])\*([^*\n]+)\*(?!\*)/g, "$1$2");
  if (options?.collapseWhitespace) {
    text = text.replace(/\s+/g, " ").trim();
  }
  return text.trim();
}

export function meetingMessageNeedsFullText(content: string): boolean {
  const trimmed = String(content ?? "").trim();
  if (!trimmed) return false;
  return trimmed.length > 80 || /\n/.test(trimmed);
}
