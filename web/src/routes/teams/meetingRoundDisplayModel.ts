import type { MeetingSourceMessage } from "../../api/types/hypothesisFirst";

const MACHINE_AGENT_ID = /^agent-\d{8}(?:-|$)/i;
const AGENT_CODE = /^A\d{3,}$/i;

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

export function meetingSpeakerCode(rawId: string, index: number): string {
  const id = String(rawId || "").trim();
  if (AGENT_CODE.test(id)) return id.toUpperCase();
  return `A${String(index + 1).padStart(3, "0")}`;
}

function messageSpeakerId(message: MeetingSourceMessage): string {
  return String(
    message.participantId
    || message.agentId
    || message.role
    || "",
  ).trim();
}

function isCompletedSpeech(message: MeetingSourceMessage): boolean {
  return String(message.status ?? "").trim().toLowerCase() === "completed";
}

export type MeetingDiscussionProgress = {
  spoken: number;
  expected: number;
  nextCode: string | null;
  complete: boolean;
  label: string;
};

export function meetingDiscussionProgress(input: {
  participants?: readonly string[] | null;
  speakerOrder?: readonly string[] | null;
  messages?: readonly MeetingSourceMessage[] | null;
}): MeetingDiscussionProgress {
  const order = (
    (input.speakerOrder && input.speakerOrder.length > 0)
      ? input.speakerOrder
      : (input.participants ?? [])
  ).map((item) => String(item || "").trim()).filter(Boolean);
  const expected = order.length;
  const completed = (input.messages ?? []).filter(isCompletedSpeech);
  const spokenById = new Set(completed.map(messageSpeakerId).filter(Boolean));
  let spoken = 0;
  let nextIndex = -1;
  for (let index = 0; index < order.length; index += 1) {
    const id = order[index];
    if (id && spokenById.has(id)) {
      spoken += 1;
    } else if (nextIndex < 0) {
      nextIndex = index;
    }
  }
  if (spoken === 0 && completed.length > 0 && expected > 0) {
    spoken = Math.min(completed.length, expected);
    nextIndex = spoken < expected ? spoken : -1;
  }
  const complete = expected > 0 && spoken >= expected;
  const nextCode = !complete && nextIndex >= 0
    ? meetingSpeakerCode(order[nextIndex] || "", nextIndex)
    : null;
  if (complete) {
    return { spoken, expected, nextCode: null, complete, label: "讨论完成，待整理" };
  }
  const countLabel = `已发言 ${spoken}/${expected || 0}`;
  return {
    spoken,
    expected,
    nextCode,
    complete,
    label: nextCode ? `${countLabel} · 待 ${nextCode}` : countLabel,
  };
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
