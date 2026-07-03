import type { AgentMessage, AgentMessagePart, AgentTextPart, AgentToolCallPart } from "../../agent-thread/types";
import {
  agentMessageContentSections,
  agentMessageContextSections,
  agentMessageProcessSections,
  buildAgentMessageSectionState,
  type AgentMessageContentSection,
  type AgentMessageContextSection,
  type AgentMessageProcessSection,
  type AgentMessageSectionState,
} from "./messageSections";

export type AgentMessageRenderState = {
  sectionState: AgentMessageSectionState;
  contentSections: AgentMessageContentSection[];
  contextSections: AgentMessageContextSection[];
  processSections: AgentMessageProcessSection[];
  sectionKinds: string;
  userContentSectionIds: string | undefined;
  answerContentSectionIds: string | undefined;
  processSectionIds: string | undefined;
  processSignal: string;
  processSignalWithoutMental: string;
  renderedTextLength: number;
  toolCalls: AgentToolCallPart[];
};

export function buildAgentMessageRenderState(message: AgentMessage): AgentMessageRenderState {
  const sectionState = buildAgentMessageSectionState(message);
  const contentSections = agentMessageContentSections(message);
  const contextSections = agentMessageContextSections(message);
  const processSections = agentMessageProcessSections(message);
  const contentParts = contentSections.flatMap((section) => section.parts);
  const processParts = processSections.flatMap((section) => section.parts);
  return {
    sectionState,
    contentSections,
    contextSections,
    processSections,
    sectionKinds: sectionState.sectionKinds.join(" "),
    userContentSectionIds: contentSectionIdsForChannel(contentSections, "user"),
    answerContentSectionIds: contentSectionIdsForChannel(contentSections, "answer"),
    processSectionIds: processSectionIdsForSections(processSections),
    processSignal: processSignalForParts(processParts),
    processSignalWithoutMental: processSignalForParts(processParts.filter((part) => part.type !== "mental")),
    renderedTextLength: renderedTextLengthForParts(contentParts, processParts),
    toolCalls: processParts.filter(isAgentToolCallPart),
  };
}

function contentSectionIdsForChannel(
  sections: AgentMessageContentSection[],
  channel: AgentTextPart["channel"],
) {
  return sections
    .filter((section) => section.parts.some((part) => part.channel === channel))
    .map((section) => section.id)
    .join(" ") || undefined;
}

function processSectionIdsForSections(sections: AgentMessageProcessSection[]) {
  return sections.map((section) => section.id).join(" ") || undefined;
}

function isAgentToolCallPart(part: AgentMessagePart): part is AgentToolCallPart {
  return part.type === "tool-call";
}

function renderedTextLengthForParts(contentParts: AgentTextPart[], processParts: AgentMessagePart[]) {
  return [
    ...contentParts.map((part) => part.text),
    ...processParts
      .filter((part) => part.type === "thought")
      .map((part) => part.text || part.summary || ""),
  ].reduce((total, value) => total + value.length, 0);
}

function processSignalForParts(parts: AgentMessagePart[]) {
  return parts.map(processPartSignal).join("|");
}

function processPartSignal(part: AgentMessagePart) {
  if (part.type === "thought") {
    return [
      part.type,
      part.status,
      part.sequence ?? "",
      part.timestamp ?? "",
      compactTextSignal(part.text),
      compactTextSignal(part.summary ?? ""),
    ].join(":");
  }
  if (part.type === "mental") {
    const snapshot = part.snapshot;
    return [
      part.type,
      part.status,
      part.sequence ?? "",
      part.timestamp ?? "",
      compactTextSignal(part.summary),
      snapshot?.mood ?? "",
      snapshot?.feeling ?? "",
      snapshot?.whisper ?? "",
      snapshot?.summary ?? "",
      snapshot?.cognitiveState ?? "",
      snapshot?.confidence ?? "",
      snapshot?.sampleSize ?? "",
      snapshot?.interventionCount ?? "",
      snapshot?.updatedAt ?? "",
      snapshot?.source ?? "",
      snapshot?.intervention ?? "",
      compactJsonSignal(snapshot?.metrics ?? {}),
    ].join(":");
  }
  if (part.type === "tool-call") {
    return [
      part.type,
      part.source ?? "",
      part.name,
      part.status,
      compactTextSignal(part.summary ?? ""),
      compactJsonSignal(part.arguments ?? {}),
      compactTextSignal(part.resultPreview ?? ""),
      part.error ?? "",
      part.durationMs ?? "",
      part.durationSeconds ?? "",
      part.timeoutSeconds ?? "",
      part.transportStatus ?? "",
      part.semanticStatus ?? "",
      part.exitCode ?? "",
      part.timedOut ?? "",
      part.failureClass ?? "",
      part.resultKind ?? "",
      part.truncated ?? "",
      part.originalLength ?? "",
      part.tracePath ?? "",
      part.sequence ?? "",
      part.timestamp ?? "",
      part.relatedThoughtSequence ?? "",
    ].join(":");
  }
  if (part.type === "runtime-event") {
    return [
      part.type,
      part.kind,
      part.name ?? "",
      part.status,
      compactTextSignal(part.summary),
      compactTextSignal(part.resultPreview ?? ""),
      part.error ?? "",
      part.sequence ?? "",
      part.timestamp ?? "",
      part.tracePath ?? "",
    ].join(":");
  }
  return part.type;
}

function compactJsonSignal(value: unknown) {
  const json = JSON.stringify(value ?? {});
  return json.length <= 240 ? json : `${json.slice(0, 240)}#${json.length}`;
}

function compactTextSignal(value: unknown) {
  const text = String(value ?? "");
  return text.length <= 240 ? text : `${text.slice(0, 240)}#${text.length}`;
}
