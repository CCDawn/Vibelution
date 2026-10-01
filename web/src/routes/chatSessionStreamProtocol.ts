import type {
  SessionAssistantDeltaStreamEvent,
  SessionStreamAppendEntry,
  SessionStreamEvent,
  SessionTurnItem,
} from "../api/types";
import { shouldAcceptSessionStreamEvent } from "./chatSessionState";
import {
  consolidateSessionTurnItemsV2,
  resolveAssistantTurnRenderProtocol,
  type ChatTurnRenderProtocol,
} from "./chatTurnProtocol";

// Pure SSE router: keep parsing, session/type rejection, and protocol tracing out of React state code.
export type SessionStreamEventType = SessionStreamEvent["type"];
export type SessionStreamEventForType<T extends SessionStreamEventType> = Extract<SessionStreamEvent, { type: T }>;
type SessionAssistantDeltaStreamPayload = SessionAssistantDeltaStreamEvent;

export type SessionStreamProtocolEventRoute =
  | "session_detail"
  | "session_initial"
  | "assistant_delta"
  | "session_journal_event"
  | "stream_resume"
  | "rejected";

export type SessionStreamProtocolRejectReason =
  | "parse_error"
  | "session_mismatch"
  | "event_type_mismatch";

export type SessionStreamProtocolTrace = {
  expectedType: SessionStreamEventType;
  actualType: SessionStreamEventType | "unparseable" | "unknown";
  eventRoute: SessionStreamProtocolEventRoute;
  turnRenderProtocol?: ChatTurnRenderProtocol;
  rejectReason?: SessionStreamProtocolRejectReason;
  payloadLength: number;
  sessionId: string;
  ledgerSeq: number;
  /** Journal sequence from the SSE id: line (Last-Event-ID resume cursor). */
  sseEventId: number;
  turnId: string;
  itemId: string;
  turnItemCount: number;
  turnItemAppendCount: number;
  finalAnswerItemCount: number;
  commentaryItemCount: number;
  toolItemCount: number;
  terminalErrorItemCount: number;
  stage: string;
  done: boolean;
};

export type AcceptedSessionStreamProtocolRoute<T extends SessionStreamEventType> = {
  accepted: true;
  payload: SessionStreamEventForType<T>;
  trace: SessionStreamProtocolTrace;
};

export type RejectedSessionStreamProtocolRoute = {
  accepted: false;
  payload?: SessionStreamEvent;
  trace: SessionStreamProtocolTrace;
};

export type SessionStreamProtocolRoute<T extends SessionStreamEventType> =
  | AcceptedSessionStreamProtocolRoute<T>
  | RejectedSessionStreamProtocolRoute;

export type RouteSessionStreamEventInput<T extends SessionStreamEventType> = {
  activeSessionId: string | null | undefined;
  expectedType: T;
  rawData: string;
  /** Journal sequence from the SSE frame's id: line, when the transport saw one. */
  eventId?: string | number | null;
};

export function routeSessionStreamEvent<T extends SessionStreamEventType>(
  input: RouteSessionStreamEventInput<T>,
): SessionStreamProtocolRoute<T> {
  let payload: SessionStreamEvent;
  try {
    payload = JSON.parse(input.rawData) as SessionStreamEvent;
  } catch {
    return {
      accepted: false,
      trace: rejectedTrace(input, undefined, "parse_error", "unparseable"),
    };
  }

  if (!shouldAcceptSessionStreamEvent(payload, input.activeSessionId)) {
    return {
      accepted: false,
      payload,
      trace: rejectedTrace(input, payload, "session_mismatch", eventType(payload)),
    };
  }

  if (payload.type !== input.expectedType) {
    return {
      accepted: false,
      payload,
      trace: rejectedTrace(input, payload, "event_type_mismatch", eventType(payload)),
    };
  }

  return {
    accepted: true,
    payload: payload as SessionStreamEventForType<T>,
    trace: acceptedTrace(input, payload as SessionStreamEventForType<T>),
  };
}

export function sessionStreamProtocolTelemetryFields(trace: SessionStreamProtocolTrace) {
  return {
    streamExpectedType: trace.expectedType,
    streamActualType: trace.actualType,
    streamEventRoute: trace.eventRoute,
    turnRenderProtocol: trace.turnRenderProtocol ?? "",
    streamRejectReason: trace.rejectReason ?? "",
    streamPayloadLength: trace.payloadLength,
    streamLedgerSeq: trace.ledgerSeq,
    streamSseEventId: trace.sseEventId,
    streamTurnId: trace.turnId,
    streamItemId: trace.itemId,
    streamTurnItemCount: trace.turnItemCount,
    streamTurnItemAppendCount: trace.turnItemAppendCount,
    streamFinalAnswerItemCount: trace.finalAnswerItemCount,
    streamCommentaryItemCount: trace.commentaryItemCount,
    streamToolItemCount: trace.toolItemCount,
    streamTerminalErrorItemCount: trace.terminalErrorItemCount,
    streamStage: trace.stage,
    streamDone: trace.done,
  };
}

function acceptedTrace<T extends SessionStreamEventType>(
  input: RouteSessionStreamEventInput<T>,
  payload: SessionStreamEventForType<T>,
): SessionStreamProtocolTrace {
  return {
    ...baseTrace(input, payload, eventType(payload)),
    eventRoute: payload.type,
    turnRenderProtocol: payload.type === "assistant_delta"
      ? resolveAssistantDeltaProtocol(payload as SessionAssistantDeltaStreamPayload)
      : undefined,
  };
}

function rejectedTrace<T extends SessionStreamEventType>(
  input: RouteSessionStreamEventInput<T>,
  payload: SessionStreamEvent | undefined,
  rejectReason: SessionStreamProtocolRejectReason,
  actualType: SessionStreamProtocolTrace["actualType"],
): SessionStreamProtocolTrace {
  return {
    ...baseTrace(input, payload, actualType),
    eventRoute: "rejected",
    rejectReason,
  };
}

function baseTrace<T extends SessionStreamEventType>(
  input: RouteSessionStreamEventInput<T>,
  payload: SessionStreamEvent | undefined,
  actualType: SessionStreamProtocolTrace["actualType"],
): Omit<SessionStreamProtocolTrace, "eventRoute"> {
  const assistantPayload = payload?.type === "assistant_delta" ? payload : undefined;
  const itemCounts = canonicalItemCounts(assistantPayload?.turnItems);
  const seqCarrier = payload as { ledgerSeq?: number; seq?: number; toSeq?: number } | undefined;
  return {
    expectedType: input.expectedType,
    actualType,
    payloadLength: input.rawData.length,
    sessionId: String(payload?.sessionId ?? input.activeSessionId ?? ""),
    // assistant_delta carries ledgerSeq; journal replays carry seq; the resume
    // marker's watermark is toSeq. All three are the same journal counter.
    ledgerSeq: normalizedNumber(seqCarrier?.ledgerSeq ?? seqCarrier?.seq ?? seqCarrier?.toSeq),
    sseEventId: normalizedNumber(input.eventId),
    turnId: String(assistantPayload?.turnId ?? ""),
    itemId: String(assistantPayload?.turnItems?.[0]?.itemId ?? ""),
    turnItemCount: Array.isArray(assistantPayload?.turnItems) ? assistantPayload.turnItems.length : 0,
    turnItemAppendCount: Array.isArray(assistantPayload?.turnItemAppends) ? assistantPayload.turnItemAppends.length : 0,
    ...itemCounts,
    stage: String(assistantPayload?.stage ?? ""),
    done: Boolean(assistantPayload?.done),
  };
}

export function canonicalItemCounts(items: SessionAssistantDeltaStreamEvent["turnItems"] | undefined) {
  const canonical = consolidateSessionTurnItemsV2(items);
  return {
    finalAnswerItemCount: canonical.filter(
      (item) => item.type === "agent_message" && item.phase === "final_answer",
    ).length,
    commentaryItemCount: canonical.filter((item) => item.type === "agent_message" && item.phase === "commentary").length,
    toolItemCount: canonical.filter((item) => item.type === "tool_call").length,
    terminalErrorItemCount: canonical.filter(
      (item) => item.type === "error" && item.terminal === true,
    ).length,
  };
}

function eventType(payload: SessionStreamEvent | undefined): SessionStreamProtocolTrace["actualType"] {
  const type = String(payload?.type ?? "").trim();
  return type === "session_detail"
    || type === "session_initial"
    || type === "assistant_delta"
    || type === "session_journal_event"
    || type === "stream_resume"
    ? type
    : "unknown";
}

function resolveAssistantDeltaProtocol(payload: SessionAssistantDeltaStreamPayload) {
  return resolveAssistantTurnRenderProtocol({
    turnItems: payload.turnItems,
  });
}

function normalizedNumber(value: unknown) {
  const numeric = Number(value ?? 0);
  return Number.isFinite(numeric) ? numeric : 0;
}

const APPENDABLE_STREAM_ITEM_TYPES = new Set(["agent_message", "reasoning"]);

function itemText(item: SessionTurnItem): string {
  return "text" in item && typeof item.text === "string" ? item.text : "";
}

/** Why an append fragment could not splice onto the cached item. */
export type SessionStreamAppendGapReason = "unknown_item" | "length_mismatch" | "empty_text";

export type SessionStreamAppendGap = {
  itemId: string;
  baseLength: number;
  reason: SessionStreamAppendGapReason;
};

export type SessionStreamAppendExpansion = {
  /** Legacy-shaped delta: appends spliced into full turnItems, ready to apply. */
  payload: SessionAssistantDeltaStreamEvent;
  /** Non-empty when the append chain broke; the consumer must resnapshot. */
  gaps: SessionStreamAppendGap[];
};

/**
 * Connection-scoped reassembler for the append-only turn item channel
 * (protocol: `assistant_delta.turnItemAppends`, BE write edge
 * `SessionStreamItemDelta`). Full rows seed the per-item text cache exactly as
 * delivered; append fragments splice onto the cached text only when the cached
 * length equals `baseLength`. Any breakage is reported instead of guessed, so
 * the consumer can fall back to an authoritative snapshot + stream reconnect
 * (a fresh connection restarts the server cursor at full snapshots).
 */
export function createSessionStreamAppendReassembler() {
  let turnKey = "";
  const itemsByTextId = new Map<string, SessionTurnItem>();

  function reset(): void {
    itemsByTextId.clear();
  }

  function expand(payload: SessionAssistantDeltaStreamEvent): SessionStreamAppendExpansion {
    const nextTurnKey = `${payload.sessionId}\u001f${payload.turnId}`;
    if (nextTurnKey !== turnKey) {
      turnKey = nextTurnKey;
      reset();
    }
    // Full rows are the authority: seed/replace the cache before splicing.
    const fullRowIds = new Set<string>();
    for (const item of payload.turnItems ?? []) {
      if (APPENDABLE_STREAM_ITEM_TYPES.has(item.type)) {
        itemsByTextId.set(item.itemId, item);
        fullRowIds.add(item.itemId);
      }
    }
    const appends = Array.isArray(payload.turnItemAppends) ? payload.turnItemAppends : [];
    if (!appends.length) {
      return { payload, gaps: [] };
    }
    const gaps: SessionStreamAppendGap[] = [];
    const spliced = new Map<string, SessionTurnItem>();
    for (const entry of appends as SessionStreamAppendEntry[]) {
      // A full row in the same frame already covers this item; a redundant
      // fragment is skipped, never treated as a gap.
      if (fullRowIds.has(entry.itemId)) {
        continue;
      }
      const cached = itemsByTextId.get(entry.itemId);
      if (!cached) {
        gaps.push({ itemId: entry.itemId, baseLength: entry.baseLength, reason: "unknown_item" });
        continue;
      }
      const cachedText = itemText(cached);
      if (!entry.appendedText) {
        gaps.push({ itemId: entry.itemId, baseLength: entry.baseLength, reason: "empty_text" });
        continue;
      }
      if (cachedText.length !== entry.baseLength) {
        gaps.push({ itemId: entry.itemId, baseLength: entry.baseLength, reason: "length_mismatch" });
        continue;
      }
      const nextItem = { ...cached, text: cachedText + entry.appendedText } as SessionTurnItem;
      itemsByTextId.set(entry.itemId, nextItem);
      spliced.set(entry.itemId, nextItem);
    }
    if (gaps.length) {
      // Broken chain: hand the payload back untouched so nothing partial is
      // applied; the consumer resnapshots and reconnects to reset the cursor.
      return { payload, gaps };
    }
    const expandedPayload: SessionAssistantDeltaStreamEvent = {
      ...payload,
      turnItems: [...(payload.turnItems ?? []), ...spliced.values()],
    };
    delete expandedPayload.turnItemAppends;
    return { payload: expandedPayload, gaps: [] };
  }

  return { expand };
}
