import { mergeAgentFeedbackEvents } from "../agent-thread/agentFeedbackEvents";
import {
  isInternalStreamingStatusContent,
  isInternalStreamingStatusStage,
} from "../components/conversation/conversationInternalStatus";
import { shouldDisplayRuntimeStatus } from "../components/conversation/conversationDisplayProtocol";
import type { ConversationMessage, SessionDetail, SessionStreamEvent } from "../api/types";
import {
  activeTurnProtocolTextLength,
  consolidateSessionTurnItemsV2,
  hasCommittedAssistantProtocolAnswer,
  hasTerminalCanonicalTurnOutcome,
  hasVisibleActiveTurnProtocolContent,
  resolveAssistantTurnRenderSurface,
} from "./chatTurnProtocol";

export type AssistantDeltaEvent = Extract<SessionStreamEvent, { type: "assistant_delta" }>;
type ConversationFeedbackEvent = NonNullable<ConversationMessage["feedbackEvents"]>[number];
export type ActiveTurnLayerState = {
  id: string;
  renderKey?: string;
  sessionId: string;
  turnId: string;
  updatedAt: string;
  streaming: boolean;
  processStage?: string;
  answerContent: string;
  thoughtContent: string;
  turnItems?: ConversationMessage["turnItems"];
  feedbackEvents: NonNullable<ConversationMessage["feedbackEvents"]>;
  timelineItems?: ConversationMessage["timelineItems"];
  codexTranscript?: ConversationMessage["codexTranscript"];
  ledgerSeq: number;
};

export type OptimisticActiveTurnLayerInput = {
  sessionId: string;
  turnId?: string;
  updatedAt?: string;
  summary?: string;
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

function activeTurnRenderKey(sessionId: string) {
  return `${sessionId}-active`;
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

export function createOptimisticActiveTurnLayer(
  input: OptimisticActiveTurnLayerInput,
): ActiveTurnLayerState | undefined {
  const sessionId = compactText(input.sessionId);
  if (!sessionId) {
    return undefined;
  }
  const turnId = compactText(input.turnId) || "optimistic";
  const updatedAt = compactText(input.updatedAt) || new Date().toISOString();
  const summary = compactText(input.summary) || "已发送，正在连接 Agent";
  return {
    id: activeTurnMessageId(sessionId, turnId),
    renderKey: activeTurnRenderKey(sessionId),
    sessionId,
    turnId,
    updatedAt,
    streaming: true,
    processStage: "user_submit",
    answerContent: "",
    thoughtContent: "",
    feedbackEvents: [
      {
        sequence: 1,
        kind: "status",
        status: "running",
        name: "user_submit",
        summary,
      },
    ],
    ledgerSeq: 0,
  };
}

export function setActiveTurnLayerForSession(
  current: Record<string, ActiveTurnLayerState>,
  sessionId: string,
  layer: ActiveTurnLayerState | undefined,
) {
  const normalizedSessionId = String(sessionId || "").trim();
  if (!normalizedSessionId) {
    return current;
  }
  if (!layer) {
    if (!current[normalizedSessionId]) {
      return current;
    }
    const next = { ...current };
    delete next[normalizedSessionId];
    return next;
  }
  if (current[normalizedSessionId] === layer) {
    return current;
  }
  return {
    ...current,
    [normalizedSessionId]: layer,
  };
}

export function latestUserTurnId(detail: SessionDetail | undefined) {
  const messages = detail?.messages ?? [];
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message?.role !== "user") {
      continue;
    }
    const turnId = String(message.metadata?.turnId ?? message.metadata?.turn_id ?? "").trim();
    if (turnId) {
      return turnId.startsWith("live:") ? turnId.slice("live:".length) : turnId;
    }
  }
  return "";
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
  const legacyContent = payload.replaceContent ? contentDelta : `${base?.answerContent ?? ""}${contentDelta}`;
  const legacyThought = payload.replaceThought ? thoughtDelta : `${base?.thoughtContent ?? ""}${thoughtDelta}`;
  const feedbackEvents = payload.feedbackEvents
    ? visibleFeedbackEvents(mergeAgentFeedbackEvents(base?.feedbackEvents, payload.feedbackEvents))
    : base?.feedbackEvents ?? [];
  const turnItems = consolidateSessionTurnItemsV2(base?.turnItems, payload.turnItems);
  const canonicalSurface = turnItems.length > 0
    ? resolveAssistantTurnRenderSurface({
      answerProjectionContent: legacyContent,
      thoughtContent: legacyThought,
      feedbackEvents,
      codexTranscript: payload.codexTranscript ?? base?.codexTranscript,
      turnItems,
    })
    : undefined;
  const content = compactText(canonicalSurface?.answerContent) ? canonicalSurface!.answerContent : legacyContent;
  const thought = compactText(canonicalSurface?.thoughtContent) ? canonicalSurface!.thoughtContent : legacyThought;
  const codexTranscript = canonicalSurface?.codexTranscript ?? payload.codexTranscript ?? base?.codexTranscript;
  const hasVisibleContent = hasVisibleActiveTurnProtocolContent({
    answerContent: content,
    thoughtContent: thought,
    feedbackEventCount: feedbackEvents.length,
    codexTranscript,
    turnItems,
  });
  if (!hasVisibleContent && payload.done) {
    return undefined;
  }
  return {
    id: activeTurnMessageId(sessionId, turnId),
    renderKey: base?.renderKey || activeTurnRenderKey(sessionId),
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
    turnItems: turnItems.length > 0 ? turnItems : undefined,
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
    turnItems: layer.turnItems,
    metadata: {
      kind: "session_active_turn_layer",
      sessionId: layer.sessionId,
      turnId: layer.turnId,
      renderKey: layer.renderKey || activeTurnRenderKey(layer.sessionId),
      ledgerSeq: layer.ledgerSeq,
    },
  };
}

export function activeTurnLayerTextLength(layer: ActiveTurnLayerState | undefined): number {
  return activeTurnProtocolTextLength({
    answerContent: layer?.answerContent,
    thoughtContent: layer?.thoughtContent,
    codexTranscript: layer?.codexTranscript,
    turnItems: layer?.turnItems,
  });
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
    && (
      hasCommittedAssistantProtocolAnswer(message)
      || hasTerminalCanonicalTurnOutcome(message)
    )
  ));
}
