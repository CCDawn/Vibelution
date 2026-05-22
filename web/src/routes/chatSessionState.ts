import { SessionDetail, SessionSummary } from "../api/types";

export function sessionSummaryFromDetail(detail: SessionDetail): SessionSummary {
  return {
    id: detail.id,
    title: detail.title,
    workspacePath: detail.workspacePath,
    status: detail.status,
    taskSummary: detail.taskSummary,
    lastActive: detail.lastActive,
    updatedAt: detail.updatedAt,
    currentPhase: detail.currentPhase,
  };
}

export function mergeSessionDetailIntoSummaries(
  sessions: SessionSummary[] | undefined,
  detail: SessionDetail,
): SessionSummary[] {
  const nextSummary = sessionSummaryFromDetail(detail);
  const currentSessions = sessions ?? [];
  const index = currentSessions.findIndex((session) => session.id === detail.id);
  if (index < 0) {
    return [nextSummary, ...currentSessions];
  }

  return currentSessions.map((session, sessionIndex) =>
    sessionIndex === index
      ? {
          ...session,
          ...nextSummary,
        }
      : session,
  );
}

export function markSessionSummaryRunning(
  sessions: SessionSummary[] | undefined,
  sessionId: string,
): SessionSummary[] | undefined {
  if (!sessions || !sessionId) {
    return sessions;
  }

  return sessions.map((session) =>
    session.id === sessionId
      ? {
          ...session,
          status: "running",
          currentPhase: "running",
          updatedAt: new Date().toISOString(),
        }
      : session,
  );
}

export function markSessionDetailRunning(detail: SessionDetail | undefined): SessionDetail | undefined {
  if (!detail) {
    return detail;
  }

  return {
    ...detail,
    status: "running",
    currentPhase: "running",
    lastTurnError: null,
    updatedAt: new Date().toISOString(),
  };
}
