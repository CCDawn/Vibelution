/**
 * Session delete, bulk delete, clear-history, rename, and add-to-review.
 * Called at the original mutation site. Rename attempt tracking stays a ref
 * created earlier in the parent so the surrounding hooks keep their order.
 */
import { useMutation } from "@tanstack/react-query";
import type { MutableRefObject } from "react";

import { resetAgentDirectSession } from "../../api/agents";
import {
  bulkDeleteChatSessions,
  createSessionChatReviewCandidate,
  deleteChatSession,
  fetchSessionDetail,
  updateChatSession,
} from "../../api/chat";
import { queryKeys } from "../../api/queryKeys";
import { startUserAction } from "../../app/userActionTelemetry";
import type { AgentInstance, SessionDetail, SessionSummary } from "../../api/types";
import {
  captureAgentSessionCacheSnapshots,
  captureSessionIndexCacheSnapshots,
  removeSessionFromAgentSessionCaches,
  updateAgentSessionSummaryCaches,
  updateSessionSummaryCaches,
} from "../chatSessionIndexQuery";
import {
  pickOptimisticNextActiveSessionId,
  renameSessionDetail,
  renameSessionInSummaries,
} from "../chatSessionState";
import { broadcastSessionIndexChange } from "../chatSessionIndexSync";
import { getPageInstanceId } from "../../app/pageInstance";
import {
  pinSessionCreatePreserve,
  takeSessionCreatePreserve,
} from "../sessionCreatePreserve";
import {
  clearSessionDeleteTombstone,
  isSessionDeleteTombstoned,
  markSessionDeleteTombstone,
} from "../sessionDeleteTombstone";
import {
  chatAgentSessionStorage,
  forgetAgentLastSession,
  forgetAgentLastSessionBySessionId,
  lastSessionForAgent,
  readAgentLastSessionMap,
  rememberAgentLastSession,
} from "./chatAgentSessionMemory";
import { forgetStoredCreateRecovery } from "./chatSessionCreateRecovery";
import { rollbackSessionRename } from "./chatSessionRenameRollback";
import { restoreUndeletedSessionCaches } from "./chatSessionDeleteRollback";
import type {
  UseChatWorkspaceLifecycleOptions,
  UseChatWorkspaceLifecycleResult,
} from "./useChatWorkspaceLifecycle";

type RenameAttempt = {
  variables: { sessionId: string; title: string };
  context: NonNullable<UseChatWorkspaceLifecycleResult["renameSessionMutation"]["context"]>;
  outcome: "pending" | "succeeded" | "failed";
};

/**
 * Drop the deleted session from its Agent's last-viewed pointer.
 * Background-tab deletes leave the pointer alone unless it names the deleted id.
 */
function forgetAgentLastSessionForDeletedSession(sessionId: string, agentId: string): void {
  const deletedSessionId = String(sessionId || "").trim();
  const deletedAgentId = String(agentId || "").trim();
  if (!deletedSessionId) {
    return;
  }
  const storage = chatAgentSessionStorage();
  if (!deletedAgentId) {
    // A sparse catalog may not identify the owner. A completed delete still
    // proves this exact session pointer is stale; retain all other selections.
    forgetAgentLastSessionBySessionId(deletedSessionId, storage);
    return;
  }
  if (lastSessionForAgent(deletedAgentId, readAgentLastSessionMap(storage)) !== deletedSessionId) {
    return;
  }
  forgetAgentLastSession(deletedAgentId, storage);
}

export type UseChatSessionChangeMutationsInput = Pick<
  UseChatWorkspaceLifecycleOptions,
  | "queryClient"
  | "chatWorkspaceCache"
  | "lang"
  | "t"
  | "describeError"
  | "clearSessionTransientUiState"
  | "removeSessionWorkspace"
  | "requestSessionComposerFocus"
  | "routeSelectionRef"
  | "chatRoute"
  | "setSessionComposerErrors"
  | "setGroupManageSessionIds"
  | "editingSessionIdRef"
  | "setEditingSessionId"
  | "setEditingSessionTitle"
> & {
  createSessionIntentsRef: {
    current: {
      get(sessionId: string): { idempotencyKey: string } | undefined;
    };
  };
  forgetCreateSessionIntent: (sessionId: string, idempotencyKey: string) => void;
  renameAttemptsRef: MutableRefObject<Map<string, RenameAttempt[]>>;
};

export function useChatSessionChangeMutations({
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
}: UseChatSessionChangeMutationsInput) {
  const settleRenameAttempt = (sessionId: string, attemptId: symbol | undefined, outcome: "succeeded" | "failed") => {
    const attempts = renameAttemptsRef.current.get(sessionId) ?? [];
    const attempt = attempts.find((entry) => entry.context.attemptId === attemptId);
    if (attempt) attempt.outcome = outcome;
    const isLatest = Boolean(attempt && attempts.at(-1) === attempt);
    if (attempts.every((entry) => entry.outcome !== "pending")) {
      renameAttemptsRef.current.delete(sessionId);
    }
    return { attempts, isLatest };
  };

  const deleteSessionMutation = useMutation({
    mutationFn: async ({ sessionId }: { sessionId: string }) =>
      deleteChatSession(sessionId),
    onMutate: async (variables) => {
      const telemetry = startUserAction("session_delete", { sessionId: variables.sessionId }, { destructive: true });
      // Do not await cancelQueries — waiting freezes tab switching while list
      // queries settle. Optimistic UI must apply immediately.
      // Drop the create pin now. A later sessions refetch must not reattach a
      // tab the user just closed. Keep the summary so a failed delete can pin it again.
      const releasedCreatePreserve = takeSessionCreatePreserve(variables.sessionId);
      markSessionDeleteTombstone(variables.sessionId);
      void queryClient.cancelQueries({ queryKey: queryKeys.sessions() });
      void queryClient.cancelQueries({ queryKey: queryKeys.conversations() });
      void queryClient.cancelQueries({ queryKey: queryKeys.agents() });
      void queryClient.cancelQueries({ queryKey: queryKeys.session(variables.sessionId) });

      const previousSessions = queryClient.getQueryData<SessionSummary[]>(queryKeys.sessions());
      const previousSessionIndexCaches = captureSessionIndexCacheSnapshots(queryClient);
      const previousAgentSessionCaches = captureAgentSessionCacheSnapshots(queryClient);
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
        previousAgents,
        previousRouteSessionId,
        optimisticNextActiveSessionId,
        deletedAgentId,
        releasedCreatePreserve,
        telemetry,
      };
    },
    onSuccess: (deleteResult, variables, context) => {
      if (!deleteResult.deleted) {
        context?.telemetry?.blocked("delete_unconfirmed", { sessionId: variables.sessionId });
        clearSessionDeleteTombstone(variables.sessionId);
        if (context?.releasedCreatePreserve) pinSessionCreatePreserve(context.releasedCreatePreserve);
        restoreUndeletedSessionCaches(queryClient, [variables.sessionId], context);
        setSessionComposerErrors((current) => ({
          ...current,
          __sessions__: lang === "zh"
            ? "会话未确认删除，草稿已保留。"
            : "Session deletion was not confirmed; drafts were preserved.",
        }));
        void chatWorkspaceCache.refreshSessionRuntime(variables.sessionId);
        return;
      }
      markSessionDeleteTombstone(variables.sessionId, { confirmed: true });
      // Other windows must drop the row from their rails; their index poll is
      // off while a stream owns live queries, so announce the deletion.
      broadcastSessionIndexChange({
        sessionId: variables.sessionId,
        changeType: "delete",
        sourceId: getPageInstanceId(),
      });
      clearSessionTransientUiState(variables.sessionId);
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
      forgetAgentLastSessionForDeletedSession(
        variables.sessionId,
        String(context?.deletedAgentId || "").trim(),
      );
      const deletedCreateIntent = createSessionIntentsRef.current.get(variables.sessionId);
      if (deletedCreateIntent) forgetCreateSessionIntent(variables.sessionId, deletedCreateIntent.idempotencyKey);
      else forgetStoredCreateRecovery(variables.sessionId);
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
      if (context?.releasedCreatePreserve) {
        pinSessionCreatePreserve(context.releasedCreatePreserve);
      }
      restoreUndeletedSessionCaches(queryClient, [variables.sessionId], context);
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
      const releasedCreatePreserves = deletedSessionIds.flatMap((sessionId) => {
        const released = takeSessionCreatePreserve(sessionId);
        return released ? [released] : [];
      });
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
        previousAgents,
        previousRouteSessionId,
        deletedSessionIds,
        optimisticNextActiveSessionId,
        releasedCreatePreserves,
        telemetry,
      };
    },
    onSuccess: (deleteResult, _variables, context) => {
      const serverNextActiveSessionId = String(deleteResult.nextActiveSessionId || "").trim();
      const optimisticNextActiveSessionId = String(context?.optimisticNextActiveSessionId || "").trim();
      const nextActiveSessionId = serverNextActiveSessionId || optimisticNextActiveSessionId;
      const confirmedIds = new Set([
        ...deleteResult.success.filter((item) => item.deleted !== false).map((item) => item.sessionId),
        ...deleteResult.skipped.filter((item) => item.reason === "not_found").map((item) => item.sessionId),
      ]);
      const requestedIds = context?.deletedSessionIds ?? _variables.sessionIds;
      const deletedSessionIds = requestedIds.filter((id) => confirmedIds.has(id));
      const undeletedIds = requestedIds.filter((id) => !confirmedIds.has(id));
      deletedSessionIds.forEach((sessionId) => markSessionDeleteTombstone(sessionId, { confirmed: true }));
      deletedSessionIds.forEach((sessionId) => broadcastSessionIndexChange({
        sessionId,
        changeType: "delete",
        sourceId: getPageInstanceId(),
      }));
      undeletedIds.forEach(clearSessionDeleteTombstone);
      for (const summary of context?.releasedCreatePreserves ?? []) {
        if (undeletedIds.includes(summary.id)) pinSessionCreatePreserve(summary);
      }
      restoreUndeletedSessionCaches(queryClient, undeletedIds, context);
      deletedSessionIds.forEach(clearSessionTransientUiState);
      if (undeletedIds.length) {
        setSessionComposerErrors((current) => ({
          ...current,
          __sessions__: lang === "zh"
            ? `${undeletedIds.length} 个会话未删除，草稿已保留。`
            : `${undeletedIds.length} sessions were not deleted; drafts were preserved.`,
        }));
        undeletedIds.forEach((sessionId) => { void chatWorkspaceCache.refreshSessionRuntime(sessionId); });
      }
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

      const deletedAgentIdBySessionId = new Map(
        (context?.previousSessions ?? []).map((session) => [
          String(session.id || "").trim(),
          String(session.agentId || "").trim(),
        ]),
      );
      deletedSessionIds.forEach((sessionId) => {
        forgetAgentLastSessionForDeletedSession(sessionId, deletedAgentIdBySessionId.get(sessionId) || "");
        const deletedCreateIntent = createSessionIntentsRef.current.get(sessionId);
        if (deletedCreateIntent) forgetCreateSessionIntent(sessionId, deletedCreateIntent.idempotencyKey);
        else forgetStoredCreateRecovery(sessionId);
      });

      context?.telemetry?.succeeded({
        deletedCount: deleteResult.summary?.successCount ?? deletedSessionIds.length,
        confirmedCount: deletedSessionIds.length,
        restoredCount: undeletedIds.length,
        status: deleteResult.status,
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
      for (const summary of context?.releasedCreatePreserves ?? []) {
        pinSessionCreatePreserve(summary);
      }
      restoreUndeletedSessionCaches(queryClient, context?.deletedSessionIds ?? variables.sessionIds, context);
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
      }
      queryClient.setQueryData<AgentInstance[]>(queryKeys.agents(), (agents) =>
        agents?.map((agent) => (agent.agentId === result.agent.agentId ? result.agent : agent)),
      );
      // Compare-and-swap: old id → replacement only while the user still views it.
      const routeReplaced = chatRoute.replaceIfStillViewing(
        { kind: "session", sessionId: previousDirectSessionId },
        { kind: "session", sessionId: replacementDirectSessionId },
      );
      // Clearing is a delete+replace: point the Agent at the new direct session
      // instead of letting the old id linger as a stale last-viewed pointer.
      const lastSessionStorage = chatAgentSessionStorage();
      if (
        previousDirectSessionId
        && replacementDirectSessionId
        && lastSessionForAgent(
          variables.agentId,
          readAgentLastSessionMap(lastSessionStorage),
        ) === previousDirectSessionId
      ) {
        rememberAgentLastSession(variables.agentId, replacementDirectSessionId, lastSessionStorage);
      }
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
      const previousDetail = queryClient.getQueryData<SessionDetail>(queryKeys.session(variables.sessionId));
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
      queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), (detail) =>
        renameSessionDetail(detail, variables.sessionId, variables.title, updatedAt),
      );
      // Session tab rename must not rewrite Agent displayName (multi-session Agents).
      const context = {
        previousSessions,
        previousSessionIndexCaches,
        previousAgentSessionCaches,
        previousDetail,
        optimisticUpdatedAt: updatedAt,
        attemptId: Symbol("session-rename"),
        telemetry,
      };
      const attempts = renameAttemptsRef.current.get(variables.sessionId) ?? [];
      attempts.push({ variables, context, outcome: "pending" });
      renameAttemptsRef.current.set(variables.sessionId, attempts);
      return context;
    },
    onSuccess: (nextDetail, variables, context) => {
      const { isLatest } = settleRenameAttempt(variables.sessionId, context?.attemptId, "succeeded");
      context?.telemetry?.succeeded({
        sessionId: variables.sessionId,
        titleLength: String(nextDetail.title || variables.title).trim().length,
        superseded: !isLatest,
      });
      if (!isLatest || isSessionDeleteTombstoned(variables.sessionId)) return;
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
      queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), (detail) => {
        // Rename owns title fields, not a later archive, pin or live transcript.
        const current = detail ?? nextDetail;
        const renamed = renameSessionDetail(current, variables.sessionId, confirmedTitle, confirmedUpdatedAt);
        if (!renamed) return renamed;
        return {
          ...renamed,
          // Root-tab optimism uses the title as a temporary display label.
          // Confirm the Agent label without replacing a newer identity update.
          agentDisplayName: current.agentDisplayName === variables.title
            ? nextDetail.agentDisplayName ?? current.agentDisplayName
            : current.agentDisplayName,
        };
      });
    },
    onError: (error, variables, context) => {
      const { attempts, isLatest } = settleRenameAttempt(variables.sessionId, context?.attemptId, "failed");
      context?.telemetry?.failed(error, { sessionId: variables.sessionId, superseded: !isLatest });
      if (isSessionDeleteTombstoned(variables.sessionId)) return;
      // A later confirmed rename owns its fields, including when its title is
      // identical to an earlier failed attempt. Replay only failures after it.
      for (let index = attempts.length - 1; index >= 0; index -= 1) {
        const attempt = attempts[index];
        if (attempt.outcome !== "failed") break;
        rollbackSessionRename(queryClient, attempt.variables, attempt.context);
      }
      if (!isLatest) return;
      if (!editingSessionIdRef.current) {
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
    deleteSessionMutation,
    bulkDeleteSessionsMutation,
    clearSessionHistoryMutation,
    renameSessionMutation,
    addSessionToReviewMutation,
  };
}
