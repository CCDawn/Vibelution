import { mergeConversationFeedbackEvents } from "../components/conversation/conversationFeedbackEvents";
import {
  answerProjectionContent,
  isInternalStreamingStatusContent,
  isInternalStreamingStatusStage,
} from "../components/conversation/conversationInternalStatus";
import type { ConversationMessage, SessionDetail, SessionStreamEvent } from "../api/types";

export type AssistantDeltaEvent = Extract<SessionStreamEvent, { type: "assistant_delta" }>;
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
    ? mergeConversationFeedbackEvents(base?.feedbackEvents, payload.feedbackEvents)
    : base?.feedbackEvents ?? [];
  if (!content && !thought && !payload.stage && !feedbackEvents.length) {
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
