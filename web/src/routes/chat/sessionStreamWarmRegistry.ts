/**
 * Module-level keep-warm registry for direct-session event streams.
 *
 * Pattern attribution (Apache-2.0): zai-org/ZCode `sessionDataLayer` —
 * reference-counted keep-warm with delayed release. Unmounting the chat route
 * no longer tears the SSE connection down synchronously: the stream is parked
 * for SESSION_STREAM_WARM_MS so a remount of the same session reuses the live
 * connection instead of paying a cold reconnect + full resync.
 *
 * Invariants:
 * - This registry (together with useSessionDetailStream as its only caller) is
 *   the sole owner of /api/sessions/:id/events connections; at most one
 *   connection per sessionId exists at any time.
 * - At most one session is kept warm: acquiring a session closes every other
 *   parked entry so parked connections cannot accumulate.
 * - While parked, incoming frames are not projected: the parked listeners only
 *   track the latest ledger watermark, and the consuming hook decides on one
 *   authoritative refresh when the watermark advanced over the cached detail.
 */
import type { SessionEventStream } from "./sessionEventStream";

/** How long an unreferenced stream stays parked (open) after the last owner unmounts. */
export const SESSION_STREAM_WARM_MS = 30_000;

const PARKED_LEDGER_EVENT_TYPES = ["session_detail", "session_initial", "assistant_delta"] as const;

type WarmSessionStreamEntry = {
  stream: SessionEventStream;
  timer: number | null;
  refCount: number;
  /** Highest ledger watermark observed while parked (0 = none). */
  parkedLedgerSeq: number;
  parkedListeners: Array<{ type: string; callback: EventListener }>;
};

export type AcquiredSessionStream = {
  stream: SessionEventStream;
  /** True when the stream was reused from a parked (warm) entry. */
  reusedWarm: boolean;
  /** Ledger watermark observed while the stream was parked (0 = none); consumed on acquire. */
  parkedLedgerSeq: number;
};

const warmEntries = new Map<string, WarmSessionStreamEntry>();

function normalizeSessionId(sessionId: string): string {
  return String(sessionId || "").trim();
}

function extractParkedLedgerSeq(rawData: string): number {
  try {
    const parsed = JSON.parse(rawData) as {
      ledgerSeq?: unknown;
      detail?: { ledgerSeq?: unknown };
    };
    const candidates = [parsed.ledgerSeq, parsed.detail?.ledgerSeq];
    let best = 0;
    for (const candidate of candidates) {
      const seq = Number(candidate ?? 0);
      if (Number.isFinite(seq) && seq > best) {
        best = Math.floor(seq);
      }
    }
    return best;
  } catch {
    return 0;
  }
}

function createParkedListener(entry: WarmSessionStreamEntry): EventListener {
  return (event: Event) => {
    const data = (event as unknown as { data?: string }).data ?? "";
    const seq = extractParkedLedgerSeq(data);
    if (seq > entry.parkedLedgerSeq) {
      entry.parkedLedgerSeq = seq;
    }
  };
}

function detachParkedListeners(entry: WarmSessionStreamEntry): void {
  for (const { type, callback } of entry.parkedListeners) {
    entry.stream.removeEventListener(type, callback);
  }
  entry.parkedListeners = [];
}

function attachParkedListeners(entry: WarmSessionStreamEntry): void {
  detachParkedListeners(entry);
  const callback = createParkedListener(entry);
  for (const type of PARKED_LEDGER_EVENT_TYPES) {
    entry.stream.addEventListener(type, callback);
    entry.parkedListeners.push({ type, callback });
  }
}

function clearWarmTimer(entry: WarmSessionStreamEntry): void {
  if (entry.timer !== null) {
    window.clearTimeout(entry.timer);
    entry.timer = null;
  }
}

function closeOtherWarmEntries(exceptSessionId: string): void {
  for (const [sessionId, entry] of [...warmEntries.entries()]) {
    if (sessionId === exceptSessionId || entry.refCount > 0) {
      continue;
    }
    clearWarmTimer(entry);
    detachParkedListeners(entry);
    entry.stream.close();
    warmEntries.delete(sessionId);
  }
}

function removeEntry(sessionId: string, entry: WarmSessionStreamEntry): void {
  clearWarmTimer(entry);
  detachParkedListeners(entry);
  warmEntries.delete(sessionId);
}

/**
 * Acquire the stream for a session: reuses a parked live stream when one
 * exists, otherwise creates one through the factory. Reference-counted; the
 * registry closes every other parked entry so at most one session stays warm.
 */
export function acquireSessionStream(
  sessionId: string,
  factory: (id: string) => SessionEventStream,
): AcquiredSessionStream {
  const key = normalizeSessionId(sessionId);
  const existing = key ? warmEntries.get(key) : undefined;
  if (existing) {
    if (existing.stream.readyState !== 2) {
      clearWarmTimer(existing);
      detachParkedListeners(existing);
      existing.refCount += 1;
      const parkedLedgerSeq = existing.parkedLedgerSeq;
      existing.parkedLedgerSeq = 0;
      closeOtherWarmEntries(key);
      return { stream: existing.stream, reusedWarm: true, parkedLedgerSeq };
    }
    // A closed stream can never go warm again; drop the stale entry.
    removeEntry(key, existing);
  }
  closeOtherWarmEntries(key);
  const stream = factory(sessionId);
  if (key) {
    warmEntries.set(key, { stream, timer: null, refCount: 1, parkedLedgerSeq: 0, parkedListeners: [] });
  }
  return { stream, reusedWarm: false, parkedLedgerSeq: 0 };
}

/**
 * Release one reference. When the count reaches zero the stream is parked:
 * it stays open for SESSION_STREAM_WARM_MS while parked listeners only record
 * the latest ledger watermark, then it is closed and dropped. A release for a
 * stream the registry does not own (or an already-closed stream) just drops
 * the entry.
 */
export function releaseSessionStream(sessionId: string, stream: SessionEventStream): void {
  const key = normalizeSessionId(sessionId);
  const entry = key ? warmEntries.get(key) : undefined;
  if (!entry || entry.stream !== stream) {
    return;
  }
  entry.refCount = Math.max(0, entry.refCount - 1);
  if (entry.refCount > 0) {
    return;
  }
  if (stream.readyState === 2) {
    removeEntry(key, entry);
    return;
  }
  attachParkedListeners(entry);
  clearWarmTimer(entry);
  entry.timer = window.setTimeout(() => {
    const current = warmEntries.get(key);
    if (!current || current !== entry || current.refCount > 0) {
      return;
    }
    entry.timer = null;
    entry.stream.close();
    removeEntry(key, entry);
  }, SESSION_STREAM_WARM_MS);
}

/** Test/HMR escape hatch: close every tracked stream immediately. */
export function disposeSessionStreams(): void {
  for (const [sessionId, entry] of [...warmEntries.entries()]) {
    clearWarmTimer(entry);
    detachParkedListeners(entry);
    entry.stream.close();
    warmEntries.delete(sessionId);
  }
}

/** Latest ledger watermark observed while the session's stream is parked (test introspection). */
export function peekParkedSessionStreamLedgerSeq(sessionId: string): number {
  const entry = warmEntries.get(normalizeSessionId(sessionId));
  return entry?.parkedLedgerSeq ?? 0;
}

/** True when the session currently has a tracked (live or parked) stream entry. */
export function hasSessionStreamEntry(sessionId: string): boolean {
  return warmEntries.has(normalizeSessionId(sessionId));
}
