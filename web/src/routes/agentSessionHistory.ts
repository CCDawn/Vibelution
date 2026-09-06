import type { SessionSummary } from "../api/types";

export function recentAgentSessions(sessions: SessionSummary[], retainedIds: readonly (string | null)[], limit = 5) {
  const recent = [...sessions].sort((a, b) =>
    (Date.parse(b.updatedAt || b.lastActive || "") || 0) - (Date.parse(a.updatedAt || a.lastActive || "") || 0),
  ).slice(0, limit);
  const visibleIds = new Set([...recent.map((session) => session.id), ...retainedIds]);
  return sessions.filter((session) => visibleIds.has(session.id));
}

export function searchAgentSessionHistory(sessions: SessionSummary[], query: string) {
  const needle = query.trim().toLocaleLowerCase();
  return sessions.filter((session) => [session.title, session.taskSummary, session.agentDisplayName, session.id]
    .filter(Boolean).join(" ").toLocaleLowerCase().includes(needle));
}
