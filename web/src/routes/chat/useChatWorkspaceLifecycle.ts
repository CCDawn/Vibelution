import { useMutation, type QueryClient, type UseMutationResult } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import type { Dispatch, MutableRefObject, SetStateAction } from "react";

import {
  type AgentDirectSessionResetResponse,
} from "../../api/agents";
import {
  createChatSession,
  deleteChatSession,
  updateChatSession,
} from "../../api/chat";
import { queryKeys } from "../../api/queryKeys";
import { startUserAction } from "../../app/userActionTelemetry";
import type {
  AgentInstance,
  ChatRoomDetail,
  ChatRoomRoundAcceptedResponse,
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
  updateAgentSessionSummaryCaches,
  updateSessionSummaryCaches,
} from "../chatSessionIndexQuery";
import {
  mergeSessionDetailIntoSummaries,
  mergeSessionDetailMessageWindow,
  sessionSummaryFromDetail,
} from "../chatSessionState";
import type { createChatWorkspaceCache } from "../chatWorkspaceCache";
import { fetchSessionDetailWindow } from "./chatSessionDetailHelpers";
import {
  pinSessionCreatePreserve,
  unpinSessionCreatePreserve,
} from "../sessionCreatePreserve";
import {
  clearSessionDeleteTombstone,
  isSessionDeleteTombstoned,
  markSessionDeleteTombstone,
} from "../sessionDeleteTombstone";
import { createTempSessionId, isTempSessionId } from "../sessionOptimisticIds";
import { useChatSessionChangeMutations } from "./useChatSessionChangeMutations";
import {
  useChatGroupWorkspaceMutations,
} from "./useChatGroupWorkspaceMutations";
import {
  chatAgentSessionStorage,
  lastSessionForAgent,
  readAgentLastSessionMap,
  rememberAgentLastSession,
} from "./chatAgentSessionMemory";
import {
  consumeTempSessionTitleCommit,
  defaultNewSessionTitle,
  isDefaultNewSessionTitle,
} from "./useChatSessionRenameMenu";
import type { ChatRouteSelection } from "./chatSelectionProjection";
import {
  buildSessionCreateShell,
  forgetSessionCreateRecovery,
  forgetStoredCreateRecovery,
  readSessionCreateRecovery,
  rememberSessionCreateRecovery,
  type SessionCreateRecovery,
} from "./chatSessionCreateRecovery";
import { clearSessionCreateAttempt, markSessionCreateAttempt } from "./sessionCreateAttempt";

type ChatWorkspaceCache = ReturnType<typeof createChatWorkspaceCache>;
type RightIndexPanel = "conversations" | "members";
type SessionCreateVariables = { agentId: string; createIntent?: SessionCreateIntent };
type SessionCreateIntent = SessionCreateRecovery & {
  state: "pending" | "failed";
};
type SessionCreateMutationContext = {
  tempSessionId: string;
  agentId: string;
  idempotencyKey: string;
  telemetry: ReturnType<typeof startUserAction>;
};

type ChatRouteLifecycleActions = {
  openSession: (sessionId: string) => void;
  openRoom: (roomId: string) => void;
  replaceIfStillViewing: (expected: ChatRouteSelection, next: ChatRouteSelection) => boolean;
};

function dropDiscardedCreatedSession(queryClient: QueryClient, sessionId: string): void {
  const id = String(sessionId || "").trim();
  if (!id) {
    return;
  }
  markSessionDeleteTombstone(id);
  unpinSessionCreatePreserve(id);
  updateSessionSummaryCaches(queryClient, (sessions) =>
    (sessions ?? []).filter((session) => session.id !== id),
  );
  updateAgentSessionSummaryCaches(queryClient, (sessions) =>
    (sessions ?? []).filter((session) => session.id !== id),
  );
  removeSessionFromAgentSessionCaches(queryClient, id);
  queryClient.removeQueries({ queryKey: queryKeys.session(id), exact: true });
}

async function deleteDiscardedCreatedSession(sessionId: string): Promise<void> {
  for (let attempt = 0; ; attempt++) {
    try {
      await deleteChatSession(sessionId);
      return;
    } catch (error) {
      const status = error instanceof Error ? (error as Error & { status?: unknown }).status : undefined;
      const transient = error instanceof TypeError || (typeof status === "number"
        && (status === 408 || status === 429 || status >= 500));
      if (!transient || attempt >= 2) throw error;
      await new Promise((resolve) => setTimeout(resolve, attempt === 0 ? 200 : 600));
    }
  }
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
  rebaseSessionComposerState: (fromId: string, toId: string) => void;
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
  /** Live rename draft; only set while the operator is editing a tab title. */
  editingSessionTitleRef: MutableRefObject<string>;
  setEditingSessionId: Dispatch<SetStateAction<string | null>>;
  setEditingSessionTitle: Dispatch<SetStateAction<string>>;
  /** Ignore rename blur for a short window while a temp→real remap remounts an open editor. */
  suppressRenameBlurUntilRef: MutableRefObject<number>;
};

export type UseChatWorkspaceLifecycleResult = {
  createSessionMutation: UseMutationResult<
    SessionDetail,
    Error,
    SessionCreateVariables,
    SessionCreateMutationContext
  >;
  createGroupRoomMutation: UseMutationResult<
    ChatRoomDetail,
    Error,
    { title: string; agentIds: string[]; mode: string; purpose: string },
    {
      routeSelectionAtRequest: ChatRouteSelection;
      tempRoomId: string;
      telemetry: ReturnType<typeof startUserAction>;
    }
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
      previousAgents: AgentInstance[] | undefined;
      deletedAgentId: string;
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
      previousAgentSessionCaches: ReturnType<typeof captureAgentSessionCacheSnapshots>;
      previousDetail: SessionDetail | undefined;
      optimisticUpdatedAt: string;
      attemptId: symbol;
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
  rebaseSessionComposerState,
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
  const createSessionIntentsRef = useRef(new Map<string, SessionCreateIntent>());
  type RenameContext = NonNullable<UseChatWorkspaceLifecycleResult["renameSessionMutation"]["context"]>;
  // Keep only overlapping attempts. Failed snapshots must unwind in submission
  // order even when the failures arrive in the opposite order.
  const renameAttemptsRef = useRef(new Map<string, Array<{
    variables: { sessionId: string; title: string };
    context: RenameContext;
    outcome: "pending" | "succeeded" | "failed";
  }>>());
  const newCreateSessionIdempotencyKey = (): string => {
    const randomUuid = globalThis.crypto?.randomUUID?.();
    return randomUuid
      ? `session-create:${randomUuid}`
      : `session-create:${Date.now()}:${Math.random().toString(36).slice(2)}`;
  };
  const forgetCreateSessionIntent = (tempSessionId: string, expectedKey: string): void => {
    const current = createSessionIntentsRef.current.get(tempSessionId);
    if (current?.idempotencyKey === expectedKey) {
      createSessionIntentsRef.current.delete(tempSessionId);
      clearSessionCreateAttempt(tempSessionId);
    }
    forgetSessionCreateRecovery(tempSessionId, expectedKey);
  };

  const recoveryRouteId = routeSelectionRef.current.kind === "session" ? routeSelectionRef.current.sessionId : "";
  useEffect(() => {
    if (!isTempSessionId(recoveryRouteId) || isSessionDeleteTombstoned(recoveryRouteId)
      || createSessionIntentsRef.current.has(recoveryRouteId)) return;
    const recovery = readSessionCreateRecovery(recoveryRouteId);
    if (!recovery) return;
    // Reload owns no in-flight POST. Let an explicit retry replay the same key.
    // Keep the title in the recovery record. Copying it onto this intent makes
    // the next retry look like an explicit title write and puts back the name
    // from before this document was reloaded.
    createSessionIntentsRef.current.set(recoveryRouteId, {
      tempSessionId: recovery.tempSessionId,
      agentId: recovery.agentId,
      idempotencyKey: recovery.idempotencyKey,
      createdAt: recovery.createdAt,
      state: "failed",
    });
    markSessionCreateAttempt(recoveryRouteId, "failed");
    if (queryClient.getQueryData(queryKeys.session(recoveryRouteId))) return;
    const recoveredTitle = String(recovery.title || "").trim();
    const restoredTitle = recoveredTitle && !isDefaultNewSessionTitle(recoveredTitle)
      ? recoveredTitle
      : defaultNewSessionTitle(lang);
    const detail = buildSessionCreateShell(recovery, restoredTitle);
    queryClient.setQueryData(queryKeys.session(recoveryRouteId), detail);
    updateSessionSummaryCaches(queryClient, (sessions) => mergeSessionDetailIntoSummaries(sessions, detail));
    updateAgentSessionSummaryCaches(queryClient, (sessions) => mergeSessionDetailIntoSummaries(sessions, detail));
    reconcileAgentSessionDetailCache(queryClient, detail);
    pinSessionCreatePreserve(sessionSummaryFromDetail(detail));
    setSelectedAgentId(recovery.agentId);
    syncSessionDetail(detail);
  }, [lang, queryClient, recoveryRouteId, setSelectedAgentId, syncSessionDetail]);

  const createSessionMutation = useMutation({
    mutationFn: async ({ agentId, createIntent }: SessionCreateVariables) => {
      const normalizedAgentId = String(agentId || "").trim();
      if (!createIntent) throw new Error("Session create intent was not prepared.");
      return createChatSession(
        { agentId: normalizedAgentId },
        createIntent.idempotencyKey,
      );
    },
    onMutate: async (variables: SessionCreateVariables) => {
      const { agentId } = variables;
      const normalizedAgentId = String(agentId || "").trim();
      const selectedTempSessionId = routeSelectionRef.current.kind === "session"
        ? String(routeSelectionRef.current.sessionId || "").trim()
        : "";
      const retryIntent = isTempSessionId(selectedTempSessionId)
        ? createSessionIntentsRef.current.get(selectedTempSessionId)
        : undefined;
      const intent = retryIntent?.state === "failed" && retryIntent.agentId === normalizedAgentId
        ? retryIntent
        : {
            agentId: normalizedAgentId,
            idempotencyKey: newCreateSessionIdempotencyKey(),
            tempSessionId: createTempSessionId(),
            createdAt: new Date().toISOString(),
            state: "pending" as const,
          };
      intent.state = "pending";
      variables.createIntent = intent;
      createSessionIntentsRef.current.set(intent.tempSessionId, intent);
      markSessionCreateAttempt(intent.tempSessionId, "pending");
      rememberSessionCreateRecovery(intent);
      const idempotencyKey = intent.idempotencyKey;
      const telemetry = startUserAction("session_create", { agentId: normalizedAgentId });
      // T0: mint a local temp tab + empty transcript immediately (ChatGPT-style).
      // Real id arrives on success; UI must stay interactive while POST is in flight.
      const tempSessionId = intent.tempSessionId;
      const agents = queryClient.getQueryData<AgentInstance[]>(queryKeys.agents()) ?? [];
      const agentRow = agents.find((item) => String(item.agentId || "").trim() === normalizedAgentId);
      const agentDisplayName = String(agentRow?.displayName || agentRow?.agentCode || "").trim();
      // Match backend: a new session starts from the placeholder label; the
      // first user turn generates the real title. A title already committed on
      // this temp shell survives a rejected-create retry.
      const title = defaultNewSessionTitle(lang);
      const existingShellTitle = String(
        queryClient.getQueryData<SessionDetail>(queryKeys.session(tempSessionId))?.title || "",
      ).trim();
      const shellTitle = existingShellTitle && !isDefaultNewSessionTitle(existingShellTitle)
        ? existingShellTitle
        : title;
      const optimisticDetail = buildSessionCreateShell(intent, shellTitle, agentDisplayName || undefined);
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
      syncSessionDetail(optimisticDetail);
      return { tempSessionId, agentId: normalizedAgentId, idempotencyKey, telemetry };
    },
    onSuccess: (nextDetail, variables, context) => {
      const telemetry = context?.telemetry;
      const nextId = String(nextDetail.id || "").trim();
      const tempSessionId = String(context?.tempSessionId || "").trim();
      if (!nextId) {
        const intent = createSessionIntentsRef.current.get(tempSessionId);
        if (intent && intent.idempotencyKey === context?.idempotencyKey) intent.state = "failed";
        markSessionCreateAttempt(tempSessionId, "failed");
        telemetry?.failed(undefined, { reason: "missing_session_id" });
        return;
      }
      // The user already closed this temp tab. Do not pin or insert the real
      // id; delete the server row so a later list refetch cannot bring it back.
      if (tempSessionId && isSessionDeleteTombstoned(tempSessionId)) {
        forgetCreateSessionIntent(tempSessionId, String(context?.idempotencyKey || ""));
        unpinSessionCreatePreserve(tempSessionId);
        dropDiscardedCreatedSession(queryClient, tempSessionId);
        if (nextId !== tempSessionId) {
          dropDiscardedCreatedSession(queryClient, nextId);
          const cleanupTelemetry = startUserAction("session_discard_delete", { sessionId: nextId, tempSessionId }, { destructive: true });
          void deleteDiscardedCreatedSession(nextId).then(() => {
            cleanupTelemetry.succeeded({ sessionId: nextId });
          }).catch((error: unknown) => {
            // The server row still needs an operator action. Make it reachable
            // again without navigating away from the user's later selection.
            clearSessionDeleteTombstone(nextId);
            queryClient.setQueryData(queryKeys.session(nextId), nextDetail);
            updateSessionSummaryCaches(queryClient, (sessions) => mergeSessionDetailIntoSummaries(sessions, nextDetail));
            updateAgentSessionSummaryCaches(queryClient, (sessions) => mergeSessionDetailIntoSummaries(sessions, nextDetail));
            reconcileAgentSessionDetailCache(queryClient, nextDetail);
            pinSessionCreatePreserve(sessionSummaryFromDetail(nextDetail));
            const message = lang === "zh" ? "会话清理未完成，请再次移除会话记录。" : "Session cleanup failed. Remove the session record again.";
            setSessionComposerErrors((current) => ({ ...current, __sessions__: `${message} ${describeError(error, t("deleteSessionFailed"))}` }));
            cleanupTelemetry.failed(error, { sessionId: nextId, recoveryEntryRestored: true });
          });
        }
        telemetry?.succeeded({
          sessionId: nextId,
          tempSessionId,
          agentId: String(nextDetail.agentId || variables.agentId || context?.agentId || "").trim(),
          discardedAfterTempDelete: true,
        });
        return;
      }
      forgetCreateSessionIntent(tempSessionId, String(context?.idempotencyKey || ""));
      clearSessionCreateAttempt(tempSessionId);
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
      // Create no longer enters rename. An open editor wins; once the operator
      // confirms, the closed editor's title stays on the temp shell.
      const titleCommitClosedEditor = Boolean(
        tempSessionId && consumeTempSessionTitleCommit(tempSessionId),
      );
      const editingTempTitle = Boolean(
        tempSessionId && editingSessionIdRef.current === tempSessionId && !titleCommitClosedEditor,
      );
      const cachedTempTitle = tempSessionId && !editingTempTitle
        ? String(queryClient.getQueryData<SessionDetail>(queryKeys.session(tempSessionId))?.title || "").trim()
        : "";
      const liveDraft = editingTempTitle
        ? String(editingSessionTitleRef.current || "").trim()
        : cachedTempTitle;
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
      if (tempSessionId && tempSessionId !== nextId) {
        rebaseSessionComposerState(tempSessionId, nextId);
      }
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
      if (keepFocusOnCreated && editingTempTitle) {
        // Extend blur suppress through remount so the operator's open rename
        // field stays editable while the temp id is replaced by the real id.
        suppressRenameBlurUntilRef.current = Date.now() + 2500;
        editingSessionIdRef.current = nextId;
        editingSessionTitleRef.current = title;
        setEditingSessionId(nextId);
        setEditingSessionTitle(title);
      }
      if (keepFocusOnCreated) {
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
      if (keepFocusOnCreated) setSelectedAgentId(agentId);
      const agentSessionStorage = chatAgentSessionStorage();
      if (agentId && (keepFocusOnCreated || lastSessionForAgent(agentId, readAgentLastSessionMap(agentSessionStorage)) === tempSessionId)) {
        // Rebase the remembered create shell even after switching Agents, but
        // never replace a later last-viewed session chosen for this Agent.
        rememberAgentLastSession(agentId, nextId, agentSessionStorage);
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
        composerStateRebased: Boolean(tempSessionId && tempSessionId !== nextId),
        keepDraft,
      });
    },
    onError: (error, _variables, context) => {
      const tempSessionId = String(context?.tempSessionId || "").trim();
      if (tempSessionId && isSessionDeleteTombstoned(tempSessionId)) {
        // A closed create shell no longer owns a failure surface. Keep the
        // transport failure observable without writing errors onto later views.
        forgetCreateSessionIntent(tempSessionId, String(context?.idempotencyKey || ""));
        context?.telemetry?.failed(error, {
          tempSessionId,
          agentId: String(context?.agentId || "").trim(),
          discardedAfterTempDelete: true,
        });
        return;
      }
      const status = error instanceof Error
        ? (error as Error & { status?: unknown }).status
        : undefined;
      if (status === 409 || status === 410) {
        // The rejected key must not be replayed, but this temp shell still owns
        // the draft. Rotate the key in place so the next click does not open a
        // second empty tab.
        const rejectedTempSessionId = String(context?.tempSessionId || "").trim();
        const expectedKey = String(context?.idempotencyKey || "");
        const rejectedIntent = createSessionIntentsRef.current.get(rejectedTempSessionId);
        if (rejectedIntent && rejectedIntent.idempotencyKey === expectedKey) {
          rejectedIntent.idempotencyKey = newCreateSessionIdempotencyKey();
          rejectedIntent.state = "failed";
          rememberSessionCreateRecovery(rejectedIntent);
        }
      } else {
        const intent = createSessionIntentsRef.current.get(String(context?.tempSessionId || "").trim());
        if (intent && intent.idempotencyKey === context?.idempotencyKey) intent.state = "failed";
      }
      markSessionCreateAttempt(tempSessionId, "failed");
      context?.telemetry?.failed(error, {
        tempSessionId: String(context?.tempSessionId || "").trim(),
        agentId: String(context?.agentId || "").trim(),
      });
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

  const {
    createGroupRoomMutation,
    startGroupRoundMutation,
    stopGroupRoundMutation,
    sendProjectBusMessageMutation,
    revokeProjectBusMessageMutation,
    updateGroupRoomMutation,
    deleteGroupRoomMutation,
    resetGroupRoomMutation,
  } = useChatGroupWorkspaceMutations({
    queryClient,
    chatWorkspaceCache,
    lang,
    describeError,
    syncChatRoomDetail,
    routeSelectionRef,
    chatRoute,
    setRightIndexPanel,
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
  });

  const {
    deleteSessionMutation,
    bulkDeleteSessionsMutation,
    clearSessionHistoryMutation,
    renameSessionMutation,
    addSessionToReviewMutation,
  } = useChatSessionChangeMutations({
    queryClient,
    chatWorkspaceCache,
    lang,
    t,
    describeError,
    clearSessionTransientUiState,
    removeSessionWorkspace,
    requestSessionComposerFocus,
    routeSelectionRef,
    chatRoute,
    setSessionComposerErrors,
    setGroupManageSessionIds,
    editingSessionIdRef,
    setEditingSessionId,
    setEditingSessionTitle,
    createSessionIntentsRef,
    forgetCreateSessionIntent,
    renameAttemptsRef,
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
