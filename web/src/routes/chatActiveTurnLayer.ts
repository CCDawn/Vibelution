import type {
  ConversationFeedbackEvent,
  ConversationMessage,
  SessionDetail,
  SessionStreamEvent,
} from "../api/types";

export type AssistantDeltaEvent = Extract<SessionStreamEvent, { type: "assistant_delta" }>;
export type ActiveTurnLayerMessage = ConversationMessage;

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

function feedbackEventKey(event: ConversationFeedbackEvent) {
  const sequence = Number(event.sequence ?? 0);
  if (Number.isFinite(sequence) && sequence > 0) {
    return `seq:${sequence}`;
  }
  return [
    event.kind ?? "",
    event.name ?? "",
    event.status ?? "",
    event.summary ?? "",
    event.resultPreview ?? "",
  ].join(":");
}

function mergeFeedbackEvents(
  previous: ConversationFeedbackEvent[] | undefined,
  incoming: ConversationFeedbackEvent[] | undefined,
) {
  if (!incoming) {
    return previous ?? [];
  }
  if (!incoming.length) {
    return [];
  }
  const merged = new Map<string, ConversationFeedbackEvent>();
  for (const event of previous ?? []) {
    merged.set(feedbackEventKey(event), event);
  }
  for (const event of incoming) {
    merged.set(feedbackEventKey(event), event);
  }
  return [...merged.values()].sort((left, right) => Number(left.sequence ?? 0) - Number(right.sequence ?? 0));
}

function messageTurnId(message: ConversationMessage) {
  const rawTurnId = String(message.metadata?.turnId ?? "");
  return rawTurnId.startsWith("live:") ? rawTurnId.slice("live:".length) : rawTurnId;
}

export function mergeAssistantDeltaIntoActiveTurnLayer(
  previous: ActiveTurnLayerMessage | undefined,
  payload: AssistantDeltaEvent,
): ActiveTurnLayerMessage | undefined {
  if (isStaleLedgerUpdate(previous?.metadata?.ledgerSeq, payload.ledgerSeq)) {
    return previous;
  }
  const sessionId = String(payload.sessionId || "").trim();
  const turnId = String(payload.turnId || "").trim();
  if (!sessionId) {
    return previous;
  }
  const now = payload.updatedAt || new Date().toISOString();
  const sameTurn = previous && messageTurnId(previous) === turnId;
  const base = sameTurn ? previous : undefined;
  const contentDelta = payload.contentDelta ?? (payload.replaceContent || !base ? payload.content ?? "" : "");
  const thoughtDelta = payload.thoughtDelta ?? (payload.replaceThought || !base ? payload.thought ?? "" : "");
  const content = payload.replaceContent ? contentDelta : `${base?.content ?? ""}${contentDelta}`;
  const thought = payload.replaceThought ? thoughtDelta : `${base?.thought ?? ""}${thoughtDelta}`;
  const feedbackEvents = mergeFeedbackEvents(base?.feedbackEvents, payload.feedbackEvents);
  if (!content && !thought && !payload.stage && !feedbackEvents.length) {
    return undefined;
  }
  return {
    id: activeTurnMessageId(sessionId, turnId),
    role: "assistant",
    content,
    timestamp: now,
    streaming: !payload.done,
    streamStage: payload.stage || undefined,
    thought: thought || undefined,
    feedbackEvents,
    timelineItems: payload.timelineItems ?? base?.timelineItems,
    metadata: {
      ...(base?.metadata ?? {}),
      kind: "session_active_turn_layer",
      sessionId,
      turnId,
      ledgerSeq: Math.max(normalizedLedgerSeq(base?.metadata?.ledgerSeq), normalizedLedgerSeq(payload.ledgerSeq)),
    },
  };
}

export function activeTurnLayerToConversationMessage(
  layer: ActiveTurnLayerMessage | undefined,
): ConversationMessage | undefined {
  return layer;
}

export function isActiveTurnSettledByDetail(
  layer: ActiveTurnLayerMessage | undefined,
  detail: SessionDetail | undefined,
) {
  if (!layer || !detail) {
    return false;
  }
  const activeTurnId = messageTurnId(layer);
  if (!activeTurnId) {
    return false;
  }
  return (detail.messages ?? []).some((message) => (
    message.role === "assistant"
    && String(message.metadata?.kind ?? "") !== "session_live_overlay"
    && String(message.metadata?.kind ?? "") !== "session_active_turn_layer"
    && messageTurnId(message) === activeTurnId
  ));
}
