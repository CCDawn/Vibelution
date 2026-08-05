/**
 * Codex/ChatGPT-style per-session timeline scroll memory.
 *
 * Conversation panes remount on session switch (isolation). Remember the last
 * viewport so returning to a thread restores mid-history reading instead of
 * always jumping to the tail.
 */

export type SessionTimelineScrollMemory = {
  scrollTop: number;
  followingLatest: boolean;
  savedAtMs: number;
};

const MAX_SESSION_SCROLL_ENTRIES = 24;
const scrollMemoryBySessionId = new Map<string, SessionTimelineScrollMemory>();

function compactSessionId(sessionId: string | null | undefined) {
  return String(sessionId || "").trim();
}

function touchOrder(sessionId: string, entry: SessionTimelineScrollMemory) {
  if (scrollMemoryBySessionId.has(sessionId)) {
    scrollMemoryBySessionId.delete(sessionId);
  }
  scrollMemoryBySessionId.set(sessionId, entry);
  while (scrollMemoryBySessionId.size > MAX_SESSION_SCROLL_ENTRIES) {
    const oldest = scrollMemoryBySessionId.keys().next().value;
    if (oldest == null) {
      break;
    }
    scrollMemoryBySessionId.delete(oldest);
  }
}

export function rememberSessionTimelineScroll(
  sessionId: string | null | undefined,
  input: {
    scrollTop: number;
    followingLatest: boolean;
    savedAtMs?: number;
  },
) {
  const normalizedSessionId = compactSessionId(sessionId);
  if (!normalizedSessionId) {
    return;
  }
  const scrollTop = Number(input.scrollTop);
  if (!Number.isFinite(scrollTop) || scrollTop < 0) {
    return;
  }
  touchOrder(normalizedSessionId, {
    scrollTop,
    followingLatest: Boolean(input.followingLatest),
    savedAtMs: Number.isFinite(input.savedAtMs) ? Number(input.savedAtMs) : Date.now(),
  });
}

export function peekSessionTimelineScroll(
  sessionId: string | null | undefined,
): SessionTimelineScrollMemory | undefined {
  const normalizedSessionId = compactSessionId(sessionId);
  if (!normalizedSessionId) {
    return undefined;
  }
  return scrollMemoryBySessionId.get(normalizedSessionId);
}

/**
 * Apply a saved viewport onto a timeline element.
 * Returns true when a non-tail restore was applied.
 */
export function restoreSessionTimelineScroll(
  timeline: {
    scrollHeight: number;
    clientHeight: number;
    scrollTop: number;
  },
  memory: SessionTimelineScrollMemory | undefined,
): { restored: boolean; scrollTop: number; followingLatest: boolean } {
  if (!memory) {
    return { restored: false, scrollTop: 0, followingLatest: true };
  }
  if (memory.followingLatest) {
    const maxTop = Math.max(0, timeline.scrollHeight - timeline.clientHeight);
    timeline.scrollTop = maxTop;
    return { restored: false, scrollTop: maxTop, followingLatest: true };
  }
  const maxTop = Math.max(0, timeline.scrollHeight - timeline.clientHeight);
  const nextTop = Math.min(Math.max(0, memory.scrollTop), maxTop);
  timeline.scrollTop = nextTop;
  return { restored: true, scrollTop: nextTop, followingLatest: false };
}

export function forgetSessionTimelineScroll(sessionId: string | null | undefined) {
  const normalizedSessionId = compactSessionId(sessionId);
  if (!normalizedSessionId) {
    return;
  }
  scrollMemoryBySessionId.delete(normalizedSessionId);
}

/** Test helper — clear module cache between cases. */
export function clearSessionTimelineScrollMemoryForTests() {
  scrollMemoryBySessionId.clear();
}
