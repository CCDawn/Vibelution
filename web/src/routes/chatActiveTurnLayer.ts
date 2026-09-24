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

export function createOptimisticActiveTurnLayer(
  input: OptimisticActiveTurnLayerInput,
): ActiveTurnLayerState | undefined {
  const sessionId = compactText(input.sessionId);
  if (!sessionId) return undefined;
  const turnId = compactText(input.turnId) || "optimistic";
  const updatedAt = compactText(input.updatedAt) || new Date().toISOString();
  // Optimistic layer keeps processStage + pending status; do not seed status-only
  // turnItems as a fake package (turnItems remain the answer SSOT).
  return {
    id: activeTurnMessageId(sessionId, turnId),
    renderKey: activeTurnRenderKey(sessionId),
    clientSubmissionId: compactText(input.clientSubmissionId) || undefined,
    sessionId,
    turnId,
    updatedAt,
    status: "pending",
    processStage: "user_submit",
    turnItems: [],
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
  // Empty after merge: keep processStage on the layer; do not inject a status-only TurnItem.
  if (payload.done && !hasVisibleActiveTurnProtocolContent({ turnItems })) return undefined;
  return {
    id: activeTurnMessageId(sessionId, turnId),
    renderKey: previous?.renderKey || activeTurnRenderKey(sessionId),
    clientSubmissionId: previous?.clientSubmissionId,
    sessionId,
    turnId,
    updatedAt,
    status,
    processStage: stage,
    turnItems,
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

export function runningToolPaintKeys(layer: ActiveTurnLayerState | undefined) {
  const occurrences = new Map<string, number>();
  let toolOrdinal = 0;
  return (layer?.turnItems ?? []).flatMap((item) => {
    if (item.type !== "tool_call") {
      return [];
    }
    const toolName = compactText(item.toolName) || "tool";
    const occurrence = occurrences.get(toolName) ?? 0;
    occurrences.set(toolName, occurrence + 1);
    const ordinalKey = `tool-ordinal:${toolOrdinal}`;
    toolOrdinal += 1;
    if (item.status !== "pending" && item.status !== "running") {
      return [];
    }
    return [{
      toolId: runningToolPaintId(item),
      fallbackKey: `tool:${toolName}:${occurrence}`,
      ordinalKey,
    }];
  });
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
  const paintKeysByToolId = new Map(
    runningToolPaintKeys(layer).map(({ toolId, fallbackKey, ordinalKey }) => [
      toolId,
      [fallbackKey, ordinalKey],
    ]),
  );
  const runningTools = (layer?.turnItems ?? []).filter((item): item is RunningToolTurnItem => (
    item.type === "tool_call" && (item.status === "pending" || item.status === "running")
  ));
  const runningToolIds = runningTools.map(runningToolPaintId).filter(Boolean);
  const tools = runningTools.filter((item) => {
    const id = runningToolPaintId(item);
    const fallbackKeys = paintKeysByToolId.get(id) ?? [];
    // A model-call placeholder can paint before the executor publishes the
    // canonical start revision.  Do not consume the one-shot measurement until
    // that revision carries a usable start time; otherwise the exact start
    // update is incorrectly treated as already painted.
    return Boolean(id)
      && !painted.has(id)
      && fallbackKeys.every((key) => !painted.has(key))
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
  return isActiveTurnSettledByMessages(layer, detail?.messages);
}

/**
 * Settle projection over the message window alone: consumers that only hold
 * `detail.messages` (streaming-layer projection) share the exact rule without
 * needing the full detail object.
 */
export function isActiveTurnSettledByMessages(
  layer: ActiveTurnLayerState | undefined,
  messages: ConversationMessage[] | undefined,
) {
  if (!layer || !messages || !layer.turnId) return false;
  const layerUpdatedAt = Date.parse(layer.updatedAt);
  return messages.some((message) => {
    if (
      message.role !== "assistant"
      || message.metadata?.kind === "session_active_turn_layer"
      || (!hasTerminalCanonicalTurnOutcome(message) && !hasCommittedAssistantProtocolAnswer(message))
    ) {
      return false;
    }
    if (message.turnId === layer.turnId) {
      return true;
    }
    const messageTimestamp = Date.parse(message.timestamp);
    // A session has only one executing turn at a time. Once a different,
    // newer assistant turn has committed, an older live layer cannot still be
    // the active turn; keeping it would append stale process UI after the new
    // answer. Invalid or equal timestamps fail closed to the exact-turn rule.
    return Number.isFinite(layerUpdatedAt)
      && Number.isFinite(messageTimestamp)
      && messageTimestamp > layerUpdatedAt;
  });
}

/**
 * The one ConversationView-facing projection of a live active-turn layer:
 * settled layers hide the streaming message (the canonical transcript is the
 * authority), everything else renders as the in-flight assistant message.
 */
export function projectActiveTurnLayerMessage(
  layer: ActiveTurnLayerState | undefined,
  messages: ConversationMessage[] | undefined,
): ConversationMessage | undefined {
  return isActiveTurnSettledByMessages(layer, messages)
    ? undefined
    : activeTurnLayerToConversationMessage(layer);
}

export function settleActiveTurnLayerFromDetail(
  layer: ActiveTurnLayerState | undefined,
  detail: SessionDetail | undefined,
): ActiveTurnLayerState | undefined {
  return isActiveTurnSettledByDetail(layer, detail) ? undefined : layer;
}

type OverlayReconcileItem = {
  type: string;
  itemKey: string;
  revision: number;
};

function overlayItemIdentity(item: SessionTurnItem): OverlayReconcileItem {
  const itemKey = compactText(
    ("callId" in item && item.callId)
    || ("itemId" in item && item.itemId)
    || ("id" in item && item.id)
    || "",
  );
  const revision = Number(item.revision ?? 0);
  return {
    type: compactText(item.type),
    itemKey,
    revision: Number.isFinite(revision) && revision > 0 ? revision : 0,
  };
}

function overlayItemSortKey(item: OverlayReconcileItem) {
  return `${item.type}\u001f${item.itemKey}`;
}

/**
 * Per-item reconciliation between the optimistic/active overlay and the
 * authoritative projection (pattern: zai-org/ZCode conversationProjectionStore,
 * Apache-2.0 — refined from whole-turn settlement to item granularity).
 *
 * An overlay turn item is dropped once the canonical transcript carries an
 * item with the same identity (type + call/item id) at an equal or newer
 * revision: the authoritative copy paints instead of a duplicated overlay
 * copy, while items the authority has not committed yet keep rendering from
 * the overlay. An overlay with nothing left to show is cleared entirely
 * (same contract as the whole-turn settle path).
 */
export function reconcileActiveTurnLayerItemsWithMessages(
  layer: ActiveTurnLayerState | undefined,
  messages: ConversationMessage[] | undefined,
): ActiveTurnLayerState | undefined {
  if (!layer || !layer.turnId || !messages?.length || !layer.turnItems.length) {
    return layer;
  }
  const authoritative = new Map<string, number>();
  for (const message of messages) {
    if (message.role !== "assistant") continue;
    if (message.metadata?.kind === "session_active_turn_layer") continue;
    if (String(message.turnId || "").trim() !== layer.turnId) continue;
    for (const item of message.turnItems ?? []) {
      const identity = overlayItemIdentity(item);
      if (!identity.itemKey) continue;
      const sortKey = overlayItemSortKey(identity);
      authoritative.set(sortKey, Math.max(authoritative.get(sortKey) ?? 0, identity.revision));
    }
  }
  if (authoritative.size === 0) {
    return layer;
  }
  let removed = 0;
  const remainingItems = layer.turnItems.filter((item) => {
    const identity = overlayItemIdentity(item);
    if (!identity.itemKey) {
      return true;
    }
    const authoritativeRevision = authoritative.get(overlayItemSortKey(identity));
    if (authoritativeRevision === undefined) {
      return true;
    }
    // Equal revision means the authority committed exactly this item; a newer
    // authority revision supersedes the overlay copy outright.
    if (identity.revision <= authoritativeRevision) {
      removed += 1;
      return false;
    }
    return true;
  });
  if (removed === 0) {
    return layer;
  }
  // Fully reconciled but not yet settled turns keep their (now empty) overlay
  // shell so stage/status UI survives until the canonical transcript settles
  // the turn through the whole-layer path.
  return { ...layer, turnItems: remainingItems };
}
