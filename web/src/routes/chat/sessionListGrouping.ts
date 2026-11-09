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

/** Recency timestamp for the stable rail order (NaN when absent/unparsable). */
function sessionRecencyMs(session: SessionSummary): number {
  return Date.parse(session.updatedAt || session.lastActive || "");
}

/**
 * Deterministic rail order: updatedAt DESC (lastActive fallback), ties broken
 * by session id DESC — the same direction as the backend SQL secondary sort,
 * so client and server agree on same-second rows. Entries without a parsable
 * timestamp sort last, also by id DESC, instead of being scattered by title.
 * Cache head-inserts, create pins, and server refetches can no longer change
 * the relative display order of rows with equal keys.
 */
export function compareSessionsStableRecency(
  left: SessionSummary,
  right: SessionSummary,
): number {
  const leftMs = sessionRecencyMs(left);
  const rightMs = sessionRecencyMs(right);
  const leftKnown = Number.isFinite(leftMs);
  const rightKnown = Number.isFinite(rightMs);
  if (leftKnown && rightKnown && leftMs !== rightMs) {
    return rightMs - leftMs;
  }
  if (leftKnown !== rightKnown) {
    return leftKnown ? -1 : 1;
  }
  const leftId = String(left.id);
  const rightId = String(right.id);
  return rightId < leftId ? -1 : rightId > leftId ? 1 : 0;
}

/** Sorted copy in the deterministic rail order; the input array is untouched. */
export function sortSessionsStableRecency(
  sessions: readonly SessionSummary[],
): SessionSummary[] {
  return [...sessions].sort(compareSessionsStableRecency);
}

/**
 * Split the loaded page into pinned-first tiers. Pinned sessions keep
 * pinnedAtMs order (backend guarantees it; the split is stable for
 * optimistic updates), unpinned sessions come back in loaded order and are
 * ordered for display by ``sortSessionsStableRecency`` at the rail call site.
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
      sessions: (buckets.get(bucket) ?? []).slice().sort(compareSessionsStableRecency),
    }))
    .filter((group) => group.sessions.length > 0);
}
