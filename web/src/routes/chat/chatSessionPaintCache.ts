/**
 * Codex/ChatGPT-style session switch paint cache.
 *
 * Codex keeps side conversations open when switching threads and paints from
 * local session state first. We mirror the "sticky last-good transcript" half:
 * once a session has a real (non-provisional) detail window, remember it so
 * revisiting the tab never flashes an empty shell while GET/select re-hydrates.
 *
 * Critical: a thin live window (e.g. last 4 of 151 messages while a turn is
 * still "running") must never replace a richer sticky snapshot, or the UI looks
 * like "running with almost no content".
 */

import type { ConversationMessage, SessionDetail } from "../../api/types";
import { forgetSessionTimelineScroll } from "../../components/conversation/conversationSessionScrollMemory";
import { mergeSessionDetailMessageWindow } from "../chatSessionState";

const MAX_LAST_GOOD_SESSIONS = 12;
const lastGoodBySessionId = new Map<string, SessionDetail>();
/** Active-first keep-alive ring for recent session ids (switch resume). */
let keepAliveSessionIds: string[] = [];

function messageCount(detail: SessionDetail | null | undefined) {
  return Array.isArray(detail?.messages) ? detail.messages.length : 0;
}

function messageIndexHint(message: ConversationMessage) {
  const meta = message.metadata?.messageIndex;
  if (typeof meta === "number" && Number.isFinite(meta)) {
    return meta;
  }
  const match = /-message-(\d+)$/.exec(String(message.id || ""));
  if (match) {
    const parsed = Number(match[1]);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return Number.POSITIVE_INFINITY;
}

function mergeMessageLists(
  stickyMessages: ConversationMessage[] | undefined,
  liveMessages: ConversationMessage[] | undefined,
): ConversationMessage[] {
  const byId = new Map<string, ConversationMessage>();
  for (const message of [...(stickyMessages ?? []), ...(liveMessages ?? [])]) {
    const id = String(message?.id || "").trim();
    if (!id) {
      continue;
    }
    byId.set(id, message);
  }
  return [...byId.values()].sort((left, right) => {
    const leftIndex = messageIndexHint(left);
    const rightIndex = messageIndexHint(right);
    if (leftIndex !== rightIndex) {
      return leftIndex - rightIndex;
    }
    return String(left.id).localeCompare(String(right.id));
  });
}

function touchOrder(sessionId: string, detail: SessionDetail) {
  if (lastGoodBySessionId.has(sessionId)) {
    lastGoodBySessionId.delete(sessionId);
  }
  lastGoodBySessionId.set(sessionId, detail);
  while (lastGoodBySessionId.size > MAX_LAST_GOOD_SESSIONS) {
    const oldest = lastGoodBySessionId.keys().next().value;
    if (oldest == null) {
      break;
    }
    lastGoodBySessionId.delete(oldest);
  }
}

/**
 * Merge sticky + live so windowed GETs accumulate rather than erase history.
 * Live wins on id collisions (newer content); sticky keeps earlier turns.
 */
export function mergeStickySessionDetailPaint(
  sticky: SessionDetail | undefined,
  live: SessionDetail,
): SessionDetail {
  if (!sticky || sticky.id !== live.id) {
    return { ...live, provisionalTranscript: undefined };
  }
  // Prefer full window merge when both sides carry messageWindow metadata.
  if (sticky.messageWindow && live.messageWindow) {
    return {
      ...mergeSessionDetailMessageWindow(sticky, live),
      provisionalTranscript: undefined,
    };
  }
  const messages = mergeMessageLists(sticky.messages, live.messages);
  return {
    ...sticky,
    ...live,
    messages,
    provisionalTranscript: undefined,
    messageWindow: live.messageWindow ?? sticky.messageWindow,
  };
}

/** Store a hydrated detail for instant re-paint on tab return. */
export function rememberSessionDetailPaint(detail: SessionDetail | null | undefined) {
  const sessionId = String(detail?.id || "").trim();
  if (!sessionId || !detail || detail.provisionalTranscript) {
    return;
  }
  const existing = lastGoodBySessionId.get(sessionId);
  if (existing && messageCount(existing) > messageCount(detail)) {
    // Never clobber a richer sticky with a thinner live window.
    const merged = mergeStickySessionDetailPaint(existing, detail);
    touchOrder(sessionId, merged);
    return;
  }
  if (existing && existing.id === sessionId) {
    touchOrder(sessionId, mergeStickySessionDetailPaint(existing, detail));
    return;
  }
  touchOrder(sessionId, { ...detail, provisionalTranscript: undefined });
}

/** Drop cache entry when a session is deleted / cleared. */
export function forgetSessionDetailPaint(sessionId: string | null | undefined) {
  const normalized = String(sessionId || "").trim();
  if (!normalized) {
    return;
  }
  lastGoodBySessionId.delete(normalized);
  keepAliveSessionIds = keepAliveSessionIds.filter((id) => id !== normalized);
  // C5/C6: paint + scroll memory share session lifetime.
  forgetSessionTimelineScroll(normalized);
}

/**
 * Prefer merged sticky+live when both exist; never paint a foreign session.
 * Thin non-provisional live windows keep sticky history for display.
 */
export function resolveStickySessionDetailPaint(options: {
  activeSessionId: string | null | undefined;
  detail: SessionDetail | undefined;
}): SessionDetail | undefined {
  const activeSessionId = String(options.activeSessionId || "").trim();
  if (!activeSessionId) {
    return undefined;
  }
  const live = options.detail;
  const sticky = lastGoodBySessionId.get(activeSessionId);
  if (live?.id === activeSessionId && !live.provisionalTranscript) {
    if (sticky?.id === activeSessionId) {
      const merged = mergeStickySessionDetailPaint(sticky, live);
      rememberSessionDetailPaint(merged);
      return merged;
    }
    rememberSessionDetailPaint(live);
    return live;
  }
  if (sticky?.id === activeSessionId) {
    // While provisional/loading, still fold any live shell fields if present.
    if (live?.id === activeSessionId) {
      return mergeStickySessionDetailPaint(sticky, { ...live, provisionalTranscript: true });
    }
    return sticky;
  }
  return live?.id === activeSessionId ? live : undefined;
}

/**
 * Transcript loading chrome only when we have nothing usable to show.
 * Sticky last-good messages suppress the empty/loading flash (Codex resume feel).
 */
export function shouldShowStickyTranscriptPending(options: {
  paintDetail: SessionDetail | undefined;
  liveDetail: SessionDetail | undefined;
  isFetching: boolean;
  isTempSession?: boolean;
  activeSessionId?: string | null;
}): boolean {
  const activeSessionId = String(options.activeSessionId || "").trim();
  if (!activeSessionId || options.isTempSession) {
    return false;
  }
  const paintMessages = options.paintDetail?.messages?.length ?? 0;
  if (paintMessages > 0) {
    return false;
  }
  if (options.paintDetail?.id === activeSessionId && !options.paintDetail.provisionalTranscript) {
    // Truly empty hydrated session.
    return false;
  }
  if (options.liveDetail?.provisionalTranscript) {
    return true;
  }
  if (options.paintDetail?.id === activeSessionId) {
    return Boolean(options.liveDetail?.provisionalTranscript || options.isFetching);
  }
  return Boolean(options.isFetching);
}

/** Test helper — clear module cache between cases. */
export function clearSessionDetailPaintCacheForTests() {
  lastGoodBySessionId.clear();
  keepAliveSessionIds = [];
}

/** Codex-style keep-alive window: active first, then recent previous ids. */
export function nextSessionKeepAliveIds(options: {
  activeSessionId: string | null | undefined;
  previousIds: readonly string[];
  limit?: number;
}): string[] {
  const activeSessionId = String(options.activeSessionId || "").trim();
  const limit = Math.max(1, options.limit ?? 2);
  if (!activeSessionId) {
    return options.previousIds.slice(0, limit);
  }
  return [activeSessionId, ...options.previousIds.filter((id) => id !== activeSessionId)].slice(0, limit);
}

/**
 * Record the active session into the keep-alive ring so sticky paint for the
 * previous thread remains warm while the user thrash-switches tabs.
 */
export function touchSessionKeepAlive(sessionId: string | null | undefined, limit = 3): string[] {
  keepAliveSessionIds = nextSessionKeepAliveIds({
    activeSessionId: sessionId,
    previousIds: keepAliveSessionIds,
    limit,
  });
  return keepAliveSessionIds.slice();
}

export function listSessionKeepAliveIds(): string[] {
  return keepAliveSessionIds.slice();
}
