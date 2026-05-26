import { SessionDetail, SessionStreamEvent, SessionSummary } from "../api/types";

export type SessionDetailLoadState = {
  blockingError: boolean;
  transientError: boolean;
  backgroundError: boolean;
};

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

export function deriveSessionDetailQueryErrorState(
  detail: SessionDetail | undefined,
  isError: boolean,
  options: {
    dataUpdatedAt?: number;
    errorUpdatedAt?: number;
    streamConnected?: boolean;
  } = {},
): SessionDetailLoadState {
  const hasDetail = Boolean(detail);
  const dataUpdatedAt = Number(options.dataUpdatedAt ?? 0);
  const errorUpdatedAt = Number(options.errorUpdatedAt ?? 0);
  const streamConnected = Boolean(options.streamConnected);
  const dataIsNewerThanError =
    hasDetail
    && dataUpdatedAt > 0
    && errorUpdatedAt > 0
    && dataUpdatedAt >= errorUpdatedAt;
  const activeQueryError = isError && !dataIsNewerThanError;

  return {
    blockingError: activeQueryError && !hasDetail,
    transientError: activeQueryError && hasDetail && !streamConnected,
    backgroundError: activeQueryError && hasDetail && streamConnected,
  };
}

export function deriveSessionListQueryErrorState(
  sessions: SessionSummary[] | undefined,
  isError: boolean,
): { blockingError: boolean; transientError: boolean } {
  const hasUsableData = Boolean(sessions?.length);
  return {
    blockingError: isError && !hasUsableData,
    transientError: isError && hasUsableData,
  };
}

export function shouldAcceptSessionStreamEvent(
  payload: SessionStreamEvent | undefined,
  activeSessionId: string | null | undefined,
): payload is SessionStreamEvent {
  return Boolean(
    payload
      && payload.type === "session_detail"
      && payload.detail
      && payload.sessionId === activeSessionId
      && payload.detail.id === activeSessionId,
  );
}
