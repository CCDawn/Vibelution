import { activeTurnOptimisticStageSummary } from "../components/conversation/conversationActiveTurnStatusPresentation";
import type { ConversationMessage, SessionDetail, SessionStreamEvent, SessionTurnItem } from "../api/types";
import {
  activeTurnProtocolTextLength,
  consolidateSessionTurnItemsV2,
  hasCommittedAssistantProtocolAnswer,
  hasTerminalCanonicalTurnOutcome,
  hasVisibleActiveTurnProtocolContent,
} from "./chatTurnProtocol";

export type AssistantDeltaEvent = Extract<SessionStreamEvent, { type: "assistant_delta" }>;

export type ActiveTurnLayerState = {
  id: string;
  renderKey?: string;
  sessionId: string;
  turnId: string;
  updatedAt: string;
  status: "pending" | "running" | "completed" | "failed";
  processStage?: string;
  turnItems: SessionTurnItem[];
  ledgerSeq: number;
};

export type OptimisticActiveTurnLayerInput = {
  sessionId: string;
  turnId?: string;
  updatedAt?: string;
  summary?: string;
};

function compactText(value: unknown) {
  return String(value ?? "").trim();
}

function normalizedLedgerSeq(value: unknown): number {
  const numeric = Number(value ?? 0);
  return Number.isFinite(numeric) && numeric > 0 ? numeric : 0;
}

function activeTurnMessageId(sessionId: string, turnId: string) {
  return `${sessionId}-message-active-${turnId || "current"}`;
}

function activeTurnRenderKey(sessionId: string) {
  return `${sessionId}-active`;
}

function statusItem(input: {
  sessionId: string;
  turnId: string;
  updatedAt: string;
  stage: string;
  status: ActiveTurnLayerState["status"];
  summary: string;
}): SessionTurnItem {
  const itemId = `${input.sessionId}:${input.turnId}:status:${input.stage || "running"}`;
  return {
    id: `${itemId}:0`,
    itemId,
    version: 3,
    sessionId: input.sessionId,
    turnId: input.turnId,
    type: "status",
    code: input.stage || "running",
    text: input.summary,
    summary: input.summary,
    status: input.status,
    revision: 0,
    sequence: 0,
    createdAt: input.updatedAt,
    updatedAt: input.updatedAt,
    terminal: input.status === "completed" || input.status === "failed",
  };
}

export function createOptimisticActiveTurnLayer(
  input: OptimisticActiveTurnLayerInput,
): ActiveTurnLayerState | undefined {
  const sessionId = compactText(input.sessionId);
  if (!sessionId) return undefined;
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
    status: "pending",
    processStage,
    turnItems: [statusItem({ sessionId, turnId, updatedAt, stage: processStage, status: "pending", summary })],
    ledgerSeq: 0,
  };
}

export function setActiveTurnLayerForSession(
  current: Record<string, ActiveTurnLayerState>,
  sessionId: string,
  layer: ActiveTurnLayerState | undefined,
) {
  const normalizedSessionId = compactText(sessionId);
  if (!normalizedSessionId) return current;
  if (!layer) {
    if (!current[normalizedSessionId]) return current;
    const next = { ...current };
    delete next[normalizedSessionId];
    return next;
  }
  return current[normalizedSessionId] === layer ? current : { ...current, [normalizedSessionId]: layer };
}

export function latestUserTurnId(detail: SessionDetail | undefined) {
  const messages = detail?.messages ?? [];
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message?.role !== "user") continue;
    const turnId = compactText(message.metadata?.turnId ?? message.metadata?.turn_id);
    if (turnId) return turnId.startsWith("live:") ? turnId.slice("live:".length) : turnId;
  }
  return "";
}

/** Every stream frame is a replacement/revision of turn items; no parallel text rail exists. */
export function mergeAssistantDeltaIntoActiveTurnLayer(
  previous: ActiveTurnLayerState | undefined,
  payload: AssistantDeltaEvent,
): ActiveTurnLayerState | undefined {
  const sessionId = compactText(payload.sessionId);
  const turnId = compactText(payload.turnId);
  if (!sessionId) return previous;
  const incomingLedgerSeq = normalizedLedgerSeq(payload.ledgerSeq);
  if (previous && previous.ledgerSeq > 0 && incomingLedgerSeq > 0 && incomingLedgerSeq < previous.ledgerSeq) {
    return previous;
  }
  const sameTurn = previous?.turnId === turnId;
  const base = sameTurn ? previous : undefined;
  const updatedAt = compactText(payload.updatedAt) || new Date().toISOString();
  const stage = compactText(payload.stage) || base?.processStage || "running";
  const status: ActiveTurnLayerState["status"] = payload.done ? "completed" : "running";
  const turnItems = consolidateSessionTurnItemsV2(base?.turnItems, payload.turnItems);
  const withStatus = turnItems.length > 0
    ? turnItems
    : [statusItem({
        sessionId,
        turnId,
        updatedAt,
        stage,
        status,
        summary: activeTurnOptimisticStageSummary(stage, "zh"),
      })];
  if (payload.done && !hasVisibleActiveTurnProtocolContent({ turnItems: withStatus })) return undefined;
  return {
    id: activeTurnMessageId(sessionId, turnId),
    renderKey: base?.renderKey || activeTurnRenderKey(sessionId),
    sessionId,
    turnId,
    updatedAt,
    status,
    processStage: stage,
    turnItems: withStatus,
    ledgerSeq: Math.max(base?.ledgerSeq ?? 0, incomingLedgerSeq),
  };
}

export function activeTurnLayerToConversationMessage(
  layer: ActiveTurnLayerState | undefined,
): ConversationMessage | undefined {
  if (!layer) return undefined;
  return {
    id: layer.id,
    role: "assistant",
    timestamp: layer.updatedAt,
    turnId: layer.turnId,
    status: layer.status,
    turnItems: layer.turnItems,
    metadata: {
      kind: "session_active_turn_layer",
      sessionId: layer.sessionId,
      renderKey: layer.renderKey || activeTurnRenderKey(layer.sessionId),
      ledgerSeq: layer.ledgerSeq,
    },
  };
}

export function activeTurnLayerTextLength(layer: ActiveTurnLayerState | undefined): number {
  return activeTurnProtocolTextLength({ turnItems: layer?.turnItems });
}

export function isActiveTurnSettledByDetail(
  layer: ActiveTurnLayerState | undefined,
  detail: SessionDetail | undefined,
) {
  if (!layer || !detail || !layer.turnId) return false;
  return (detail.messages ?? []).some((message) => (
    message.role === "assistant"
    && message.turnId === layer.turnId
    && message.metadata?.kind !== "session_active_turn_layer"
    && (hasTerminalCanonicalTurnOutcome(message) || hasCommittedAssistantProtocolAnswer(message))
  ));
}

export function settleActiveTurnLayerFromDetail(
  layer: ActiveTurnLayerState | undefined,
  detail: SessionDetail | undefined,
): ActiveTurnLayerState | undefined {
  return isActiveTurnSettledByDetail(layer, detail) ? undefined : layer;
}
