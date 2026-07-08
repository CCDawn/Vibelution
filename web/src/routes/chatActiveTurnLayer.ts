import { mergeAgentFeedbackEvents } from "../agent-thread/agentFeedbackEvents";
import {
  answerProjectionContent,
  isInternalStreamingStatusContent,
  isInternalStreamingStatusStage,
} from "../components/conversation/conversationInternalStatus";
import {
  shouldDisplayRuntimeStatus,
  shouldDisplayTranscriptCell,
} from "../components/conversation/conversationDisplayProtocol";
import type { ConversationMessage, SessionDetail, SessionStreamEvent } from "../api/types";

export type AssistantDeltaEvent = Extract<SessionStreamEvent, { type: "assistant_delta" }>;
type ConversationFeedbackEvent = NonNullable<ConversationMessage["feedbackEvents"]>[number];
export type ActiveTurnLayerState = {
  id: string;
  sessionId: string;
  turnId: string;
  updatedAt: string;
  streaming: boolean;
  processStage?: string;
  answerContent: string;
  thoughtContent: string;
  feedbackEvents: NonNullable<ConversationMessage["feedbackEvents"]>;
  timelineItems?: ConversationMessage["timelineItems"];
  codexTranscript?: ConversationMessage["codexTranscript"];
  ledgerSeq: number;
};

function normalizedLedgerSeq(value: unknown): number {
  const numeric = Number(value ?? 0);
  return Number.isFinite(numeric) && numeric > 0 ? numeric : 0;
}

function isStaleLedgerUpdate(currentSeq: unknown, incomingSeq: unknown): boolean {
  const current = normalizedLedgerSeq(currentSeq);
  const incoming = normalizedLedgerSeq(incomingSeq);
  return current > 0 && incoming > 0 && incoming < current;
}

function activeTurnMessageId(sessionId: string, turnId: string) {
  return `${sessionId}-message-active-${turnId || "current"}`;
}

function messageTurnId(message: ConversationMessage) {
  const rawTurnId = String(message.metadata?.turnId ?? "");
  return rawTurnId.startsWith("live:") ? rawTurnId.slice("live:".length) : rawTurnId;
}

function assistantDeltaAnswerContent(payload: AssistantDeltaEvent, base: ActiveTurnLayerState | undefined) {
  const rawDelta = payload.contentDelta ?? (payload.replaceContent || !base ? payload.content ?? "" : "");
  return isInternalStreamingStatusStage(payload.stage) && isInternalStreamingStatusContent(rawDelta) ? "" : rawDelta;
}

function compactText(value: unknown) {
  return String(value ?? "").trim();
}

function hasVisibleFeedbackEvent(event: ConversationFeedbackEvent) {
  if (!shouldDisplayRuntimeStatus({
    kind: event.kind,
    name: event.name,
    status: event.status,
    summary: event.summary,
    resultPreview: event.resultPreview,
    error: event.error,
    failureClass: event.failureClass,
    timedOut: event.timedOut,
  })) {
    return false;
  }
  if (event.kind === "status") {
    return true;
  }
  return Boolean(
    compactText(event.name)
    || compactText(event.summary)
    || compactText(event.resultPreview)
    || compactText(event.error)
    || compactText(event.failureClass)
  );
}

function visibleFeedbackEvents(events: ConversationFeedbackEvent[]) {
  return events.filter(hasVisibleFeedbackEvent);
}

function hasVisibleCodexTranscript(transcript: ConversationMessage["codexTranscript"] | undefined) {
  return Boolean(
    transcript
    && String(transcript.source ?? "").trim() === "native"
    && Array.isArray(transcript.cells)
    && transcript.cells.some(shouldDisplayTranscriptCell)
  );
}

function hasVisibleActiveTurnContent(layer: {
  answerContent: string;
  thoughtContent: string;
  feedbackEvents: ConversationFeedbackEvent[];
  codexTranscript?: ConversationMessage["codexTranscript"];
}) {
  return Boolean(
    compactText(layer.answerContent)
    || compactText(layer.thoughtContent)
    || layer.feedbackEvents.length > 0
    || hasVisibleCodexTranscript(layer.codexTranscript)
  );
}

export function mergeAssistantDeltaIntoActiveTurnLayer(
  previous: ActiveTurnLayerState | undefined,
  payload: AssistantDeltaEvent,
): ActiveTurnLayerState | undefined {
  if (isStaleLedgerUpdate(previous?.ledgerSeq, payload.ledgerSeq)) {
    return previous;
  }
  const sessionId = String(payload.sessionId || "").trim();
  const turnId = String(payload.turnId || "").trim();
  if (!sessionId) {
    return previous;
  }
  const now = payload.updatedAt || new Date().toISOString();
  const sameTurn = previous && previous.turnId === turnId;
  const base = sameTurn ? previous : undefined;
  const contentDelta = assistantDeltaAnswerContent(payload, base);
  const thoughtDelta = payload.thoughtDelta ?? (payload.replaceThought || !base ? payload.thought ?? "" : "");
  const content = payload.replaceContent ? contentDelta : `${base?.answerContent ?? ""}${contentDelta}`;
  const thought = payload.replaceThought ? thoughtDelta : `${base?.thoughtContent ?? ""}${thoughtDelta}`;
  const feedbackEvents = payload.feedbackEvents
    ? visibleFeedbackEvents(mergeAgentFeedbackEvents(base?.feedbackEvents, payload.feedbackEvents))
    : base?.feedbackEvents ?? [];
  const codexTranscript = payload.codexTranscript ?? base?.codexTranscript;
  if (!hasVisibleActiveTurnContent({
    answerContent: content,
    thoughtContent: thought,
    feedbackEvents,
    codexTranscript,
  })) {
    return undefined;
  }
  return {
    id: activeTurnMessageId(sessionId, turnId),
    sessionId,
    turnId,
    updatedAt: now,
    streaming: !payload.done,
    processStage: payload.stage || base?.processStage || undefined,
    answerContent: content,
    thoughtContent: thought,
    feedbackEvents,
    timelineItems: payload.timelineItems ?? base?.timelineItems,
    codexTranscript,
    ledgerSeq: Math.max(normalizedLedgerSeq(base?.ledgerSeq), normalizedLedgerSeq(payload.ledgerSeq)),
  };
}

export function activeTurnLayerToConversationMessage(
  layer: ActiveTurnLayerState | undefined,
): ConversationMessage | undefined {
  if (!layer) {
    return undefined;
  }
  return {
    id: layer.id,
    role: "assistant",
    content: layer.answerContent,
    timestamp: layer.updatedAt,
    streaming: layer.streaming,
    streamStage: layer.processStage,
    thought: layer.thoughtContent || undefined,
    feedbackEvents: layer.feedbackEvents.length > 0 ? layer.feedbackEvents : undefined,
    timelineItems: layer.timelineItems,
    codexTranscript: layer.codexTranscript,
    metadata: {
      kind: "session_active_turn_layer",
      sessionId: layer.sessionId,
      turnId: layer.turnId,
      ledgerSeq: layer.ledgerSeq,
    },
  };
}

export function activeTurnLayerTextLength(layer: ActiveTurnLayerState | undefined): number {
  return String(layer?.answerContent ?? "").length + String(layer?.thoughtContent ?? "").length;
}

export function isActiveTurnSettledByDetail(
  layer: ActiveTurnLayerState | undefined,
  detail: SessionDetail | undefined,
) {
  if (!layer || !detail) {
    return false;
  }
  const activeTurnId = layer.turnId;
  if (!activeTurnId) {
    return false;
  }
  return (detail.messages ?? []).some((message) => (
    message.role === "assistant"
    && String(message.metadata?.kind ?? "") !== "session_live_overlay"
    && String(message.metadata?.kind ?? "") !== "session_active_turn_layer"
    && messageTurnId(message) === activeTurnId
    && Boolean(String(answerProjectionContent(message) ?? "").trim())
  ));
}
