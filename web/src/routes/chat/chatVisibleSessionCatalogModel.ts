import type { SessionDetail, SessionSummary } from "../../api/types";
import { isVisibleDirectSession } from "../conversationIndexModel";

/** Combine the ordinary and archived directory projections for the archive view. */
export function mergeArchivedSessionSummaries(
  sessions: SessionSummary[] | undefined,
  archivedSessions: SessionSummary[],
): SessionSummary[] | undefined {
  if (!archivedSessions.length) return sessions;
  const known = new Set((sessions ?? []).map((session) => session.id));
  const archivedById = new Map(archivedSessions.map((session) => [session.id, session]));
  return [
    ...(sessions ?? []).map((session) => archivedById.get(session.id) ?? session),
    ...archivedSessions.filter((session) => !known.has(session.id)),
  ];
}

export function mergeAllVisibleSessions(
  sessions: SessionSummary[] | undefined,
  childSessions: SessionSummary[] | undefined,
  pendingArchiveAgentIds: ReadonlySet<string>,
  options?: { includeArchivedSessions?: boolean },
): SessionSummary[] {
  const merged = [...(sessions ?? []), ...(childSessions ?? [])];
  return merged
    .filter((session) => isVisibleDirectSession(session, options))
    .filter((session) => !pendingArchiveAgentIds.has(String(session.agentId || "").trim()))
    .filter((session, index, items) => items.findIndex((item) => item.id === session.id) === index);
}

export function resolveActiveSessionAgentId(options: {
  sessionDetailAgentId: string | undefined;
  directSessionActiveSummary: SessionSummary | undefined;
  activeSessionId: string | null;
  sessionsById: ReadonlyMap<string, SessionSummary>;
}): string {
  const { sessionDetailAgentId, directSessionActiveSummary, activeSessionId, sessionsById } = options;
  return String(
    sessionDetailAgentId
    || directSessionActiveSummary?.agentId
    || sessionsById.get(activeSessionId || "")?.agentId
    || "",
  ).trim();
}

export function buildSessionsById(sessions: readonly SessionSummary[]): Map<string, SessionSummary> {
  return new Map(sessions.map((session) => [session.id, session]));
}

export function resolveActivitySeenSessionSources(
  activeSessionId: string,
  sessionsById: ReadonlyMap<string, SessionSummary>,
  detail: SessionDetail | undefined,
  directSessionActiveSummary: SessionSummary | undefined,
): Array<SessionSummary | SessionDetail | undefined> {
  const directorySession = sessionsById.get(activeSessionId);
  const detailSession = detail?.id === activeSessionId ? detail : undefined;
  return [
    directorySession,
    directSessionActiveSummary?.id === activeSessionId ? directSessionActiveSummary : undefined,
    detailSession,
  ];
}
