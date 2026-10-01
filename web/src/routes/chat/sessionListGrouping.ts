/**
 * Pure helpers for the session list rail powers: pinned-first split and
 * day-boundary timeline buckets over the loaded session page.
 */

import type { SessionSummary } from "../../api/types";

export type SessionListDateBucket = "today" | "yesterday" | "thisWeek" | "earlier";

export const SESSION_LIST_DATE_BUCKET_ORDER: readonly SessionListDateBucket[] = [
  "today",
  "yesterday",
  "thisWeek",
  "earlier",
];

export type SessionListDateGroup = {
  bucket: SessionListDateBucket;
  sessions: SessionSummary[];
};

function dayStartMs(value: number): number {
  const date = new Date(value);
  date.setHours(0, 0, 0, 0);
  return date.getTime();
}

/** Day-boundary bucket for one timestamp relative to ``nowMs`` (local days). */
export function sessionListDateBucket(updatedAtMs: number, nowMs: number): SessionListDateBucket {
  const day = dayStartMs(updatedAtMs);
  const today = dayStartMs(nowMs);
  if (day >= today) {
    return "today";
  }
  if (day >= today - 86_400_000) {
    return "yesterday";
  }
  if (day >= today - 6 * 86_400_000) {
    return "thisWeek";
  }
  return "earlier";
}

/** Stable within-bucket order: newest update first (falls back to title). */
function compareByRecency(left: SessionSummary, right: SessionSummary): number {
  const leftMs = Date.parse(left.updatedAt || left.lastActive || "") || 0;
  const rightMs = Date.parse(right.updatedAt || right.lastActive || "") || 0;
  if (leftMs !== rightMs) {
    return rightMs - leftMs;
  }
  return String(left.title || left.id).localeCompare(String(right.title || right.id));
}

/**
 * Split the loaded page into pinned-first tiers. Pinned sessions keep
 * pinnedAtMs order (backend guarantees it; the split is stable for
 * optimistic updates), unpinned sessions keep their loaded order.
 */
export function splitPinnedSessions(sessions: readonly SessionSummary[]): {
  pinned: SessionSummary[];
  unpinned: SessionSummary[];
} {
  const pinned: SessionSummary[] = [];
  const unpinned: SessionSummary[] = [];
  for (const session of sessions) {
    if (Number(session.pinnedAtMs ?? 0) > 0) {
      pinned.push(session);
    } else {
      unpinned.push(session);
    }
  }
  pinned.sort((left, right) => Number(right.pinnedAtMs ?? 0) - Number(left.pinnedAtMs ?? 0));
  return { pinned, unpinned };
}

/** Group sessions into day buckets; empty buckets are omitted. */
export function groupSessionsByTimeline(
  sessions: readonly SessionSummary[],
  nowMs: number,
): SessionListDateGroup[] {
  const buckets = new Map<SessionListDateBucket, SessionSummary[]>();
  for (const session of sessions) {
    const updatedMs = Date.parse(session.updatedAt || session.lastActive || "");
    if (!Number.isFinite(updatedMs) || updatedMs <= 0) {
      continue;
    }
    const bucket = sessionListDateBucket(updatedMs, nowMs);
    const existing = buckets.get(bucket);
    if (existing) {
      existing.push(session);
    } else {
      buckets.set(bucket, [session]);
    }
  }
  return SESSION_LIST_DATE_BUCKET_ORDER
    .map((bucket) => ({
      bucket,
      sessions: (buckets.get(bucket) ?? []).slice().sort(compareByRecency),
    }))
    .filter((group) => group.sessions.length > 0);
}
