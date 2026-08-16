import { useMutation, type QueryClient, type UseMutationResult } from "@tanstack/react-query";
import type { Dispatch, MutableRefObject, SetStateAction } from "react";

import {
  resetAgentDirectSession,
  type AgentDirectSessionResetResponse,
} from "../../api/agents";
import {
  createChatRoom,
  createChatSession,
  createSessionChatReviewCandidate,
  deleteChatRoom,
  deleteChatSession,
  bulkDeleteChatSessions,
  fetchSessionDetail,
  resetChatRoom,
  startChatRoomRound,
  stopChatRoomRound,
  updateChatRoom,
  updateChatSession,
} from "../../api/chat";
import {
  revokeProjectAgentBusMessage,
  sendProjectAgentBusMessage,
} from "../../api/projectAgentBus";
import { queryKeys } from "../../api/queryKeys";
import { startUserAction } from "../../app/userActionTelemetry";
import type {
  AgentInstance,
  ChatRoomDetail,
  ChatRoomRoundAcceptedResponse,
  ConversationSummary,
  SessionChatReviewCandidateResponse,
  SessionDeleteResponse,
  SessionBulkDeleteResponse,
  SessionDetail,
  SessionSummary,
} from "../../api/types";
import type { TranslationKey } from "../../i18n/dictionary";
import {
  captureAgentSessionCacheSnapshots,
  captureSessionIndexCacheSnapshots,
  reconcileAgentSessionDetailCache,
  removeSessionFromAgentSessionCaches,
  restoreAgentSessionCacheSnapshots,
  restoreSessionIndexCacheSnapshots,
  updateAgentSessionSummaryCaches,
  updateSessionSummaryCaches,
} from "../chatSessionIndexQuery";
import {
  mergeSessionDetailIntoSummaries,
  mergeSessionDetailMessageWindow,
  renameSessionDetail,
  renameSessionInSummaries,
  sessionSummaryFromDetail,
} from "../chatSessionState";
import type { createChatWorkspaceCache } from "../chatWorkspaceCache";
import {
  fetchSessionDetailWindow,
  removeDeletedSessionFromConversations,
  renameSessionInConversations,
} from "./chatSessionDetailHelpers";
import {
  pinSessionCreatePreserve,
  unpinSessionCreatePreserve,
} from "../sessionCreatePreserve";
import { clearSessionDeleteTombstone, markSessionDeleteTombstone } from "../sessionDeleteTombstone";
import { createTempSessionId } from "../sessionOptimisticIds";
import {
  chatAgentSessionStorage,
  rememberAgentLastSession,
} from "./chatAgentSessionMemory";
import { defaultNewSessionTitle, isDefaultNewSessionTitle } from "./useChatSessionRenameMenu";
import type { ChatRouteSelection } from "./chatSelectionProjection";

type ChatWorkspaceCache = ReturnType<typeof createChatWorkspaceCache>;
type RightIndexPanel = "conversations" | "members";

type ChatRouteLifecycleActions = {
  openSession: (sessionId: string) => void;
  openRoom: (roomId: string) => void;
  replaceIfStillViewing: (expected: ChatRouteSelection, next: ChatRouteSelection) => boolean;
};

function pickOptimisticNextActiveSessionId(
  remainingSessions: SessionSummary[] | undefined,
  deletedSessionId: string,
  previousActiveSessionId: string,
  deletedAgentId: string = "",
): string {
  const deletedId = String(deletedSessionId || "").trim();
  const previousActiveId = String(previousActiveSessionId || "").trim();
  // Deleting a background tab must not steal focus from the current active session.
  if (previousActiveId && previousActiveId !== deletedId) {
    return previousActiveId;
  }
  const remaining = (Array.isArray(remainingSessions) ? remainingSessions : [])
    .filter((session) => session.id !== deletedId);
  const preferredAgentId = String(deletedAgentId || "").trim();
  if (preferredAgentId) {
    const sameAgent = remaining.find(
      (session) => String(session.agentId || "").trim() === preferredAgentId,
    );
    if (sameAgent?.id) {
      return String(sameAgent.id).trim();
    }
  }
  // Prefer the first remaining tab (list is usually recency-ordered by backend).
  return String(remaining[0]?.id || "").trim();
}

export type { AgentDirectSessionResetResponse };

export type UseChatWorkspaceLifecycleOptions = {
  queryClient: QueryClient;
  chatWorkspaceCache: ChatWorkspaceCache;
  lang: "zh" | "en";
  t: (key: TranslationKey) => string;
  describeError: (error: unknown, fallback: string) => string;
  syncSessionDetail: (detail: SessionDetail) => void;
  syncChatRoomDetail: (room: ChatRoomDetail) => void;
  clearSessionTransientUiState: (sessionId: string) => void;
  removeSessionWorkspace: (sessionId: string) => void;
  requestSessionComposerFocus: (sessionId: string) => void;
  /** Always-current committed route selection (snapshot at request start). */
  routeSelectionRef: MutableRefObject<ChatRouteSelection>;
  /** Sole Chat route writer (compare-and-swap transitions only). */
  chatRoute: ChatRouteLifecycleActions;
  setRightIndexPanel: Dispatch<SetStateAction<RightIndexPanel>>;
  setSelectedAgentId: Dispatch<SetStateAction<string>>;
  setSessionFilter: Dispatch<SetStateAction<string>>;
  setSessionComposerErrors: Dispatch<SetStateAction<Record<string, string>>>;
  setGroupComposerOpen: Dispatch<SetStateAction<boolean>>;
  setGroupTitleDraft: Dispatch<SetStateAction<string>>;
  setGroupModeDraft: Dispatch<SetStateAction<string>>;
  setGroupPurposeDraft: Dispatch<SetStateAction<string>>;
  setGroupSelectedAgentIds: Dispatch<SetStateAction<string[]>>;
  setGroupTopicDraft: Dispatch<SetStateAction<string>>;
  setGroupRoomActionError: Dispatch<SetStateAction<string>>;
  setGroupManageTitleDraft: Dispatch<SetStateAction<string>>;
  setGroupManageSessionIds: Dispatch<SetStateAction<string[]>>;
  setGroupManageModeDraft: Dispatch<SetStateAction<string>>;
  setGroupManagePurposeDraft: Dispatch<SetStateAction<string>>;
  setProjectBusDraft: Dispatch<SetStateAction<string>>;
  editingSessionIdRef: MutableRefObject<string | null>;
  /** Live rename draft while create remaps temp → real id. */
  editingSessionTitleRef: MutableRefObject<string>;
  setEditingSessionId: Dispatch<SetStateAction<string | null>>;
  setEditingSessionTitle: Dispatch<SetStateAction<string>>;
  /** Ignore rename blur for a short window after optimistic create remounts the tab. */
  suppressRenameBlurUntilRef: MutableRefObject<number>;
};

export type UseChatWorkspaceLifecycleResult = {
  createSessionMutation: UseMutationResult<SessionDetail, Error, { agentId: string }, unknown>;
  createGroupRoomMutation: UseMutationResult<
    ChatRoomDetail,
    Error,
    { title: string; agentIds: string[]; mode: string; purpose: string },
    { routeSelectionAtRequest: ChatRouteSelection }
  >;
  startGroupRoundMutation: UseMutationResult<
    ChatRoomRoundAcceptedResponse,
    Error,
    { roomId: string; topic: string; mode: string; purpose: string },
    unknown
  >;
  stopGroupRoundMutation: UseMutationResult<ChatRoomDetail, Error, { roomId: string }, unknown>;
  sendProjectBusMessageMutation: UseMutationResult<
    unknown,
    Error,
    { content: string; interruptTargets: boolean },
    unknown
  >;
  revokeProjectBusMessageMutation: UseMutationResult<unknown, Error, { eventId: string }, unknown>;
  updateGroupRoomMutation: UseMutationResult<
    ChatRoomDetail,
    Error,
    { roomId: string; title: string; sessionIds: string[]; mode: string; purpose: string },
    unknown
  >;
  deleteGroupRoomMutation: UseMutationResult<
    { deleted: boolean; roomId: string },
    Error,
    { roomId: string },
    unknown
  >;
  resetGroupRoomMutation: UseMutationResult<ChatRoomDetail, Error, { roomId: string }, unknown>;
  deleteSessionMutation: UseMutationResult<
    SessionDeleteResponse,
    Error,
    { sessionId: string },
    {
      previousSessions: SessionSummary[] | undefined;
      previousSessionIndexCaches: ReturnType<typeof captureSessionIndexCacheSnapshots>;
      previousAgentSessionCaches: ReturnType<typeof captureAgentSessionCacheSnapshots>;
      previousConversations: ConversationSummary[] | undefined;
      previousAgents: AgentInstance[] | undefined;
    }
  >;
  bulkDeleteSessionsMutation: UseMutationResult<
    SessionBulkDeleteResponse,
    Error,
    { sessionIds: string[] },
    {
      previousSessions: SessionSummary[] | undefined;
      previousSessionIndexCaches: ReturnType<typeof captureSessionIndexCacheSnapshots>;
      previousAgentSessionCaches: ReturnType<typeof captureAgentSessionCacheSnapshots>;
      previousConversations: ConversationSummary[] | undefined;
      previousAgents: AgentInstance[] | undefined;
      previousRouteSessionId: string;
      deletedSessionIds: string[];
      optimisticNextActiveSessionId: string;
      telemetry: ReturnType<typeof startUserAction>;
    }
  >;
  clearSessionHistoryMutation: UseMutationResult<
    AgentDirectSessionResetResponse,
    Error,
    { sessionId: string; agentId: string },
    unknown
  >;
  renameSessionMutation: UseMutationResult<
    SessionDetail,
    Error,
    { sessionId: string; title: string },
    {
      previousSessions: SessionSummary[] | undefined;
      previousSessionIndexCaches: ReturnType<typeof captureSessionIndexCacheSnapshots>;
      previousConversations: ConversationSummary[] | undefined;
      previousDetail: SessionDetail | undefined;
    }
  >;
  addSessionToReviewMutation: UseMutationResult<
    SessionChatReviewCandidateResponse,
    Error,
    { sessionId: string },
    unknown
  >;
};

/**
 * Chat workspace lifecycle mutations: create/delete/rename sessions, group room
 * CRUD/rounds, and project-bus message send/revoke. Does not open EventSources.
 */
export function useChatWorkspaceLifecycle({
  queryClient,
  chatWorkspaceCache,
  lang,
  t,
  describeError,
  syncSessionDetail,
  syncChatRoomDetail,
  clearSessionTransientUiState,
  removeSessionWorkspace,
  requestSessionComposerFocus,
  routeSelectionRef,
  chatRoute,
  setRightIndexPanel,
  setSelectedAgentId,
  setSessionFilter,
  setSessionComposerErrors,
  setGroupComposerOpen,
  setGroupTitleDraft,
  setGroupModeDraft,
  setGroupPurposeDraft,
  setGroupSelectedAgentIds,
  setGroupTopicDraft,
  setGroupRoomActionError,
  setGroupManageTitleDraft,
  setGroupManageSessionIds,
  setGroupManageModeDraft,
  setGroupManagePurposeDraft,
  setProjectBusDraft,
  editingSessionIdRef,
  editingSessionTitleRef,
  setEditingSessionId,
  setEditingSessionTitle,
  suppressRenameBlurUntilRef,
}: UseChatWorkspaceLifecycleOptions): UseChatWorkspaceLifecycleResult {
  const createSessionMutation = useMutation({
    mutationFn: async ({ agentId }: { agentId: string }) =>
      createChatSession({ agentId }),
    onMutate: async ({ agentId }) => {
      const normalizedAgentId = String(agentId || "").trim();
      const telemetry = startUserAction("session_create", { agentId: normalizedAgentId });
      // T0: mint a local temp tab + empty transcript immediately (ChatGPT-style).
      // Real id arrives on success; UI must stay interactive while POST is in flight.
      const tempSessionId = createTempSessionId();
      const nowIso = new Date().toISOString();
      const agents = queryClient.getQueryData<AgentInstance[]>(queryKeys.agents()) ?? [];
      const agentRow = agents.find((item) => String(item.agentId || "").trim() === normalizedAgentId);
      const agentDisplayName = String(agentRow?.displayName || agentRow?.agentCode || "").trim();
      // Match backend: prefer Agent display name so tabs are identifiable immediately.
      const title = agentDisplayName || defaultNewSessionTitle(lang);
      // Remount during temp→real would blur the title input and auto-finish rename; suppress that.
      suppressRenameBlurUntilRef.current = Date.now() + 2500;
      const optimisticDetail: SessionDetail = {
        id: tempSessionId,
        title,
        agentId: normalizedAgentId,
        agentDisplayName: agentDisplayName || undefined,
        status: "idle",
        currentPhase: "ready",
        taskSummary: "",
        lastActive: nowIso,
        updatedAt: nowIso,
        createdAt: nowIso,
        messages: [],
        defaultFileContext: "",
        previewTabs: [],
        activePreviewPath: "",
        changedFiles: [],
        readFiles: [],
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
      // Do not await cancelQueries — waiting freezes tab switching while list
      // queries are in flight, same as deleteSessionMutation.
      void queryClient.cancelQueries({ queryKey: ["sessions", "query"] });
      void queryClient.cancelQueries({ queryKey: ["sessions", "agent"] });
      void queryClient.cancelQueries({ queryKey: ["sessions", "active-bootstrap"] });
      setSessionComposerErrors((current) => ({
        ...current,
        __sessions__: "",
        [tempSessionId]: "",
      }));
      setRightIndexPanel("conversations");
      // Cache first, then switch route — center panel reads cache when query is disabled for temp ids.
      queryClient.setQueryData(queryKeys.session(tempSessionId), optimisticDetail);
      updateSessionSummaryCaches(queryClient, (sessions) =>
        mergeSessionDetailIntoSummaries(sessions, optimisticDetail),
      );
      updateAgentSessionSummaryCaches(queryClient, (sessions) =>
        mergeSessionDetailIntoSummaries(sessions, optimisticDetail),
      );
      reconcileAgentSessionDetailCache(queryClient, optimisticDetail);
      pinSessionCreatePreserve(sessionSummaryFromDetail(optimisticDetail));
      // The temp id enters the URL immediately; the route is the single authority.
      chatRoute.openSession(tempSessionId);
      setSelectedAgentId(normalizedAgentId);
      if (normalizedAgentId) {
        rememberAgentLastSession(
          normalizedAgentId,
          tempSessionId,
          chatAgentSessionStorage(),
        );
      }
      setSessionFilter("");
      editingSessionIdRef.current = tempSessionId;
      editingSessionTitleRef.current = title;
      setEditingSessionId(tempSessionId);
      setEditingSessionTitle(title);
      syncSessionDetail(optimisticDetail);
      return { tempSessionId, agentId: normalizedAgentId, telemetry };
    },
    onSuccess: (nextDetail, variables, context) => {
      const telemetry = context?.telemetry;
      const nextId = String(nextDetail.id || "").trim();
      const tempSessionId = String(context?.tempSessionId || "").trim();
      if (!nextId) {
        telemetry?.failed(undefined, { reason: "missing_session_id" });
        return;
      }
      const agentId = String(nextDetail.agentId || variables.agentId || context?.agentId || "").trim();
      // Prefer server title (now defaults to Agent name); fall back to local Agent label.
      const serverTitle = String(nextDetail.title || "").trim();
      const agentLabel = String(
        nextDetail.agentDisplayName
        || (queryClient.getQueryData<AgentInstance[]>(queryKeys.agents()) ?? [])
          .find((item) => String(item.agentId || "").trim() === agentId)
          ?.displayName
        || "",
      ).trim();
      const fallbackTitle = serverTitle || agentLabel || defaultNewSessionTitle(lang);
      // Keep the operator's in-progress rename draft across temp→real remount.
      const liveDraft = String(editingSessionTitleRef.current || "").trim();
      const keepDraft = Boolean(
        liveDraft
        && liveDraft !== fallbackTitle
        && !isDefaultNewSessionTitle(liveDraft),
      );
      const title = keepDraft ? liveDraft : fallbackTitle;
      const seededDetail: SessionDetail = {
        ...nextDetail,
        id: nextId,
        title,
        agentId,
        messages: Array.isArray(nextDetail.messages) ? nextDetail.messages : [],
      };
      // Seed real id cache BEFORE the route swaps so the UI never paints a hard loading shell.
      queryClient.setQueryData(queryKeys.session(nextId), seededDetail);
      updateSessionSummaryCaches(queryClient, (sessions) =>
        mergeSessionDetailIntoSummaries(sessions, seededDetail),
      );
      updateAgentSessionSummaryCaches(queryClient, (sessions) =>
        mergeSessionDetailIntoSummaries(sessions, seededDetail),
      );
      reconcileAgentSessionDetailCache(queryClient, seededDetail);
      pinSessionCreatePreserve(sessionSummaryFromDetail(seededDetail));
      // Compare-and-swap: only replace temp → real when the user is still on the
      // temp route. A user who already left keeps their page; cache updates only.
      const stillOnTemp = tempSessionId
        ? chatRoute.replaceIfStillViewing(
            { kind: "session", sessionId: tempSessionId },
            { kind: "session", sessionId: nextId },
          )
        : false;
      const keepFocusOnCreated = !tempSessionId || stillOnTemp;
      if (keepFocusOnCreated) {
        // Extend blur suppress through remount so rename field stays open for typing.
        suppressRenameBlurUntilRef.current = Date.now() + 2500;
        editingSessionIdRef.current = nextId;
        editingSessionTitleRef.current = title;
        setEditingSessionId(nextId);
        setEditingSessionTitle(title);
        syncSessionDetail(seededDetail);
      }
      // Drop temp shell after real id is active/cached.
      if (tempSessionId) {
        unpinSessionCreatePreserve(tempSessionId);
        updateSessionSummaryCaches(queryClient, (sessions) =>
          (sessions ?? []).filter((session) => session.id !== tempSessionId),
        );
        updateAgentSessionSummaryCaches(queryClient, (sessions) =>
          (sessions ?? []).filter((session) => session.id !== tempSessionId),
        );
        removeSessionFromAgentSessionCaches(queryClient, tempSessionId);
        queryClient.removeQueries({ queryKey: queryKeys.session(tempSessionId), exact: true });
        removeSessionWorkspace(tempSessionId);
      }
      setSelectedAgentId(agentId);
      if (agentId && keepFocusOnCreated) {
        rememberAgentLastSession(agentId, nextId, chatAgentSessionStorage());
      }
      setSessionComposerErrors((current) => {
        const next = { ...current, [nextId]: "", __sessions__: "" };
        if (tempSessionId) {
          delete next[tempSessionId];
        }
        return next;
      });
      // Progressive hydrate: partial window first (no secondary lists), then full workspace cache refresh.
      void fetchSessionDetailWindow(nextId, {
        messageLimit: 40,
        includeSecondary: false,
        transcriptScope: "window",
      }).then((partial) => {
        if (!partial || String(partial.id || "").trim() !== nextId) {
          return;
        }
        const hydrated = keepDraft
          ? { ...partial, title }
          : partial;
        queryClient.setQueryData<SessionDetail>(queryKeys.session(nextId), (previous) =>
          mergeSessionDetailMessageWindow(previous, hydrated) ?? hydrated,
        );
        updateSessionSummaryCaches(queryClient, (sessions) =>
          mergeSessionDetailIntoSummaries(sessions, hydrated),
        );
        updateAgentSessionSummaryCaches(queryClient, (sessions) =>
          mergeSessionDetailIntoSummaries(sessions, hydrated),
        );
        reconcileAgentSessionDetailCache(queryClient, {
          ...hydrated,
          messages: Array.isArray(hydrated.messages) ? hydrated.messages : [],
        } as SessionDetail);
      }).catch(() => {
        // Keep lightweight create shell; user can still chat.
      });
      // Narrow refresh: avoid another sessions-prefix invalidate that re-fetches
      // bootstrap/agent lists and races the seeded create tab. Conversations and
      // agent directory still need a poke after create.
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.conversations() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.runtimeSummary() }),
        ...(agentId
          ? [
              queryClient.invalidateQueries({ queryKey: queryKeys.agent(agentId) }),
              queryClient.invalidateQueries({ queryKey: queryKeys.agentRuns(agentId) }),
            ]
          : []),
      ]);
      if (keepDraft && keepFocusOnCreated) {
        // Persist the draft name once the real id exists (temp shells cannot PATCH).
        void updateChatSession(nextId, { title }).then((renamed) => {
          const confirmedTitle = String(renamed.title || title).trim() || title;
          const confirmedDetail = {
            ...seededDetail,
            ...renamed,
            id: nextId,
            title: confirmedTitle,
            agentId,
          };
          queryClient.setQueryData(queryKeys.session(nextId), confirmedDetail);
          updateSessionSummaryCaches(queryClient, (sessions) =>
            mergeSessionDetailIntoSummaries(sessions, confirmedDetail),
          );
          updateAgentSessionSummaryCaches(queryClient, (sessions) =>
            mergeSessionDetailIntoSummaries(sessions, confirmedDetail),
          );
          reconcileAgentSessionDetailCache(queryClient, confirmedDetail);
          pinSessionCreatePreserve(sessionSummaryFromDetail(confirmedDetail));
          if (editingSessionIdRef.current === nextId) {
            editingSessionTitleRef.current = confirmedTitle;
            setEditingSessionTitle(confirmedTitle);
          }
        }).catch(() => {
          // Keep local draft title; operator can retry rename from the tab.
        });
      }
      telemetry?.succeeded({
        sessionId: nextId,
        tempSessionId,
        agentId,
        routeReplacedFromTemp: stillOnTemp,
        keepFocusOnCreated,
        keepDraft,
      });
    },
    onError: (error, _variables, context) => {
      context?.telemetry?.failed(error, {
        tempSessionId: String(context?.tempSessionId || "").trim(),
        agentId: String(context?.agentId || "").trim(),
      });
      const tempSessionId = String(context?.tempSessionId || "").trim();
      const failureMessage = describeError(error, t("createSessionFailed"));
      if (tempSessionId) {
        // Keep the temp failure surface on its route. Never auto-restore a
        // previous session; the user retries create or selects another tab.
        setSessionComposerErrors((current) => ({
          ...current,
          [tempSessionId]: failureMessage,
          __sessions__: failureMessage,
        }));
      } else {
        setSessionComposerErrors((current) => ({
          ...current,
          __sessions__: failureMessage,
        }));
      }
      // Do not broad-refresh the index on create failure — that would wipe the
      // temp failure tab. Operator stays on the temp route to retry or leave.
    },
  });

  const createGroupRoomMutation = useMutation({
    mutationFn: async (
      { title, agentIds, mode, purpose }: { title: string; agentIds: string[]; mode: string; purpose: string },
    ) =>
      createChatRoom({ title, agentIds, mode, purpose }),
    onMutate: (variables) => {
      const telemetry = startUserAction("group_room_create", {
        agentCount: variables.agentIds.length,
        mode: variables.mode,
      });
      return {
        routeSelectionAtRequest: routeSelectionRef.current,
        telemetry,
      };
    },
    onSuccess: (room, _variables, context) => {
      context?.telemetry?.succeeded({
        roomId: room.roomId,
        participantCount: room.participants?.length ?? 0,
      });
      setGroupComposerOpen(false);
      setGroupTitleDraft("");
      setGroupModeDraft("round_robin");
      setGroupPurposeDraft("discussion");
      setGroupSelectedAgentIds([]);
      setSessionFilter("");
      setSessionComposerErrors((current) => ({
        ...current,
        __sessions__: "",
      }));
      setRightIndexPanel("members");
      queryClient.setQueryData(queryKeys.chatRoom(room.roomId), room);
      // Enter the new room only while the user still views the request-start route.
      chatRoute.replaceIfStillViewing(
        context?.routeSelectionAtRequest ?? { kind: "bare" },
        { kind: "room", roomId: room.roomId },
      );
      void chatWorkspaceCache.afterChatRoomChanged(room.roomId);
    },
    onError: (error, _variables, context) => {
      context?.telemetry?.failed(error);
      setSessionComposerErrors((current) => ({
        ...current,
        __sessions__: describeError(
          error,
          lang === "zh" ? "创建群聊失败" : "Create group chat failed",
        ),
      }));
    },
  });

  const startGroupRoundMutation = useMutation({
    mutationFn: async (
      { roomId, topic, mode, purpose }: { roomId: string; topic: string; mode: string; purpose: string },
    ) =>
      startChatRoomRound(roomId, { topic, mode, purpose }, { preferAsync: true }),
    onMutate: (variables) => ({
      telemetry: startUserAction("group_round_start", {
        roomId: variables.roomId,
        topicLength: variables.topic.length,
        mode: variables.mode,
      }),
    }),
    onSuccess: (accepted, _variables, context) => {
      context?.telemetry?.succeeded({
        roomId: accepted.roomId,
        roundId: accepted.roundId,
        asyncAccepted: true,
      });
      setRightIndexPanel("members");
      setGroupTopicDraft("");
      setGroupRoomActionError("");
      void chatWorkspaceCache.afterGroupRoundStarted(accepted.roomId);
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, { roomId: variables.roomId });
      setGroupRoomActionError(describeError(error, lang === "zh" ? "启动群聊讨论失败" : "Run group discussion failed"));
      void chatWorkspaceCache.afterChatRoomChanged(routeSelectionRef.current.kind === "room" ? routeSelectionRef.current.roomId : "");
    },
  });

  const stopGroupRoundMutation = useMutation({
    mutationFn: async ({ roomId }: { roomId: string }) =>
      stopChatRoomRound(roomId),
    onMutate: (variables) => ({
      telemetry: startUserAction("group_round_stop", { roomId: variables.roomId }),
    }),
    onSuccess: (room, _variables, context) => {
      context?.telemetry?.succeeded({ roomId: room.roomId });
      setRightIndexPanel("members");
      setGroupRoomActionError("");
      syncChatRoomDetail(room);
      void chatWorkspaceCache.afterGroupRoundStopped(room.roomId);
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, { roomId: variables.roomId });
      setGroupRoomActionError(describeError(error, lang === "zh" ? "停止群聊讨论失败" : "Stop group discussion failed"));
      void chatWorkspaceCache.afterGroupRoundStopped(variables.roomId);
    },
  });

  const sendProjectBusMessageMutation = useMutation({
    mutationFn: async (
      {
        content,
        interruptTargets,
      }: {
        content: string;
        interruptTargets: boolean;
      },
    ) =>
      sendProjectAgentBusMessage({ content, interruptTargets }),
    onMutate: (variables) => ({
      telemetry: startUserAction("project_bus_send", {
        contentLength: variables.content.length,
        interruptTargets: variables.interruptTargets,
      }),
    }),
    onSuccess: (_payload, _variables, context) => {
      context?.telemetry?.succeeded();
      setProjectBusDraft("");
      setGroupRoomActionError("");
      void chatWorkspaceCache.afterProjectBusChanged();
    },
    onError: (error, _variables, context) => {
      context?.telemetry?.failed(error);
      setGroupRoomActionError(describeError(error, lang === "zh" ? "发送总群引导失败" : "Send project bus guidance failed"));
      void chatWorkspaceCache.afterProjectBusFailed();
    },
  });

  const revokeProjectBusMessageMutation = useMutation({
    mutationFn: async ({ eventId }: { eventId: string }) =>
      revokeProjectAgentBusMessage({
        eventId,
        reason: "user_recalled_project_bus_message",
      }),
    onMutate: (variables) => ({
      telemetry: startUserAction("project_bus_revoke", { eventId: variables.eventId }, { destructive: true }),
    }),
    onSuccess: (_payload, _variables, context) => {
      context?.telemetry?.succeeded();
      setGroupRoomActionError("");
      void chatWorkspaceCache.afterProjectBusChanged();
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, { eventId: variables.eventId });
      setGroupRoomActionError(describeError(error, lang === "zh" ? "撤回总群消息失败" : "Recall project bus message failed"));
      void chatWorkspaceCache.afterProjectBusFailed();
    },
  });

  const updateGroupRoomMutation = useMutation({
    mutationFn: async (
      { roomId, title, sessionIds, mode, purpose }: {
        roomId: string;
        title: string;
        sessionIds: string[];
        mode: string;
        purpose: string;
      },
    ) =>
      updateChatRoom(roomId, {
        title,
        participantSessionIds: sessionIds,
        mode,
        purpose,
      }),
    onMutate: (variables) => ({
      telemetry: startUserAction("group_room_update", {
        roomId: variables.roomId,
        participantCount: variables.sessionIds.length,
        mode: variables.mode,
      }),
    }),
    onSuccess: (room, _variables, context) => {
      context?.telemetry?.succeeded({
        roomId: room.roomId,
        participantCount: room.participants.length,
      });
      setRightIndexPanel("members");
      setGroupManageTitleDraft(room.title || "");
      setGroupManageSessionIds(room.participants.map((participant) => participant.sessionId));
      setGroupManageModeDraft(room.mode || "round_robin");
      setGroupManagePurposeDraft(room.purpose || "discussion");
      setGroupRoomActionError("");
      queryClient.setQueryData(queryKeys.chatRoom(room.roomId), room);
      void chatWorkspaceCache.afterChatRoomChanged(room.roomId);
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, { roomId: variables.roomId });
      setGroupRoomActionError(describeError(error, lang === "zh" ? "更新群聊失败" : "Update group failed"));
      if (routeSelectionRef.current.kind === "room") {
        void chatWorkspaceCache.afterChatRoomChanged(routeSelectionRef.current.roomId);
      }
    },
  });

  const deleteGroupRoomMutation = useMutation({
    mutationFn: async ({ roomId }: { roomId: string }) =>
      deleteChatRoom(roomId),
    onMutate: (variables) => ({
      telemetry: startUserAction("group_room_delete", { roomId: variables.roomId }, { destructive: true }),
    }),
    onSuccess: (_payload, variables, context) => {
      const routeReplaced = chatRoute.replaceIfStillViewing(
        { kind: "room", roomId: variables.roomId },
        { kind: "bare" },
      );
      context?.telemetry?.succeeded({
        roomId: variables.roomId,
        routeReplaced,
      });
      setRightIndexPanel("conversations");
      setGroupTopicDraft("");
      setGroupRoomActionError("");
      setGroupManageTitleDraft("");
      setGroupManageSessionIds([]);
      setGroupManageModeDraft("round_robin");
      queryClient.removeQueries({ queryKey: queryKeys.chatRoom(variables.roomId), exact: true });
      // Only leave the deleted room while the user is still on its route.
      void chatWorkspaceCache.afterChatRoomChanged(variables.roomId);
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, { roomId: variables.roomId });
      setGroupRoomActionError(describeError(error, lang === "zh" ? "删除群聊失败" : "Delete group failed"));
    },
  });

  const resetGroupRoomMutation = useMutation({
    mutationFn: async ({ roomId }: { roomId: string }) =>
      resetChatRoom(roomId),
    onMutate: (variables) => ({
      telemetry: startUserAction("group_room_reset", { roomId: variables.roomId }, { destructive: true }),
    }),
    onSuccess: (room, _variables, context) => {
      context?.telemetry?.succeeded({ roomId: room.roomId });
      setRightIndexPanel("members");
      setGroupRoomActionError("");
      syncChatRoomDetail(room);
      void chatWorkspaceCache.afterChatRoomChanged(room.roomId);
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, { roomId: variables.roomId });
      setGroupRoomActionError(describeError(error, lang === "zh" ? "重置群聊失败" : "Reset group failed"));
      if (routeSelectionRef.current.kind === "room") {
        void chatWorkspaceCache.afterChatRoomChanged(routeSelectionRef.current.roomId);
      }
    },
  });

  const deleteSessionMutation = useMutation({
    mutationFn: async ({ sessionId }: { sessionId: string }) =>
      deleteChatSession(sessionId),
    onMutate: async (variables) => {
      const telemetry = startUserAction("session_delete", { sessionId: variables.sessionId }, { destructive: true });
      // Do not await cancelQueries — waiting freezes tab switching while list
      // queries settle. Optimistic UI must apply immediately.
      markSessionDeleteTombstone(variables.sessionId);
      void queryClient.cancelQueries({ queryKey: queryKeys.sessions() });
      void queryClient.cancelQueries({ queryKey: queryKeys.conversations() });
      void queryClient.cancelQueries({ queryKey: queryKeys.agents() });
      void queryClient.cancelQueries({ queryKey: queryKeys.session(variables.sessionId) });

      const previousSessions = queryClient.getQueryData<SessionSummary[]>(queryKeys.sessions());
      const previousSessionIndexCaches = captureSessionIndexCacheSnapshots(queryClient);
      const previousAgentSessionCaches = captureAgentSessionCacheSnapshots(queryClient);
      const previousConversations = queryClient.getQueryData<ConversationSummary[]>(queryKeys.conversations());
      const previousAgents = queryClient.getQueryData<AgentInstance[]>(queryKeys.agents());
      const previousRouteSessionId = routeSelectionRef.current.kind === "session"
        ? routeSelectionRef.current.sessionId
        : "";
      const deletedAgentId = String(
        (previousSessions ?? []).find((session) => session.id === variables.sessionId)?.agentId || "",
      ).trim();

      updateSessionSummaryCaches(queryClient, (sessions) =>
        sessions?.filter((session) => session.id !== variables.sessionId),
      );
      removeSessionFromAgentSessionCaches(queryClient, variables.sessionId);
      queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations(), (conversations) =>
        removeDeletedSessionFromConversations(conversations, variables.sessionId),
      );
      queryClient.setQueryData<AgentInstance[]>(queryKeys.agents(), (agents) =>
        agents?.map((agent) => (
          agent.directSessionId === variables.sessionId
            ? { ...agent, directSessionId: "" }
            : agent
        )),
      );

      const remainingSessions = queryClient.getQueryData<SessionSummary[]>(queryKeys.sessions());
      const optimisticNextActiveSessionId = pickOptimisticNextActiveSessionId(
        remainingSessions,
        variables.sessionId,
        previousRouteSessionId,
        deletedAgentId,
      );

      // Instant handoff: remove workspace and leave the deleted tab before DELETE
      // returns. Compare-and-swap keeps the user's page when they already left.
      clearSessionTransientUiState(variables.sessionId);
      removeSessionWorkspace(variables.sessionId);
      if (previousRouteSessionId === variables.sessionId) {
        const routeReplaced = chatRoute.replaceIfStillViewing(
          { kind: "session", sessionId: variables.sessionId },
          optimisticNextActiveSessionId
            ? { kind: "session", sessionId: optimisticNextActiveSessionId }
            : { kind: "bare" },
        );
        if (optimisticNextActiveSessionId) {
          if (routeReplaced) {
            requestSessionComposerFocus(optimisticNextActiveSessionId);
          }
          setSessionComposerErrors((current) => ({
            ...current,
            [variables.sessionId]: "",
            [optimisticNextActiveSessionId]: "",
            __sessions__: "",
          }));
          // Warm next detail in background; do not block delete network call.
          void queryClient.prefetchQuery({
            queryKey: queryKeys.session(optimisticNextActiveSessionId),
            queryFn: () =>
              fetchSessionDetail(optimisticNextActiveSessionId),
          }).catch(() => undefined);
        }
      }

      setGroupManageSessionIds((current) => current.filter((sessionId) => sessionId !== variables.sessionId));

      return {
        previousSessions,
        previousSessionIndexCaches,
        previousAgentSessionCaches,
        previousConversations,
        previousAgents,
        previousRouteSessionId,
        optimisticNextActiveSessionId,
        telemetry,
      };
    },
    onSuccess: (deleteResult, variables, context) => {
      const serverNextActiveSessionId = String(deleteResult.nextActiveSessionId || "").trim();
      const optimisticNextActiveSessionId = String(context?.optimisticNextActiveSessionId || "").trim();
      const nextActiveSessionId = serverNextActiveSessionId || optimisticNextActiveSessionId;
      let routeReplaced = false;

      // Keep the user's post-delete selection if they already switched tabs.
      // Only apply server next-active while the route still sits on the deleted id.
      if (nextActiveSessionId && nextActiveSessionId !== variables.sessionId) {
        routeReplaced = chatRoute.replaceIfStillViewing(
          { kind: "session", sessionId: variables.sessionId },
          { kind: "session", sessionId: nextActiveSessionId },
        );
        if (routeReplaced) {
          requestSessionComposerFocus(nextActiveSessionId);
        }
        setSessionComposerErrors((current) => ({
          ...current,
          [nextActiveSessionId]: "",
        }));
      }
      context?.telemetry?.succeeded({
        sessionId: variables.sessionId,
        previousRouteSessionId: String(context?.previousRouteSessionId || "").trim(),
        optimisticNextActiveSessionId,
        serverNextActiveSessionId,
        nextActiveSessionId,
        routeReplaced,
      });
      void chatWorkspaceCache.afterSessionDeleted({
        deletedSessionId: variables.sessionId,
        roomId: routeSelectionRef.current.kind === "room" ? routeSelectionRef.current.roomId : "",
      });
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, { sessionId: variables.sessionId });
      // Allow the row back into lists after a failed delete.
      clearSessionDeleteTombstone(variables.sessionId);
      if (context?.previousSessions) {
        queryClient.setQueryData(queryKeys.sessions(), context.previousSessions);
      }
      restoreSessionIndexCacheSnapshots(queryClient, context?.previousSessionIndexCaches);
      restoreAgentSessionCacheSnapshots(queryClient, context?.previousAgentSessionCaches);
      if (context?.previousConversations) {
        queryClient.setQueryData(queryKeys.conversations(), context.previousConversations);
      }
      if (context?.previousAgents !== undefined) {
        queryClient.setQueryData(queryKeys.agents(), context.previousAgents);
      }
      // Failed delete keeps the current route; never roll back navigation.
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("deleteSessionFailed")),
      }));
      void chatWorkspaceCache.refreshSessionRuntime(variables.sessionId);
    },
  });

  const bulkDeleteSessionsMutation = useMutation({
    mutationFn: async ({ sessionIds }: { sessionIds: string[] }) =>
      bulkDeleteChatSessions(sessionIds),
    onMutate: async (variables) => {
      const deletedSessionIds = [...new Set(
        variables.sessionIds.map((sessionId) => String(sessionId || "").trim()).filter(Boolean),
      )];
      const telemetry = startUserAction(
        "session_delete",
        { sessionIds: deletedSessionIds.join(",") },
        { destructive: true },
      );
      deletedSessionIds.forEach((sessionId) => markSessionDeleteTombstone(sessionId));
      void queryClient.cancelQueries({ queryKey: queryKeys.sessions() });
      void queryClient.cancelQueries({ queryKey: queryKeys.conversations() });
      void queryClient.cancelQueries({ queryKey: queryKeys.agents() });
      deletedSessionIds.forEach((sessionId) => {
        void queryClient.cancelQueries({ queryKey: queryKeys.session(sessionId) });
      });

      const previousSessions = queryClient.getQueryData<SessionSummary[]>(queryKeys.sessions());
      const previousSessionIndexCaches = captureSessionIndexCacheSnapshots(queryClient);
      const previousAgentSessionCaches = captureAgentSessionCacheSnapshots(queryClient);
      const previousConversations = queryClient.getQueryData<ConversationSummary[]>(queryKeys.conversations());
      const previousAgents = queryClient.getQueryData<AgentInstance[]>(queryKeys.agents());
      const previousRouteSessionId = routeSelectionRef.current.kind === "session"
        ? routeSelectionRef.current.sessionId
        : "";
      const deletedSessionIdSet = new Set(deletedSessionIds);

      updateSessionSummaryCaches(queryClient, (sessions) =>
        sessions?.filter((session) => !deletedSessionIdSet.has(session.id)),
      );
      deletedSessionIds.forEach((sessionId) => {
        removeSessionFromAgentSessionCaches(queryClient, sessionId);
      });
      queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations(), (conversations) =>
        (conversations ?? []).filter((conversation) => {
          const sessionId = String(conversation.directSessionId || conversation.conversationId || "").trim();
          return !deletedSessionIdSet.has(sessionId);
        }),
      );
      queryClient.setQueryData<AgentInstance[]>(queryKeys.agents(), (agents) =>
        agents?.map((agent) => (
          agent.directSessionId && deletedSessionIdSet.has(agent.directSessionId)
            ? { ...agent, directSessionId: "" }
            : agent
        )),
      );

      const remainingSessions = queryClient.getQueryData<SessionSummary[]>(queryKeys.sessions());
      const routeDeletedSessionId = deletedSessionIdSet.has(previousRouteSessionId)
        ? previousRouteSessionId
        : "";
      const deletedAgentId = routeDeletedSessionId
        ? String(
          (previousSessions ?? []).find((session) => session.id === routeDeletedSessionId)?.agentId || "",
        ).trim()
        : "";
      const optimisticNextActiveSessionId = routeDeletedSessionId
        ? pickOptimisticNextActiveSessionId(
          remainingSessions,
          routeDeletedSessionId,
          previousRouteSessionId,
          deletedAgentId,
        )
        : "";

      deletedSessionIds.forEach((sessionId) => {
        clearSessionTransientUiState(sessionId);
        removeSessionWorkspace(sessionId);
      });
      if (routeDeletedSessionId) {
        const routeReplaced = chatRoute.replaceIfStillViewing(
          { kind: "session", sessionId: routeDeletedSessionId },
          optimisticNextActiveSessionId
            ? { kind: "session", sessionId: optimisticNextActiveSessionId }
            : { kind: "bare" },
        );
        if (optimisticNextActiveSessionId && routeReplaced) {
          requestSessionComposerFocus(optimisticNextActiveSessionId);
        }
      }

      setGroupManageSessionIds((current) => current.filter((sessionId) => !deletedSessionIdSet.has(sessionId)));

      return {
        previousSessions,
        previousSessionIndexCaches,
        previousAgentSessionCaches,
        previousConversations,
        previousAgents,
        previousRouteSessionId,
        deletedSessionIds,
        optimisticNextActiveSessionId,
        telemetry,
      };
    },
    onSuccess: (deleteResult, _variables, context) => {
      const serverNextActiveSessionId = String(deleteResult.nextActiveSessionId || "").trim();
      const optimisticNextActiveSessionId = String(context?.optimisticNextActiveSessionId || "").trim();
      const nextActiveSessionId = serverNextActiveSessionId || optimisticNextActiveSessionId;
      const deletedSessionIds = context?.deletedSessionIds ?? [];
      const previousRouteSessionId = String(context?.previousRouteSessionId || "").trim();
      let routeReplaced = false;

      if (
        nextActiveSessionId
        && previousRouteSessionId
        && deletedSessionIds.includes(previousRouteSessionId)
        && nextActiveSessionId !== previousRouteSessionId
      ) {
        routeReplaced = chatRoute.replaceIfStillViewing(
          { kind: "session", sessionId: previousRouteSessionId },
          { kind: "session", sessionId: nextActiveSessionId },
        );
        if (routeReplaced) {
          requestSessionComposerFocus(nextActiveSessionId);
        }
      }

      context?.telemetry?.succeeded({
        deletedCount: deleteResult.summary?.successCount ?? deletedSessionIds.length,
        skippedCount: deleteResult.summary?.skippedCount ?? 0,
        failedCount: deleteResult.summary?.failedCount ?? 0,
        previousRouteSessionId,
        optimisticNextActiveSessionId,
        serverNextActiveSessionId,
        nextActiveSessionId,
        routeReplaced,
      });

      deletedSessionIds.forEach((sessionId) => {
        void chatWorkspaceCache.afterSessionDeleted({
          deletedSessionId: sessionId,
          roomId: routeSelectionRef.current.kind === "room" ? routeSelectionRef.current.roomId : "",
        });
      });
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, {
        sessionIds: variables.sessionIds.join(","),
      });
      (context?.deletedSessionIds ?? variables.sessionIds).forEach((sessionId) => {
        clearSessionDeleteTombstone(sessionId);
      });
      if (context?.previousSessions) {
        queryClient.setQueryData(queryKeys.sessions(), context.previousSessions);
      }
      restoreSessionIndexCacheSnapshots(queryClient, context?.previousSessionIndexCaches);
      restoreAgentSessionCacheSnapshots(queryClient, context?.previousAgentSessionCaches);
      if (context?.previousConversations) {
        queryClient.setQueryData(queryKeys.conversations(), context.previousConversations);
      }
      if (context?.previousAgents !== undefined) {
        queryClient.setQueryData(queryKeys.agents(), context.previousAgents);
      }
      setSessionComposerErrors((current) => ({
        ...current,
        __sessions__: describeError(error, t("deleteSessionFailed")),
      }));
      (context?.deletedSessionIds ?? variables.sessionIds).forEach((sessionId) => {
        void chatWorkspaceCache.refreshSessionRuntime(sessionId);
      });
    },
  });

  const clearSessionHistoryMutation = useMutation({
    mutationFn: async ({ sessionId, agentId }: { sessionId: string; agentId: string }) =>
      resetAgentDirectSession(agentId, sessionId),
    onMutate: (variables) => ({
      telemetry: startUserAction("session_clear_history", {
        sessionId: variables.sessionId,
        agentId: variables.agentId,
      }, { destructive: true }),
    }),
    onSuccess: (result, variables, context) => {
      const previousDirectSessionId = String(
        result.resetSummary.previousDirectSessionId || variables.sessionId,
      ).trim();
      const replacementDirectSessionId = String(result.resetSummary.replacementDirectSessionId || "").trim();
      if (!result.resetSummary.resetDirectSession || !replacementDirectSessionId) {
        context?.telemetry?.failed(undefined, {
          sessionId: variables.sessionId,
          agentId: variables.agentId,
          reason: "reset_not_applied",
        });
        setSessionComposerErrors((current) => ({
          ...current,
          [variables.sessionId]: t("clearSessionHistoryFailed"),
        }));
        void chatWorkspaceCache.afterChatWorkspaceReset();
        return;
      }
      if (previousDirectSessionId) {
        // Stop in-flight old-id requests (detail/llm-options/select) that were
        // resurrecting deleted sessions via workspace recovery.
        void queryClient.cancelQueries({ queryKey: queryKeys.session(previousDirectSessionId) });
        void queryClient.cancelQueries({ queryKey: queryKeys.sessionLlmOptions(previousDirectSessionId) });
        clearSessionTransientUiState(previousDirectSessionId);
        queryClient.removeQueries({ queryKey: queryKeys.session(previousDirectSessionId), exact: true });
        queryClient.removeQueries({ queryKey: queryKeys.sessionLlmOptions(previousDirectSessionId), exact: true });
        removeSessionWorkspace(previousDirectSessionId);
        // Optimistically drop the old row from list caches so UI does not flash a duplicate.
        updateSessionSummaryCaches(queryClient, (sessions) =>
          (sessions ?? []).filter((session) => session.id !== previousDirectSessionId),
        );
        queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations(), (conversations) =>
          removeDeletedSessionFromConversations(conversations, previousDirectSessionId),
        );
      }
      queryClient.setQueryData<AgentInstance[]>(queryKeys.agents(), (agents) =>
        agents?.map((agent) => (agent.agentId === result.agent.agentId ? result.agent : agent)),
      );
      // Compare-and-swap: old id → replacement only while the user still views it.
      const routeReplaced = chatRoute.replaceIfStillViewing(
        { kind: "session", sessionId: previousDirectSessionId },
        { kind: "session", sessionId: replacementDirectSessionId },
      );
      context?.telemetry?.succeeded({
        sessionId: variables.sessionId,
        agentId: variables.agentId,
        previousDirectSessionId,
        replacementDirectSessionId,
        routeReplaced,
      });
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: "",
        [replacementDirectSessionId]: "",
        __sessions__: "",
      }));
      // Prefer targeted cache update over a full sessions remove+invalidate thrash.
      void chatWorkspaceCache.afterSessionDeleted({
        deletedSessionId: previousDirectSessionId || variables.sessionId,
      });
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, {
        sessionId: variables.sessionId,
        agentId: variables.agentId,
      });
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("clearSessionHistoryFailed")),
      }));
      void chatWorkspaceCache.afterChatWorkspaceReset();
    },
  });

  const renameSessionMutation = useMutation({
    mutationFn: async ({ sessionId, title }: { sessionId: string; title: string }) =>
      updateChatSession(sessionId, { title }),
    onMutate: (variables) => {
      const telemetry = startUserAction("session_rename", {
        sessionId: variables.sessionId,
        titleLength: variables.title.length,
      });
      const updatedAt = new Date().toISOString();
      const previousSessions = queryClient.getQueryData<SessionSummary[]>(queryKeys.sessions());
      const previousSessionIndexCaches = captureSessionIndexCacheSnapshots(queryClient);
      const previousAgentSessionCaches = captureAgentSessionCacheSnapshots(queryClient);
      const previousConversations = queryClient.getQueryData<ConversationSummary[]>(queryKeys.conversations());
      const previousDetail = queryClient.getQueryData<SessionDetail>(queryKeys.session(variables.sessionId));
      const targetSession = previousDetail ?? previousSessions?.find((session) => session.id === variables.sessionId);
      const renameSummaries = (sessions: SessionSummary[] | undefined) =>
        renameSessionInSummaries(sessions, variables.sessionId, variables.title, updatedAt);
      editingSessionIdRef.current = null;
      setEditingSessionId(null);
      setEditingSessionTitle("");
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      updateSessionSummaryCaches(queryClient, renameSummaries);
      updateAgentSessionSummaryCaches(queryClient, renameSummaries);
      queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations(), (conversations) =>
        renameSessionInConversations(conversations, variables.sessionId, variables.title, updatedAt, targetSession),
      );
      queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), (detail) =>
        renameSessionDetail(detail, variables.sessionId, variables.title, updatedAt),
      );
      // Session tab rename must not rewrite Agent displayName (multi-session Agents).
      return {
        previousSessions,
        previousSessionIndexCaches,
        previousAgentSessionCaches,
        previousConversations,
        previousDetail,
        telemetry,
      };
    },
    onSuccess: (nextDetail, variables, context) => {
      context?.telemetry?.succeeded({
        sessionId: variables.sessionId,
        titleLength: String(nextDetail.title || variables.title).trim().length,
      });
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      const confirmedTitle = String(nextDetail.title || variables.title).trim() || variables.title;
      const confirmedUpdatedAt = String(nextDetail.updatedAt || new Date().toISOString()).trim();
      const renameSummaries = (sessions: SessionSummary[] | undefined) =>
        renameSessionInSummaries(sessions, variables.sessionId, confirmedTitle, confirmedUpdatedAt);
      updateSessionSummaryCaches(queryClient, renameSummaries);
      updateAgentSessionSummaryCaches(queryClient, renameSummaries);
      queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations(), (conversations) =>
        renameSessionInConversations(conversations, variables.sessionId, confirmedTitle, confirmedUpdatedAt, nextDetail),
      );
      queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), (detail) =>
        renameSessionDetail(detail, variables.sessionId, confirmedTitle, confirmedUpdatedAt),
      );
      queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), (detail) => ({
        ...(detail ?? nextDetail),
        ...nextDetail,
      }));
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, { sessionId: variables.sessionId });
      if (context?.previousSessions) {
        queryClient.setQueryData(queryKeys.sessions(), context.previousSessions);
      }
      restoreSessionIndexCacheSnapshots(queryClient, context?.previousSessionIndexCaches);
      restoreAgentSessionCacheSnapshots(queryClient, context?.previousAgentSessionCaches);
      if (context?.previousConversations) {
        queryClient.setQueryData(queryKeys.conversations(), context.previousConversations);
      }
      if (context?.previousDetail) {
        queryClient.setQueryData(queryKeys.session(variables.sessionId), context.previousDetail);
      }
      if (!editingSessionIdRef.current || editingSessionIdRef.current === variables.sessionId) {
        editingSessionIdRef.current = variables.sessionId;
        setEditingSessionId(variables.sessionId);
        setEditingSessionTitle(variables.title);
      }
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("renameSessionFailed")),
      }));
    },
  });

  const addSessionToReviewMutation = useMutation({
    mutationFn: async ({ sessionId }: { sessionId: string }) =>
      createSessionChatReviewCandidate(sessionId),
    onMutate: (variables) => ({
      telemetry: startUserAction("session_add_to_review", { sessionId: variables.sessionId }),
    }),
    onSuccess: (payload, variables, context) => {
      context?.telemetry?.succeeded({ sessionId: variables.sessionId });
      const detail = payload.summary
        ? `${t("addSessionToReviewSucceeded")} ${payload.summary}`
        : t("addSessionToReviewSucceeded");
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: detail,
        __sessions__: "",
      }));
      void queryClient.invalidateQueries({ queryKey: queryKeys.evolutionChatReview() });
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, { sessionId: variables.sessionId });
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("addSessionToReviewFailed")),
      }));
      void queryClient.invalidateQueries({ queryKey: queryKeys.evolutionChatReview() });
    },
  });

  return {
    createSessionMutation,
    createGroupRoomMutation,
    startGroupRoundMutation,
    stopGroupRoundMutation,
    sendProjectBusMessageMutation,
    revokeProjectBusMessageMutation,
    updateGroupRoomMutation,
    deleteGroupRoomMutation,
    resetGroupRoomMutation,
    deleteSessionMutation,
    bulkDeleteSessionsMutation,
    clearSessionHistoryMutation,
    renameSessionMutation,
    addSessionToReviewMutation,
  };
}
