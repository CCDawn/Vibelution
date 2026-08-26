import type { MeetingSourceMessage } from "../../api/types/hypothesisFirst";

const MACHINE_AGENT_ID =
  /^(?:agent-\d{8}(?:-[a-z0-9][a-z0-9._-]*)?|session-[a-z0-9][a-z0-9._-]*)$/i;
const AGENT_CODE = /^A\d{3,}$/i;
// Only trust a participant code when the session id uses the server's
// timestamped, code-bearing shape.  Generic ids such as `session-a` are not
// an identity mapping and must remain position-neutral in the UI.
const CODE_BEARING_SESSION_ID = /^session-\d{8}-\d{6}-(a\d{3,})$/i;
// Keep the legacy fixture/compatibility form deterministic without treating
// a long runtime id (for example `agent-20260826-...`) as a display code.
const NUMERIC_AGENT_ID = /^agent-(\d{1,3})$/i;

export function isMachineAgentId(value: string): boolean {
  return MACHINE_AGENT_ID.test(value.trim());
}

export function meetingSpeakerLabel(
  message: Pick<MeetingSourceMessage, "agentId" | "role" | "speakerTitle">,
): string {
  // The room already carries the human-facing identity (interface code +
  // Chinese post title, e.g. 「A014 · 科研协调」); prefer it over machine
  // agent ids and English role keys that users cannot map to a teammate.
  const title = String(message.speakerTitle ?? "").trim();
  if (title && !isMachineAgentId(title)) return title;
  const role = String(message.role ?? "").trim();
  if (role && !isMachineAgentId(role)) return role;
  const agentId = String(message.agentId ?? "").trim();
  if (agentId && !isMachineAgentId(agentId)) return agentId;
  return "发言人";
}

function explicitAgentCode(rawId: string): string | null {
  const id = String(rawId || "").trim();
  if (AGENT_CODE.test(id)) return id.toUpperCase();
  const sessionMatch = CODE_BEARING_SESSION_ID.exec(id);
  return sessionMatch?.[1]?.toUpperCase() ?? null;
}

function neutralParticipantLabel(index: number): string {
  return `第 ${index + 1} 位参与者`;
}

export function meetingSpeakerCode(rawId: string, index: number): string {
  const id = String(rawId || "").trim();
  const numericAgentMatch = NUMERIC_AGENT_ID.exec(id);
  const numericAgentCode = numericAgentMatch
    ? `A${numericAgentMatch[1].padStart(3, "0")}`
    : null;
  return (
    explicitAgentCode(id) ?? numericAgentCode ?? neutralParticipantLabel(index)
  );
}

type ResolvedSpeakerOrder = {
  matchOrder: string[];
  displayOrder: Array<string | null>;
};

function hasUniqueValues(values: readonly string[]): boolean {
  return values.length > 0 && new Set(values).size === values.length;
}

function canMapSessionOrderToParticipants(
  speakerOrder: readonly string[],
  participants: readonly string[],
): boolean {
  if (
    speakerOrder.length === 0 ||
    speakerOrder.length !== participants.length ||
    !speakerOrder.every(isMachineAgentId) ||
    !speakerOrder.every(Boolean) ||
    !participants.every((participant) =>
      Boolean(explicitAgentCode(participant)),
    ) ||
    !hasUniqueValues(speakerOrder)
  ) {
    return false;
  }
  const participantCodes = participants.map(
    (participant) => explicitAgentCode(participant) ?? "",
  );
  const speakerCodes = speakerOrder.map(
    (speaker) => explicitAgentCode(speaker) ?? "",
  );
  return (
    hasUniqueValues(participantCodes) &&
    hasUniqueValues(speakerCodes) &&
    speakerCodes.every((code) => participantCodes.includes(code))
  );
}

function resolveSpeakerOrder(
  participantsInput: readonly string[] | null | undefined,
  speakerOrderInput: readonly string[] | null | undefined,
): ResolvedSpeakerOrder {
  const participants = (participantsInput ?? []).map((item) =>
    String(item || "").trim(),
  );
  const speakerOrder = (speakerOrderInput ?? []).map((item) =>
    String(item || "").trim(),
  );
  const hasSpeakerOrder = speakerOrder.some(Boolean);
  const matchOrder = (hasSpeakerOrder ? speakerOrder : participants).filter(
    Boolean,
  );

  if (
    hasSpeakerOrder &&
    canMapSessionOrderToParticipants(speakerOrder, participants)
  ) {
    return {
      matchOrder,
      displayOrder: speakerOrder.map((speaker) => explicitAgentCode(speaker)),
    };
  }

  return {
    matchOrder,
    displayOrder: matchOrder.map((item) => explicitAgentCode(item)),
  };
}

function messageSpeakerIds(message: MeetingSourceMessage): string[] {
  // Room messages carry participantId while meeting participants are agentIds;
  // collect both spaces so speaker matching works regardless of source.
  return [
    message.participantId,
    message.agentId,
    message.speakerCode,
    message.sessionId,
    message.role,
  ]
    .map((item) => String(item || "").trim())
    .filter(Boolean);
}

function isCompletedSpeech(message: MeetingSourceMessage): boolean {
  return (
    String(message.status ?? "")
      .trim()
      .toLowerCase() === "completed"
  );
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
  const resolvedOrder = resolveSpeakerOrder(
    input.participants,
    input.speakerOrder,
  );
  const order = resolvedOrder.matchOrder;
  const expected = order.length;
  const completed = (input.messages ?? []).filter(isCompletedSpeech);
  const spokenById = new Set(completed.flatMap(messageSpeakerIds));
  let spoken = 0;
  let nextIndex = -1;
  for (let index = 0; index < order.length; index += 1) {
    const id = order[index];
    const displayId = resolvedOrder.displayOrder[index];
    if (
      id &&
      (spokenById.has(id) || (displayId ? spokenById.has(displayId) : false))
    ) {
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
  const nextCode =
    !complete && nextIndex >= 0
      ? meetingSpeakerCode(
          resolvedOrder.displayOrder[nextIndex] || order[nextIndex] || "",
          nextIndex,
        )
      : null;
  if (complete) {
    return {
      spoken,
      expected,
      nextCode: null,
      complete,
      label: "讨论完成，待整理",
    };
  }
  const countLabel = `已发言 ${spoken}/${expected || 0}`;
  return {
    spoken,
    expected,
    nextCode,
    complete,
    label: nextCode
      ? `${countLabel} · ${nextCode.startsWith("第 ") ? "待" : "待 "}${nextCode}`
      : countLabel,
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
