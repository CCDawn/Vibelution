import type { SessionSummary } from "../api/types";
import { isTempSessionId } from "./sessionOptimisticIds";

export function recentAgentSessions(sessions: SessionSummary[], retainedIds: readonly (string | null)[], limit = 5) {
  const recent = [...sessions].sort((a, b) =>
    (Date.parse(b.updatedAt || b.lastActive || "") || 0) - (Date.parse(a.updatedAt || a.lastActive || "") || 0),
  ).slice(0, limit);
  const visibleIds = new Set([
    ...recent.map((session) => session.id),
    ...retainedIds,
    // An unfinished local shell is not in the server recency window. Keep it
    // beside the five recent rows until create finishes or the user closes it.
    ...sessions.filter((session) => isTempSessionId(session.id)).map((session) => session.id),
  ]);
  return sessions.filter((session) => visibleIds.has(session.id));
}
