import { fetchJson } from "../../api/client";
import type {
  ChatRoomDetail,
  ConversationMessage,
  ConversationSummary,
  MentalStateSnapshot,
  SessionDetail,
  SessionSummary,
} from "../../api/types";
import { isTurnErrorMessage } from "../../components/conversation/conversationMessagePredicates";
import { sessionToConversationSummary } from "../conversationIndexModel";
import { isAgentRootSession } from "../DirectSessionIndexItem";

export const SESSION_DETAIL_INITIAL_MESSAGE_LIMIT = 40;
export const SESSION_DETAIL_HISTORY_PAGE_SIZE = 40;

export type SessionDetailWindowOptions = {
  messageLimit?: number;
  beforeMessageIndex?: number;
  transcriptScope?: "all" | "window" | "none";
  signal?: AbortSignal;
};

export function fetchSessionDetailWindow(
  sessionId: string | null | undefined,
  options: SessionDetailWindowOptions = {},
) {
  const normalizedSessionId = String(sessionId || "").trim();
  const params = new URLSearchParams();
  params.set("messageLimit", String(options.messageLimit ?? SESSION_DETAIL_INITIAL_MESSAGE_LIMIT));
  params.set("transcriptScope", options.transcriptScope ?? "window");
  if (options.beforeMessageIndex && options.beforeMessageIndex > 0) {
    params.set("beforeMessageIndex", String(options.beforeMessageIndex));
  }
  return fetchJson<SessionDetail>(
    `/api/sessions/${encodeURIComponent(normalizedSessionId)}?${params.toString()}`,
    { signal: options.signal },
  );
}


export function isSessionNotFoundError(error: unknown) {
  const message = error instanceof Error ? error.message : String(error ?? "");
  return /session not found|会话不存在|未找到会话/i.test(message);
}

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
  return latestMessage && isTurnErrorMessage(latestMessage) ? String(latestMessage.content ?? "") : "";
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
    message.streaming ? "streaming" : "settled",
    message.content?.length ?? 0,
    message.toolCalls?.length ?? 0,
    message.feedbackEvents?.length ?? 0,
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


export function latestMentalSnapshot(messages: ConversationMessage[] | undefined): MentalStateSnapshot | undefined {
  return [...(messages ?? [])].reverse().find((message) => message.role === "assistant" && message.mentalSnapshot)?.mentalSnapshot;
}


export function latestChatRoomRound(room: ChatRoomDetail | null | undefined) {
  const rounds = room?.rounds ?? [];
  return rounds.length ? rounds[rounds.length - 1] : null;
}
