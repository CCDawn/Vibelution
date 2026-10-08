/**
 * Flat archived-session rail: sort and the collapsed page.
 * The archive view replaces the live directory; it does not mix into it.
 */

import type { SessionSummary } from "../../api/types";
import type { SessionListSortBy } from "./sessionListPreferences";

export const ARCHIVED_SESSION_RAIL_COLLAPSED_LIMIT = 20;

function sortStamp(session: SessionSummary, sortBy: SessionListSortBy): number {
  const raw = sortBy === "createdAt"
    ? session.createdAt || session.updatedAt || session.lastActive
    : session.updatedAt || session.lastActive || session.createdAt;
  const parsed = Date.parse(raw || "");
  return Number.isFinite(parsed) ? parsed : 0;
}

/** Newest first. Ties fall back to title so the order stays stable. */
export function sortArchivedSessions(
  sessions: readonly SessionSummary[],
  sortBy: SessionListSortBy,
): SessionSummary[] {
  return [...sessions].sort((left, right) => {
    const delta = sortStamp(right, sortBy) - sortStamp(left, sortBy);
    if (delta !== 0) {
      return delta;
    }
    return String(left.title || left.id).localeCompare(String(right.title || right.id));
  });
}

export function visibleArchivedSessions(
  sessions: readonly SessionSummary[],
  expanded: boolean,
  limit: number = ARCHIVED_SESSION_RAIL_COLLAPSED_LIMIT,
): SessionSummary[] {
  if (expanded || sessions.length <= limit) {
    return [...sessions];
  }
  return sessions.slice(0, limit);
}
