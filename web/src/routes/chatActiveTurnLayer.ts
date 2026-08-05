import { mergeAgentFeedbackEvents } from "../agent-thread/agentFeedbackEvents";
import {
  isInternalStreamingStatusContent,
  isInternalStreamingStatusStage,
} from "../components/conversation/conversationInternalStatus";
import { activeTurnOptimisticStageSummary } from "../components/conversation/conversationActiveTurnStatusPresentation";
import { shouldDisplayRuntimeStatus } from "../components/conversation/conversationDisplayProtocol";
import type { ConversationMessage, SessionDetail, SessionStreamEvent } from "../api/types";
import {
  activeTurnProtocolTextLength,
  consolidateSessionTurnItemsV2,
  hasCommittedAssistantProtocolAnswer,
  hasTerminalCanonicalTurnOutcome,
  hasVisibleActiveTurnProtocolContent,
  projectConversationMessageFromTurnItemsV2,
  resolveAssistantTurnRenderSurface,
} from "./chatTurnProtocol";
import type { SessionTurnItem } from "../api/types/chat";

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

function isFinalAnswerTurnItem(item: SessionTurnItem) {
  const kind = compactText(item.kind || item.type).toLowerCase();
  const phase = compactText(item.phase).toLowerCase();
  const channel = compactText(item.channel).toLowerCase();
  return (
    phase === "final_answer"
    || (
      (kind === "assistant_message" || kind === "agent_message")
      && (channel === "answer" || !channel)
      && phase !== "commentary"
      && phase !== "interim"
    )
  );
}

/**
 * Phase B: keep provisional final item text aligned with streaming legacy content
 * when a delta frame updates content faster than the turnItems snapshot.
 */
export function reconcileTurnItemsWithStreamingContent(
  turnItems: SessionTurnItem[] | undefined,
  streamingContent: string,
): SessionTurnItem[] {
  const items = consolidateSessionTurnItemsV2(turnItems);
  const content = compactText(streamingContent);
  if (items.length === 0 || !content) {
    return items;
  }
  const finalIndex = items.findIndex((item) => isFinalAnswerTurnItem(item));
  if (finalIndex < 0) {
    return items;
  }
  const finalItem = items[finalIndex];
  const itemText = compactText(finalItem.text);
  const isProvisionalFinal = (
    finalItem.provisional === true
    || finalItem.terminal !== true
    || ["pending", "running", "in_progress", "streaming"].includes(compactText(finalItem.status).toLowerCase())
  );
  if (
    isProvisionalFinal
    && content.length > itemText.length
    && (itemText.length === 0 || content.startsWith(itemText) || content.includes(itemText))
  ) {
    const next = items.slice();
    next[finalIndex] = {
      ...finalItem,
      text: content,
      status: finalItem.status === "completed" ? finalItem.status : "in_progress",
      provisional: finalItem.terminal === true ? finalItem.provisional : true,
    };
    return next;
  }
  return items;
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
  const processStage = "user_submit";
  const summary = compactText(input.summary) || activeTurnOptimisticStageSummary(processStage, "zh");
  return {
    id: activeTurnMessageId(sessionId, turnId),
    renderKey: activeTurnRenderKey(sessionId),
    sessionId,
    turnId,
    updatedAt,
    streaming: true,
    processStage,
    answerContent: "",
    thoughtContent: "",
    feedbackEvents: [
      {
        sequence: 1,
        kind: "status",
        status: "running",
        name: processStage,
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
  }, { surface: "active" })) {
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
  // Phase B: turnItems are the active-turn draft package. Prefer consolidating
  // item identity over parallel content/transcript authority.
  const consolidatedItems = consolidateSessionTurnItemsV2(base?.turnItems, payload.turnItems);
  const turnItems = reconcileTurnItemsWithStreamingContent(consolidatedItems, legacyContent);
  const hasTurnItemPackage = turnItems.length > 0;
  let content = legacyContent;
  let thought = legacyThought;
  let codexTranscript = payload.codexTranscript ?? base?.codexTranscript;
  if (hasTurnItemPackage) {
    // Phase B: turnItems package owns answer + derived transcript.
    const renderSurface = resolveAssistantTurnRenderSurface({
      answerProjectionContent: legacyContent,
      thoughtContent: legacyThought,
      feedbackEvents,
      turnItems,
    });
    content = compactText(renderSurface.answerContent)
      ? renderSurface.answerContent
      : legacyContent;
    thought = compactText(renderSurface.thoughtContent)
      ? renderSurface.thoughtContent
      : legacyThought;
    codexTranscript = renderSurface.codexTranscript ?? codexTranscript;
  }
  const hasVisibleContent = hasVisibleActiveTurnProtocolContent({
    answerContent: content,
    thoughtContent: thought,
    feedbackEventCount: feedbackEvents.length,
    codexTranscript,
    turnItems: hasTurnItemPackage ? turnItems : undefined,
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
    turnItems: hasTurnItemPackage ? turnItems : undefined,
    ledgerSeq: Math.max(normalizedLedgerSeq(base?.ledgerSeq), normalizedLedgerSeq(payload.ledgerSeq)),
  };
}

export function activeTurnLayerToConversationMessage(
  layer: ActiveTurnLayerState | undefined,
): ConversationMessage | undefined {
  if (!layer) {
    return undefined;
  }
  const message: ConversationMessage = {
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
  // Project content + codexTranscript from turnItems when the package is present.
  return projectConversationMessageFromTurnItemsV2(message);
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
  return (detail.messages ?? []).some((message) => {
    if (
      message.role !== "assistant"
      || String(message.metadata?.kind ?? "") === "session_live_overlay"
      || String(message.metadata?.kind ?? "") === "session_active_turn_layer"
      || messageTurnId(message) !== activeTurnId
    ) {
      return false;
    }
    // Prefer a committed turnItems package when detail carries v2 items.
    if (hasTerminalCanonicalTurnOutcome(message) || hasCommittedAssistantProtocolAnswer(message)) {
      return true;
    }
    return false;
  });
}

/**
 * When detail settles the active turn, drop the live layer so detail messages
 * (with turnItems package) become the only visible authority.
 */
export function settleActiveTurnLayerFromDetail(
  layer: ActiveTurnLayerState | undefined,
  detail: SessionDetail | undefined,
): ActiveTurnLayerState | undefined {
  if (!layer) {
    return undefined;
  }
  if (isActiveTurnSettledByDetail(layer, detail)) {
    return undefined;
  }
  return layer;
}
