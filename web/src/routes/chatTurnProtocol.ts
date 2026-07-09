import type { ConversationMessage } from "../api/types";
import { shouldDisplayTranscriptCell } from "../components/conversation/conversationDisplayProtocol";
import { answerProjectionContent } from "../components/conversation/conversationInternalStatus";

export type ChatTurnRenderProtocol =
  | "legacy_assistant_delta"
  | "native_codex_transcript"
  | "process_feedback";

export type ChatTurnProtocolSurface = {
  answerContent?: unknown;
  thoughtContent?: unknown;
  feedbackEventCount?: number;
  codexTranscript?: ConversationMessage["codexTranscript"];
};

function compactText(value: unknown) {
  return String(value ?? "").trim();
}

function nativeTranscriptCells(transcript: ConversationMessage["codexTranscript"] | undefined) {
  if (
    !transcript
    || String(transcript.source ?? "").trim() !== "native"
    || !Array.isArray(transcript.cells)
  ) {
    return [];
  }
  return transcript.cells.filter(shouldDisplayTranscriptCell);
}

export function visibleNativeAssistantMarkdownText(
  transcript: ConversationMessage["codexTranscript"] | undefined,
) {
  return nativeTranscriptCells(transcript)
    .filter((cell) => String(cell.kind ?? "").trim() === "assistant_markdown")
    .map((cell) => compactText(cell.text))
    .filter(Boolean)
    .join("\n\n");
}

export function hasVisibleNativeCodexTranscript(
  transcript: ConversationMessage["codexTranscript"] | undefined,
) {
  return nativeTranscriptCells(transcript).length > 0;
}

export function activeTurnProtocolTextLength(surface: ChatTurnProtocolSurface) {
  return compactText(surface.answerContent).length
    + compactText(surface.thoughtContent).length
    + visibleNativeAssistantMarkdownText(surface.codexTranscript).length;
}

export function resolveAssistantTurnRenderProtocol(surface: ChatTurnProtocolSurface): ChatTurnRenderProtocol {
  if (hasVisibleNativeCodexTranscript(surface.codexTranscript)) {
    return "native_codex_transcript";
  }
  if (compactText(surface.answerContent) || compactText(surface.thoughtContent)) {
    return "legacy_assistant_delta";
  }
  return "process_feedback";
}

export function hasVisibleActiveTurnProtocolContent(surface: ChatTurnProtocolSurface) {
  return Boolean(
    activeTurnProtocolTextLength(surface) > 0
    || (surface.feedbackEventCount ?? 0) > 0
    || hasVisibleNativeCodexTranscript(surface.codexTranscript)
  );
}

export function hasCommittedAssistantProtocolAnswer(message: ConversationMessage) {
  if (message.role !== "assistant") {
    return false;
  }
  return Boolean(
    compactText(answerProjectionContent(message))
    || compactText(visibleNativeAssistantMarkdownText(message.codexTranscript))
  );
}
