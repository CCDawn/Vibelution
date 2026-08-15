import type { QueryClient } from "@tanstack/react-query";

import { fetchSessionDetail, isSessionNotFoundError } from "../../api/chat";
import { evictUnopenableSessionFromCaches } from "../chatSessionIndexQuery";
import { queryKeys } from "../../api/queryKeys";
import type {
  ChatRoomDetail,
  ConversationMessage,
  ConversationSummary,
  SessionDetail,
  SessionSummary,
} from "../../api/types";
import {
  assistantFinalAnswerText,
  assistantStatusTurnItems,
  assistantTurnIsStreaming,
  assistantTurnItemsForMessage,
} from "../chatTurnProtocol";
import { isTurnErrorMessage } from "../../components/conversation/conversationMessagePredicates";
import { sessionToConversationSummary } from "../conversationIndexModel";
import { isAgentRootSession } from "../DirectSessionIndexItem";

export const SESSION_DETAIL_INITIAL_MESSAGE_LIMIT = 40;
export const SESSION_DETAIL_HISTORY_PAGE_SIZE = 40;
/** Cursor/ChatGPT-style idle warm of a few nearby chats without thrashing the network. */
export const SESSION_DETAIL_NEIGHBOR_PREFETCH_COUNT = 3;
export const SESSION_DETAIL_PREFETCH_STALE_MS = 30_000;

export type SessionDetailWindowOptions = {
  messageLimit?: number;
  beforeMessageIndex?: number;
  transcriptScope?: "all" | "window" | "none";
  /**
   * When false, backend skips expensive side lists (inbox / governance / group /
   * next-state). Use for high-frequency poll while SSE owns live transcript.
   */
  includeSecondary?: boolean;
  signal?: AbortSignal;
};

export function fetchSessionDetailWindow(
  sessionId: string | null | undefined,
  options: SessionDetailWindowOptions = {},
) {
  const normalizedSessionId = String(sessionId || "").trim();
  return fetchSessionDetail(normalizedSessionId, {
    messageLimit: options.messageLimit ?? SESSION_DETAIL_INITIAL_MESSAGE_LIMIT,
    transcriptScope: options.transcriptScope ?? "window",
    beforeMessageIndex: options.beforeMessageIndex,
    includeSecondary: options.includeSecondary,
    signal: options.signal,
  });
}

/**
 * Warm a session detail window into React Query so switching chats reuses cache
 * (Cursor hover/open prefetch pattern). Deduped by query key with the live query.
 */
export function prefetchSessionDetailWindow(
  queryClient: QueryClient,
  sessionId: string | null | undefined,
  options: Pick<SessionDetailWindowOptions, "messageLimit"> = {},
): Promise<SessionDetail | undefined> {
  const normalizedSessionId = String(sessionId || "").trim();
  if (!normalizedSessionId) {
    return Promise.resolve(undefined);
  }
  return queryClient.prefetchQuery({
    queryKey: queryKeys.session(normalizedSessionId),
    queryFn: ({ signal }) => fetchSessionDetailWindow(normalizedSessionId, {
      signal,
      messageLimit: options.messageLimit,
    }),
    staleTime: SESSION_DETAIL_PREFETCH_STALE_MS,
  }).then(() => {
    const state = queryClient.getQueryState<SessionDetail>(queryKeys.session(normalizedSessionId));
    if (state?.status === "error" && isSessionNotFoundError(state.error)) {
      evictUnopenableSessionFromCaches(queryClient, normalizedSessionId);
      return undefined;
    }
    return queryClient.getQueryData<SessionDetail>(queryKeys.session(normalizedSessionId));
  }).catch((error: unknown) => {
    if (isSessionNotFoundError(error)) {
      evictUnopenableSessionFromCaches(queryClient, normalizedSessionId);
    }
    return undefined;
  });
}

/** Prefer recently updated sessions other than the active one (list order as-is). */
export function resolveNeighborSessionIdsForPrefetch(input: {
  sessions: Array<Pick<SessionSummary, "id">> | null | undefined;
  activeSessionId?: string | null;
  limit?: number;
}): string[] {
  const activeSessionId = String(input.activeSessionId || "").trim();
  const limit = Math.max(0, input.limit ?? SESSION_DETAIL_NEIGHBOR_PREFETCH_COUNT);
  if (!input.sessions?.length || limit === 0) {
    return [];
  }
  const ids: string[] = [];
  for (const session of input.sessions) {
    const id = String(session.id || "").trim();
    if (!id || id === activeSessionId || ids.includes(id)) {
      continue;
    }
    ids.push(id);
    if (ids.length >= limit) {
      break;
    }
  }
  return ids;
}


export { isSessionNotFoundError } from "../../api/chat";

/**
 * Minimal SessionDetail shell from list summary so session switches can paint
 * title/status immediately while the full detail window loads.
 */
export function buildSessionDetailShellFromSummary(
  summary: SessionSummary | null | undefined,
): SessionDetail | undefined {
  if (!summary?.id) {
    return undefined;
  }
  return {
    ...summary,
    defaultFileContext: "",
    previewTabs: [],
    activePreviewPath: "",
    changedFiles: [],
    readFiles: [],
    messages: [],
    // Empty messages here mean "still loading", not "truly empty session".
    provisionalTranscript: true,
    stopRequested: false,
    stopRequestedAt: "",
    stopReason: "",
    messageWindow: {
      mode: "window",
      totalMessages: 0,
      returnedMessages: 0,
      oldestMessageIndex: 0,
      newestMessageIndex: 0,
      hasEarlier: false,
      hasLater: false,
      transcriptScope: "window",
    },
  };
}

/** True when UI is painting a list-summary shell before the message window hydrates. */
export function isProvisionalSessionTranscript(detail: SessionDetail | null | undefined): boolean {
  return Boolean(detail?.provisionalTranscript);
}

/**
 * Prefer cached full detail for the active session; otherwise summary shell.
 * Never return another session's detail as placeholder (avoids flash of wrong chat).
 */
export function resolveSessionDetailPlaceholder(options: {
  activeSessionId: string | null | undefined;
  cachedDetail: SessionDetail | undefined;
  summary: SessionSummary | null | undefined;
}): SessionDetail | undefined {
  const activeSessionId = String(options.activeSessionId || "").trim();
  if (!activeSessionId) {
    return undefined;
  }
  if (options.cachedDetail && options.cachedDetail.id === activeSessionId) {
    return options.cachedDetail;
  }
  const summary = options.summary?.id === activeSessionId ? options.summary : undefined;
  return buildSessionDetailShellFromSummary(summary);
}

/**
 * Resolve what the chat center should paint for the active session.
 * Combines live query data, RQ cache (including optimistic temp shells), and list summary.
 * Disabled queries (temp ids) often omit `queryData` even after setQueryData — always
 * re-read the cache so create/switch never falls back to a full loading shell.
 */
export function resolveActiveSessionDetailForUi(options: {
  activeSessionId: string | null | undefined;
  queryData: SessionDetail | undefined;
  cachedDetail: SessionDetail | undefined;
  summary: SessionSummary | null | undefined;
}): SessionDetail | undefined {
  const activeSessionId = String(options.activeSessionId || "").trim();
  if (!activeSessionId) {
    return undefined;
  }
  if (options.queryData?.id === activeSessionId) {
    return options.queryData;
  }
  return resolveSessionDetailPlaceholder({
    activeSessionId,
    cachedDetail: options.cachedDetail,
    summary: options.summary,
  });
}

/**
 * Hard loading shell only when we have nothing usable to paint.
 * - Temp shells stay interactive.
 * - Summary shells (`provisionalTranscript`) are soft-pending: keep the conversation
 *   frame (composer) but the transcript should show a loading state, not "no messages".
 * - Missing detail while a real fetch is in flight is hard loading.
 */
export function isSessionDetailHardLoading(options: {
  activeSessionId: string | null | undefined;
  detail: SessionDetail | undefined;
  isFetching: boolean;
  isTempSession?: boolean;
}): boolean {
  const activeSessionId = String(options.activeSessionId || "").trim();
  if (!activeSessionId || options.isTempSession) {
    return false;
  }
  if (options.detail?.id === activeSessionId) {
    // Provisional shells keep the frame; transcript pending is handled separately.
    return false;
  }
  return Boolean(options.isFetching);
}

/**
 * Transcript should show a loading/skeleton state instead of the empty-session copy.
 */
export function shouldShowSessionTranscriptPending(options: {
  activeSessionId: string | null | undefined;
  detail: SessionDetail | undefined;
  isFetching: boolean;
  isTempSession?: boolean;
}): boolean {
  const activeSessionId = String(options.activeSessionId || "").trim();
  if (!activeSessionId || options.isTempSession) {
    return false;
  }
  if (options.detail?.id === activeSessionId && options.detail.provisionalTranscript) {
    return true;
  }
  if (options.detail?.id === activeSessionId) {
    return false;
  }
  return Boolean(options.isFetching);
}

export function isForeignSessionDetailQueryKey(
  queryKey: readonly unknown[],
  activeSessionId: string,
): boolean {
  if (queryKey[0] !== "sessions" || queryKey.length !== 2) {
    return false;
  }
  const sessionId = String(queryKey[1] ?? "").trim();
  if (!sessionId || sessionId === "none") {
    return false;
  }
  return sessionId !== activeSessionId;
}




export function latestVisibleTurnErrorMessage(messages: ConversationMessage[] | undefined) {
  const latestMessage = messages?.[messages.length - 1];
  if (!latestMessage || !isTurnErrorMessage(latestMessage)) {
    return "";
  }
  const statusItems = assistantStatusTurnItems(latestMessage);
  for (let index = statusItems.length - 1; index >= 0; index -= 1) {
    const item = statusItems[index];
    if (item?.type === "error") {
      return item.text;
    }
  }
  return "";
}


export function removeDeletedSessionFromConversations(
  conversations: ConversationSummary[] | undefined,
  deletedSessionId: string,
): ConversationSummary[] | undefined {
  if (!conversations) {
    return conversations;
  }
  return conversations.filter((conversation) => {
    if (conversation.type !== "direct_agent") {
      return true;
    }
    return conversation.directSessionId !== deletedSessionId && conversation.conversationId !== deletedSessionId;
  });
}


export function mergeSessionDetailIntoConversations(
  conversations: ConversationSummary[] | undefined,
  detail: SessionDetail,
): ConversationSummary[] | undefined {
  if (!conversations) {
    return conversations;
  }
  const nextConversation = sessionToConversationSummary(detail);
  const existingIndex = conversations.findIndex(
    (conversation) =>
      conversation.type === "direct_agent"
      && (conversation.directSessionId === detail.id || conversation.conversationId === detail.id),
  );
  if (existingIndex < 0) {
    return [nextConversation, ...conversations];
  }
  return conversations.map((conversation, index) =>
    index === existingIndex
      ? {
          ...conversation,
          ...nextConversation,
        }
      : conversation,
  );
}


export function renameSessionInConversations(
  conversations: ConversationSummary[] | undefined,
  sessionId: string,
  title: string,
  updatedAt: string,
  session?: SessionSummary | SessionDetail,
): ConversationSummary[] | undefined {
  if (!conversations || !sessionId) {
    return conversations;
  }

  return conversations.map((conversation) => {
    const directSessionId = String(conversation.directSessionId || conversation.conversationId || "").trim();
    if (conversation.type !== "direct_agent" || directSessionId !== sessionId) {
      return conversation;
    }
    if (session && isAgentRootSession(session)) {
      return {
        ...conversation,
        title,
        agentDisplayName: title,
        updatedAt,
      };
    }
    return {
      ...conversation,
      title,
      updatedAt,
    };
  });
}


export function latestSessionMessageId(detail: SessionDetail): string {
  const messages = detail.messages ?? [];
  return messages[messages.length - 1]?.id ?? "";
}


export function latestSessionMessageSignal(detail: SessionDetail): string {
  const messages = detail.messages ?? [];
  const message = messages[messages.length - 1];
  if (!message) {
    return "";
  }
  return [
    message.id ?? "",
    assistantTurnIsStreaming(message) ? "streaming" : "settled",
    message.role === "user" ? message.content.length : assistantFinalAnswerText(message).length,
    assistantTurnItemsForMessage(message).filter((item) => item.type === "tool_call").length,
    assistantStatusTurnItems(message).length,
  ].join(":");
}


export function sessionDetailSnapshotKey(detail: SessionDetail): string {
  return [
    detail.id,
    detail.status ?? "",
    detail.currentPhase ?? "",
    detail.updatedAt ?? "",
    detail.messages?.length ?? 0,
    latestSessionMessageId(detail),
    latestSessionMessageSignal(detail),
  ].join("|");
}


export function normalizedLedgerSeq(value: unknown): number {
  const numeric = Number(value ?? 0);
  return Number.isFinite(numeric) && numeric > 0 ? numeric : 0;
}


export function isStaleLedgerUpdate(currentSeq: unknown, incomingSeq: unknown): boolean {
  const current = normalizedLedgerSeq(currentSeq);
  const incoming = normalizedLedgerSeq(incomingSeq);
  return current > 0 && incoming > 0 && incoming < current;
}


export function latestMentalSnapshot(_messages: ConversationMessage[] | undefined) {
  // Mental snapshots were a parallel mutable message field. Canonical turns do
  // not transport it, so callers deliberately receive no synthetic fallback.
  return undefined;
}


export function latestChatRoomRound(room: ChatRoomDetail | null | undefined) {
  const rounds = room?.rounds ?? [];
  return rounds.length ? rounds[rounds.length - 1] : null;
}
