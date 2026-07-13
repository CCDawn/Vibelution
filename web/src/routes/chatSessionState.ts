import { ConversationMessage, SessionDetail, SessionMessageWindow, SessionReferenceAttachment, SessionStreamEvent, SessionSummary } from "../api/types";

export type OptimisticUserMessageInput = {
  sessionId: string;
  clientSubmissionId: string;
  content: string;
  attachmentIds?: string[];
  references?: SessionReferenceAttachment[];
  createdAt?: string;
};

const OPTIMISTIC_USER_MESSAGE_METADATA_KEY = "optimisticUserMessage";
const CLIENT_SUBMISSION_ID_METADATA_KEY = "clientSubmissionId";
let fallbackSubmissionSequence = 0;

export function createClientSubmissionId(sessionId: string): string {
  const randomUuid = globalThis.crypto?.randomUUID?.();
  if (randomUuid) {
    return `submission-${randomUuid}`;
  }
  fallbackSubmissionSequence += 1;
  const sessionToken = String(sessionId || "session").replace(/[^a-zA-Z0-9_-]/g, "_");
  return `submission-${sessionToken}-${Date.now().toString(36)}-${fallbackSubmissionSequence.toString(36)}`;
}

function optimisticUserMessageId(input: OptimisticUserMessageInput): string {
  return `optimistic-user-${input.clientSubmissionId}`;
}

function conversationMessageClientSubmissionId(message: ConversationMessage): string {
  return String(message.metadata?.[CLIENT_SUBMISSION_ID_METADATA_KEY] ?? "").trim();
}

function isMatchingUserSubmission(message: ConversationMessage, input: OptimisticUserMessageInput): boolean {
  return message.role === "user"
    && conversationMessageClientSubmissionId(message) === input.clientSubmissionId;
}

function isMatchingOptimisticUserMessage(message: ConversationMessage, input: OptimisticUserMessageInput): boolean {
  return isMatchingUserSubmission(message, input)
    && message.metadata?.[OPTIMISTIC_USER_MESSAGE_METADATA_KEY] === true;
}

function isOptimisticUserMessage(message: ConversationMessage): boolean {
  return message.role === "user" && message.metadata?.[OPTIMISTIC_USER_MESSAGE_METADATA_KEY] === true;
}

function isCommittedUserMessage(message: ConversationMessage): boolean {
  return message.role === "user" && message.metadata?.[OPTIMISTIC_USER_MESSAGE_METADATA_KEY] !== true;
}

function removeSettledOptimisticUserMessages(messages: ConversationMessage[]): ConversationMessage[] {
  const committedSubmissionIds = new Set(
    messages
      .filter(isCommittedUserMessage)
      .map(conversationMessageClientSubmissionId)
      .filter(Boolean),
  );
  if (committedSubmissionIds.size === 0) {
    return messages;
  }
  return messages.filter((message) => {
    if (!isOptimisticUserMessage(message)) {
      return true;
    }
    const clientSubmissionId = conversationMessageClientSubmissionId(message);
    return !clientSubmissionId || !committedSubmissionIds.has(clientSubmissionId);
  });
}

export function appendOptimisticUserMessage(
  detail: SessionDetail | undefined,
  input: OptimisticUserMessageInput,
): SessionDetail | undefined {
  if (!detail) {
    return detail;
  }

  if (detail.messages.some((message) => isMatchingUserSubmission(message, input))) {
    return detail;
  }

  const createdAt = input.createdAt ?? new Date().toISOString();
  const optimisticMessage: ConversationMessage = {
    id: optimisticUserMessageId(input),
    role: "user",
    content: input.content,
    timestamp: createdAt,
    metadata: {
      [OPTIMISTIC_USER_MESSAGE_METADATA_KEY]: true,
      [CLIENT_SUBMISSION_ID_METADATA_KEY]: input.clientSubmissionId,
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

export function markOptimisticUserMessageAccepted(
  detail: SessionDetail | undefined,
  input: OptimisticUserMessageInput,
  turnId: string | undefined,
): SessionDetail | undefined {
  const normalizedTurnId = String(turnId ?? "").trim();
  if (!detail || !normalizedTurnId) {
    return detail;
  }
  let changed = false;
  const messages = detail.messages.map((message) => {
    if (!isMatchingOptimisticUserMessage(message, input)) {
      return message;
    }
    changed = true;
    return {
      ...message,
      metadata: {
        ...(message.metadata ?? {}),
        [OPTIMISTIC_USER_MESSAGE_METADATA_KEY]: true,
        pending: false,
        turnId: normalizedTurnId,
      },
    };
  });
  if (!changed) {
    return detail;
  }
  return {
    ...detail,
    messages,
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

function messageWindowIndex(message: ConversationMessage): number {
  const match = String(message.id || "").match(/-message-(\d+)$/);
  const index = match ? Number(match[1]) : 0;
  return Number.isFinite(index) && index > 0 ? index : Number.POSITIVE_INFINITY;
}

function mergeConversationMessageWindows(
  previousMessages: ConversationMessage[],
  nextMessages: ConversationMessage[],
): ConversationMessage[] {
  const orderById = new Map<string, number>();
  const mergedById = new Map<string, ConversationMessage>();
  for (const message of [...previousMessages, ...nextMessages]) {
    const id = String(message.id || "").trim();
    if (!id) {
      continue;
    }
    if (!orderById.has(id)) {
      orderById.set(id, orderById.size);
    }
    mergedById.set(id, message);
  }
  return removeSettledOptimisticUserMessages([...mergedById.values()]).sort((left, right) => {
    const leftIndex = messageWindowIndex(left);
    const rightIndex = messageWindowIndex(right);
    if (leftIndex !== rightIndex) {
      return leftIndex - rightIndex;
    }
    return (orderById.get(left.id) ?? 0) - (orderById.get(right.id) ?? 0);
  });
}

function mergedMessageWindow(
  previous: SessionMessageWindow,
  next: SessionMessageWindow,
  messages: ConversationMessage[],
): SessionMessageWindow {
  const totalMessages = Math.max(previous.totalMessages || 0, next.totalMessages || 0);
  const finiteIndexes = messages
    .map(messageWindowIndex)
    .filter((index) => Number.isFinite(index));
  const oldestCandidates = [
    ...finiteIndexes,
    previous.oldestMessageIndex || 0,
    next.oldestMessageIndex || 0,
  ].filter((index) => index > 0);
  const newestCandidates = [
    ...finiteIndexes,
    previous.newestMessageIndex || 0,
    next.newestMessageIndex || 0,
  ].filter((index) => index > 0);
  const oldestMessageIndex = finiteIndexes.length
    ? Math.min(...oldestCandidates)
    : Math.min(previous.oldestMessageIndex || 0, next.oldestMessageIndex || 0);
  const newestMessageIndex = finiteIndexes.length
    ? Math.max(...newestCandidates)
    : Math.max(previous.newestMessageIndex || 0, next.newestMessageIndex || 0);
  const hasEarlier = oldestMessageIndex > 1 && (previous.hasEarlier || next.hasEarlier || oldestMessageIndex > 1);
  const hasLater = totalMessages > 0 && newestMessageIndex < totalMessages;
  return {
    ...next,
    totalMessages,
    returnedMessages: messages.length,
    oldestMessageIndex,
    newestMessageIndex,
    hasEarlier,
    hasLater,
    nextBeforeMessageIndex: hasEarlier ? oldestMessageIndex : null,
  };
}

export function mergeSessionDetailMessageWindow(
  previous: SessionDetail | undefined,
  next: SessionDetail,
): SessionDetail {
  if (!previous || previous.id !== next.id || !previous.messageWindow || !next.messageWindow) {
    return next;
  }
  const messages = mergeConversationMessageWindows(previous.messages ?? [], next.messages ?? []);
  const base = next.messageWindow.hasLater ? previous : next;
  return {
    ...base,
    messages,
    messageWindow: mergedMessageWindow(previous.messageWindow, next.messageWindow, messages),
  };
}

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
