import { ConversationMessage, SessionDetail, SessionReferenceAttachment, SessionStreamEvent, SessionSummary } from "../api/types";

export type OptimisticUserMessageInput = {
  sessionId: string;
  content: string;
  attachmentIds?: string[];
  references?: SessionReferenceAttachment[];
  createdAt?: string;
};

const OPTIMISTIC_USER_MESSAGE_METADATA_KEY = "optimisticUserMessage";

function optimisticUserMessageId(input: OptimisticUserMessageInput, createdAt: string): string {
  const contentHash = Array.from(input.content)
    .reduce((hash, char) => ((hash << 5) - hash + char.charCodeAt(0)) | 0, 0)
    .toString(16);
  return `optimistic-user-${input.sessionId}-${createdAt}-${contentHash}`;
}

function isMatchingOptimisticUserMessage(message: ConversationMessage, input: OptimisticUserMessageInput): boolean {
  return message.role === "user"
    && message.content === input.content
    && message.metadata?.[OPTIMISTIC_USER_MESSAGE_METADATA_KEY] === true;
}

export function appendOptimisticUserMessage(
  detail: SessionDetail | undefined,
  input: OptimisticUserMessageInput,
): SessionDetail | undefined {
  if (!detail) {
    return detail;
  }

  if (detail.messages.some((message) => isMatchingOptimisticUserMessage(message, input))) {
    return detail;
  }

  const createdAt = input.createdAt ?? new Date().toISOString();
  const optimisticMessage: ConversationMessage = {
    id: optimisticUserMessageId(input, createdAt),
    role: "user",
    content: input.content,
    timestamp: createdAt,
    metadata: {
      [OPTIMISTIC_USER_MESSAGE_METADATA_KEY]: true,
      pending: true,
      attachmentIds: input.attachmentIds ?? [],
      references: input.references ?? [],
    },
    references: input.references ?? [],
  };

  return {
    ...detail,
    messages: [...detail.messages, optimisticMessage],
    updatedAt: createdAt,
  };
}

export function removeOptimisticUserMessage(
  detail: SessionDetail | undefined,
  input: OptimisticUserMessageInput,
): SessionDetail | undefined {
  if (!detail) {
    return detail;
  }

  const nextMessages = detail.messages.filter((message) => !isMatchingOptimisticUserMessage(message, input));
  if (nextMessages.length === detail.messages.length) {
    return detail;
  }

  return {
    ...detail,
    messages: nextMessages,
    updatedAt: new Date().toISOString(),
  };
}

export type SessionDetailLoadState = {
  blockingError: boolean;
  transientError: boolean;
  backgroundError: boolean;
};

export function sessionSummaryFromDetail(detail: SessionDetail): SessionSummary {
  const summary: SessionSummary = {
    id: detail.id,
    title: detail.title,
    workspacePath: detail.workspacePath,
    status: detail.status,
    taskSummary: detail.taskSummary,
    lastActive: detail.lastActive,
    updatedAt: detail.updatedAt,
    currentPhase: detail.currentPhase,
    sessionKind: detail.sessionKind,
    parentSessionId: detail.parentSessionId,
    rootSessionId: detail.rootSessionId,
    childSessionIds: detail.childSessionIds,
    activeChildSessionId: detail.activeChildSessionId,
    childStatus: detail.childStatus,
    taskTitle: detail.taskTitle,
    resultCard: detail.resultCard,
  };
  if (detail.agentId !== undefined) {
    summary.agentId = detail.agentId;
  }
  if (detail.agentCode !== undefined) {
    summary.agentCode = detail.agentCode;
  }
  if (detail.agentDisplayName !== undefined) {
    summary.agentDisplayName = detail.agentDisplayName;
  }
  if (detail.agentAvatarImagePath !== undefined) {
    summary.agentAvatarImagePath = detail.agentAvatarImagePath;
  }
  if (detail.agentAvatarImageUrl !== undefined) {
    summary.agentAvatarImageUrl = detail.agentAvatarImageUrl;
  }
  if (detail.agentPrimaryMode !== undefined) {
    summary.agentPrimaryMode = detail.agentPrimaryMode;
  }
  if (detail.agentRoleKey !== undefined) {
    summary.agentRoleKey = detail.agentRoleKey;
  }
  if (detail.agentPromptTemplateId !== undefined) {
    summary.agentPromptTemplateId = detail.agentPromptTemplateId;
  }
  if (detail.agentPromptSnapshot !== undefined) {
    summary.agentPromptSnapshot = detail.agentPromptSnapshot;
  }
  if (detail.dialogueModelId !== undefined) {
    summary.dialogueModelId = detail.dialogueModelId;
  }
  if (detail.agentInboxPendingCount !== undefined) {
    summary.agentInboxPendingCount = detail.agentInboxPendingCount;
  }
  if (detail.agentWorkspacePath !== undefined) {
    summary.agentWorkspacePath = detail.agentWorkspacePath;
  }
  if (detail.agentMissingId !== undefined) {
    summary.agentMissingId = detail.agentMissingId;
  }
  if (detail.agentPrimaryDirectSessionId !== undefined) {
    summary.agentPrimaryDirectSessionId = detail.agentPrimaryDirectSessionId;
  }
  if (detail.agentDirectSessionMismatch !== undefined) {
    summary.agentDirectSessionMismatch = detail.agentDirectSessionMismatch;
  }
  if (detail.agentMissing !== undefined) {
    summary.agentMissing = detail.agentMissing;
  }
  if (detail.agentStatusCode !== undefined) {
    summary.agentStatusCode = detail.agentStatusCode;
  }
  if (detail.agentStatusMessage !== undefined) {
    summary.agentStatusMessage = detail.agentStatusMessage;
  }
  if (detail.sourceRef !== undefined) {
    summary.sourceRef = detail.sourceRef;
  }
  if (detail.projectionEdit !== undefined) {
    summary.projectionEdit = detail.projectionEdit;
  }
  if (detail.agentSourceRef !== undefined) {
    summary.agentSourceRef = detail.agentSourceRef;
  }
  if (detail.conversationIndexVisibility !== undefined) {
    summary.conversationIndexVisibility = detail.conversationIndexVisibility;
  }
  if (detail.conversationIndexKind !== undefined) {
    summary.conversationIndexKind = detail.conversationIndexKind;
  }
  if (detail.conversationIndexErrors !== undefined) {
    summary.conversationIndexErrors = detail.conversationIndexErrors;
  }
  return summary;
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

export function removeDeletedSessionFromSummaries(
  sessions: SessionSummary[] | undefined,
  deletedSessionId: string,
  nextDetail: SessionDetail,
): SessionSummary[] {
  const currentSessions = sessions ?? [];
  return mergeSessionDetailIntoSummaries(
    currentSessions.filter((session) => session.id !== deletedSessionId),
    nextDetail,
  );
}

export function renameSessionInSummaries(
  sessions: SessionSummary[] | undefined,
  sessionId: string,
  title: string,
  updatedAt: string,
): SessionSummary[] | undefined {
  if (!sessions || !sessionId) {
    return sessions;
  }

  return sessions.map((session) => {
    if (session.id !== sessionId) {
      return session;
    }
    if (isRootAgentSession(session)) {
      return {
        ...session,
        title,
        agentDisplayName: title,
        updatedAt,
      };
    }
    if (session.sessionKind === "child") {
      return {
        ...session,
        title,
        taskTitle: title,
        updatedAt,
      };
    }
    return {
      ...session,
      title,
      updatedAt,
    };
  });
}

export function renameSessionDetail(
  detail: SessionDetail | undefined,
  sessionId: string,
  title: string,
  updatedAt: string,
): SessionDetail | undefined {
  if (!detail || detail.id !== sessionId) {
    return detail;
  }

  if (isRootAgentSession(detail)) {
    return {
      ...detail,
      title,
      agentDisplayName: title,
      updatedAt,
    };
  }
  if (detail.sessionKind === "child") {
    return {
      ...detail,
      title,
      taskTitle: title,
      updatedAt,
    };
  }
  return {
    ...detail,
    title,
    updatedAt,
  };
}

function isRootAgentSession(session: Pick<SessionSummary, "agentId" | "sessionKind">): boolean {
  return Boolean(String(session.agentId ?? "").trim()) && String(session.sessionKind ?? "main").trim() !== "child";
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
  options: {
    emptyNotFoundAsEmpty?: boolean;
    error?: unknown;
  } = {},
): { blockingError: boolean; transientError: boolean } {
  const hasUsableData = Boolean(sessions?.length);
  const message = options.error instanceof Error ? options.error.message : String(options.error ?? "");
  const treatAsEmpty = Boolean(options.emptyNotFoundAsEmpty && /not found|404|未找到/i.test(message));
  return {
    blockingError: isError && !hasUsableData && !treatAsEmpty,
    transientError: isError && hasUsableData && !treatAsEmpty,
  };
}

export function shouldAcceptSessionStreamEvent(
  payload: SessionStreamEvent | undefined,
  activeSessionId: string | null | undefined,
): payload is SessionStreamEvent {
  if (!payload || payload.sessionId !== activeSessionId) {
    return false;
  }
  if (payload.type === "session_detail") {
    return Boolean(payload.detail && payload.detail.id === activeSessionId);
  }
  return payload.type === "assistant_delta" || payload.type === "session_initial";
}
