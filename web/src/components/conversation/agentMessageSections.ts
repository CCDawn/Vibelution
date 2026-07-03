import { agentMessageToSections } from "../../agent-thread/sections";
import type {
  AgentAttachmentPart,
  AgentMentalSnapshot,
  AgentMessage,
  AgentMessagePart,
  AgentMessageSection,
  AgentMessageSectionKind,
  AgentMentalPart,
  AgentReferencePart,
  AgentRuntimeEventPart,
  AgentTextPart,
  AgentThoughtPart,
  AgentToolCallPart,
} from "../../agent-thread/types";
import {
  isProviderFailureSummaryText,
  isRuntimeNoticeText,
  isTransientReasoningStatusText,
} from "./conversationMessagePredicates";

export function hasMentalSnapshot(snapshot: AgentMentalSnapshot | undefined) {
  if (!snapshot) {
    return false;
  }
  return [
    snapshot.mood,
    snapshot.feeling,
    snapshot.whisper,
    snapshot.cognitiveState,
  ].some((value) => String(value ?? "").trim().length > 0);
}

export type AgentMessageSectionState = {
  sectionCount: number;
  sectionKinds: AgentMessageSectionKind[];
  hasProcessSection: boolean;
  hasContentSection: boolean;
  hasContextSection: boolean;
  answerText: string;
  userText: string;
  hasThoughtBlock: boolean;
  hasMentalBlock: boolean;
  hasToolBlock: boolean;
  hasResponseBlock: boolean;
  hasFeedbackTimeline: boolean;
  hasUserContent: boolean;
};

export type AgentMessageContextSection = Omit<AgentMessageSection, "kind" | "parts"> & {
  kind: "context";
  parts: Array<AgentAttachmentPart | AgentReferencePart>;
};

export type AgentMessageContentSection = Omit<AgentMessageSection, "kind" | "parts"> & {
  kind: "content";
  parts: AgentTextPart[];
};

export type AgentMessageProcessPart =
  | AgentThoughtPart
  | AgentMentalPart
  | AgentRuntimeEventPart
  | AgentToolCallPart;

export type AgentMessageProcessSection = Omit<AgentMessageSection, "kind" | "parts"> & {
  kind: "process";
  parts: AgentMessageProcessPart[];
};

export function buildAgentMessageSectionState(message: AgentMessage): AgentMessageSectionState {
  const sections = agentMessageToSections(message);
  const processParts = sectionParts(sections, "process");
  const contentParts = sectionParts(sections, "content");
  const answerText = agentMessageText(contentParts, "answer");
  const userText = agentMessageText(contentParts, "user");
  const sectionKinds = sections.map((section) => section.kind);
  return {
    sectionCount: sections.length,
    sectionKinds,
    hasProcessSection: sectionKinds.includes("process"),
    hasContentSection: sectionKinds.includes("content"),
    hasContextSection: sectionKinds.includes("context"),
    answerText,
    userText,
    hasThoughtBlock: message.role === "assistant" && processParts.some(isVisibleAgentThoughtPart),
    hasMentalBlock: message.role === "assistant" && processParts.some(isVisibleAgentMentalPart),
    hasToolBlock: message.role === "assistant" && processParts.some((part) => part.type === "tool-call"),
    hasResponseBlock: hasAgentResponseBlock(message, answerText),
    hasFeedbackTimeline: message.role === "assistant" && processParts.some(isAgentFeedbackTimelinePart),
    hasUserContent: message.role !== "assistant" && Boolean(userText),
  };
}

export function agentMessageContextSections(message: AgentMessage): AgentMessageContextSection[] {
  return agentMessageToSections(message)
    .filter((section): section is AgentMessageContextSection => section.kind === "context");
}

export function agentMessageContentSections(message: AgentMessage): AgentMessageContentSection[] {
  return agentMessageToSections(message)
    .filter((section): section is AgentMessageContentSection => section.kind === "content");
}

export function agentMessageProcessSections(message: AgentMessage): AgentMessageProcessSection[] {
  return agentMessageToSections(message)
    .filter((section): section is AgentMessageProcessSection => section.kind === "process");
}

function sectionParts(sections: AgentMessageSection[], kind: AgentMessageSectionKind) {
  return sections
    .filter((section) => section.kind === kind)
    .flatMap((section) => section.parts);
}

function agentMessageText(parts: AgentMessagePart[], channel: AgentTextPart["channel"]) {
  return parts
    .filter((part): part is AgentTextPart => part.type === "text" && part.channel === channel)
    .map((part) => part.text.trim())
    .filter(Boolean)
    .join("\n\n");
}

function isVisibleAgentThoughtPart(part: AgentMessagePart): part is AgentThoughtPart {
  return part.type === "thought" && Boolean((part.text || part.summary || "").trim());
}

function isVisibleAgentMentalPart(part: AgentMessagePart): part is AgentMentalPart {
  if (part.type !== "mental") {
    return false;
  }
  return hasMentalSnapshot(part.snapshot) || Boolean(part.summary.trim());
}

function isAgentFeedbackTimelinePart(part: AgentMessagePart) {
  if (part.type === "runtime-event") {
    return true;
  }
  if (part.type === "tool-call") {
    return part.source === "feedback-event";
  }
  if (part.type === "thought" || part.type === "mental") {
    return part.sequence !== undefined || Boolean(part.timestamp);
  }
  return false;
}

function agentMetadataString(message: AgentMessage, key: string) {
  const value = message.metadata?.[key] ?? message.source.metadata?.[key];
  return typeof value === "string" ? value.trim() : "";
}

function hasAgentResponseBlock(message: AgentMessage, answerText: string) {
  if (message.role !== "assistant") {
    return false;
  }
  if (!answerText.trim()) {
    return false;
  }
  if (isProviderFailureSummaryText(answerText)) {
    return false;
  }
  const kind = agentMetadataString(message, "kind");
  if (kind === "turn_error" || kind === "group_room_transcript") {
    return false;
  }
  if (kind === "image2_generation" && agentMetadataString(message, "status") === "failed") {
    return false;
  }
  if (isRuntimeNoticeText(answerText)) {
    return false;
  }
  if (isAgentRuntimeStatusText(message, answerText)) {
    return false;
  }
  return true;
}

function isAgentRuntimeStatusText(message: AgentMessage, text: string) {
  const content = text.trim();
  if (!content) {
    return false;
  }
  if (
    /^(状态|status)\s+.+/i.test(content)
    && /(正在|running|thinking|reasoning|tooling|模型|model|上下文|context)/i.test(content)
  ) {
    return true;
  }
  return Boolean(message.streaming) && isTransientReasoningStatusText(content);
}
