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
  clientSubmissionId?: string;
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
  clientSubmissionId?: string;
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
    clientSubmissionId: compactText(input.clientSubmissionId) || undefined,
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
    renderKey: previous?.renderKey || activeTurnRenderKey(sessionId),
    clientSubmissionId: previous?.clientSubmissionId,
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
      clientSubmissionId: layer.clientSubmissionId,
      ledgerSeq: layer.ledgerSeq,
      processStage: layer.processStage,
      activeStatusSource: layer.ledgerSeq > 0 ? "assistant_delta" : "optimistic_submit",
    },
  };
}

export function activeTurnLayerTextLength(layer: ActiveTurnLayerState | undefined): number {
  return activeTurnProtocolTextLength({ turnItems: layer?.turnItems });
}

type RunningToolTurnItem = SessionTurnItem & { type: "tool_call" };

function runningToolPaintId(item: RunningToolTurnItem) {
  return compactText(item.callId) || compactText(item.itemId) || compactText(item.id);
}

export function runningToolStartedAtEpochMs(item: RunningToolTurnItem): number {
  const exactStart = Number(item.metadata?.executionStartedAtEpochMs);
  if (Number.isFinite(exactStart) && exactStart > 0) {
    return exactStart;
  }
  // `createdAt` can precede execution while the model is still streaming the
  // tool call.  The running revision's `updatedAt` is the canonical moment the
  // executor projected the start into the live turn layer, but remains only a
  // coarse fallback for legacy packets without the exact epoch value.
  return Date.parse(item.updatedAt || item.createdAt || "");
}

export function toolStartToFirstPaintMs(
  item: RunningToolTurnItem,
  firstPaintedAtEpochMs: number | undefined,
  observedAtEpochMs: number,
) {
  const toolStartEpochMs = runningToolStartedAtEpochMs(item);
  if (!Number.isFinite(toolStartEpochMs)) {
    return 0;
  }
  const firstPaintEpochMs = Number.isFinite(firstPaintedAtEpochMs)
    ? Number(firstPaintedAtEpochMs)
    : observedAtEpochMs;
  // `0` is reserved for "not measured". A row painted in the same
  // millisecond as (or just before) executor start is still an observed paint.
  return Math.max(1, Math.round(firstPaintEpochMs - toolStartEpochMs));
}

export function selectFirstUnpaintedRunningTool(
  layer: ActiveTurnLayerState | undefined,
  paintedToolIds: readonly string[],
): {
  tool: RunningToolTurnItem | undefined;
  toolId: string;
  tools: RunningToolTurnItem[];
  toolIds: string[];
  runningToolIds: string[];
} {
  const painted = new Set(paintedToolIds.map(compactText).filter(Boolean));
  const runningTools = (layer?.turnItems ?? []).filter((item): item is RunningToolTurnItem => (
    item.type === "tool_call" && (item.status === "pending" || item.status === "running")
  ));
  const runningToolIds = runningTools.map(runningToolPaintId).filter(Boolean);
  const tools = runningTools.filter((item) => {
    const id = runningToolPaintId(item);
    // A model-call placeholder can paint before the executor publishes the
    // canonical start revision.  Do not consume the one-shot measurement until
    // that revision carries a usable start time; otherwise the exact start
    // update is incorrectly treated as already painted.
    return Boolean(id)
      && !painted.has(id)
      && Number.isFinite(runningToolStartedAtEpochMs(item));
  });
  const toolIds = tools.map(runningToolPaintId).filter(Boolean);
  const tool = tools[0];
  return {
    tool,
    toolId: tool ? runningToolPaintId(tool) : "",
    tools,
    toolIds,
    runningToolIds,
  };
}

export function activeTurnTerminalRefreshKey(
  layer: ActiveTurnLayerState | undefined,
  detail?: SessionDetail,
) {
  if (!layer || !layer.turnId) {
    return "";
  }
  // A provider terminal frame can arrive before the canonical session summary
  // is persisted. Give the persisted detail its own later refresh key so the
  // directory cannot remain stuck on the earlier optimistic running summary.
  if (isActiveTurnSettledByDetail(layer, detail)) {
    return `${layer.turnId}:detail:${normalizedLedgerSeq(detail?.ledgerSeq)}`;
  }
  if (layer.status === "completed" || layer.status === "failed") {
    return `${layer.turnId}:${layer.status}:${layer.ledgerSeq}`;
  }
  return "";
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
