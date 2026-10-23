import { useCallback, type Dispatch, type RefObject, type SetStateAction } from "react";
import { useMutation, type QueryClient } from "@tanstack/react-query";

import { updateAgent } from "../../api/agents";
import { forkSessionFromNode, pinChatSession, unpinChatSession } from "../../api/chat";
import { archiveChatSession, unarchiveChatSession } from "../../api/sessionArchive";
import { queryKeys } from "../../api/queryKeys";
import type { AgentInstance, ConversationMessage, SessionDetail, SessionSummary } from "../../api/types";
import { startUserAction } from "../../app/userActionTelemetry";
import {
  captureAgentSessionCacheSnapshots,
  captureSessionIndexCacheSnapshots,
  restoreAgentSessionCacheSnapshots,
  restoreSessionIndexCacheSnapshots,
  updateAgentSessionSummaryCaches,
  updateSessionSummaryCaches,
} from "../chatSessionIndexQuery";
import { mergeSessionDetailIntoSummaries } from "../chatSessionState";
import { broadcastSessionIndexChange } from "../chatSessionIndexSync";
import { getPageInstanceId } from "../../app/pageInstance";
import { describeChatRouteError as describeError } from "./chatCodingRouteViewModel";
import type { createChatWorkspaceCache } from "../chatWorkspaceCache";
import type { TranslationKey } from "../../i18n/dictionaryTypes";
import type { ConversationForkScope } from "../../components/conversation/conversationViewTypes";
import type { ChatRouteNavigateOptions } from "./useChatRouteSelection";
import { describeUncertainChatWrite, refreshChatInBackground, useChatScopedMutationPending } from "./useChatScopedMutationPending";

const SESSION_ARCHIVE_MUTATION_KEY = ["chat", "session-archive-write"] as const;

export type ChatSessionMutationsInput = {
  queryClient: QueryClient;
  chatWorkspaceCache: ReturnType<typeof createChatWorkspaceCache>;
  lang: "zh" | "en";
  t: (key: TranslationKey) => string;
  setSessionComposerErrors: Dispatch<SetStateAction<Record<string, string>>>;
  /** A select captured before an archive write must not restore old read-only flags. */
  latestDirectSessionSelectionRef: RefObject<string | null>;
  directSessionSelectionGenerationRef: RefObject<number>;
  activeSessionId: string | null | undefined;
  syncSessionDetail: (detail: SessionDetail, options?: { transcript?: "merge" | "preserve" }) => void;
  openSession: (sessionId: string, options?: ChatRouteNavigateOptions) => void;
};

/**
 * Session-level archive/pin mutations (ZCode-style metadata flips) with
 * telemetry, optimistic summary-cache patches and rollback. Extracted from
 * ChatCodingRouteWorkbench with identical behavior.
 */
export function useChatSessionMutations({
  queryClient,
  chatWorkspaceCache,
  lang,
  t,
  setSessionComposerErrors,
  latestDirectSessionSelectionRef,
  directSessionSelectionGenerationRef,
  activeSessionId,
  syncSessionDetail,
  openSession,
}: ChatSessionMutationsInput) {
  const archivePending = useChatScopedMutationPending(SESSION_ARCHIVE_MUTATION_KEY, "sessionId");
  // Session-level archive (ZCode-style metadata flip). Optimistic cache update
  // keeps the default list clean immediately; the archived listing refetches.
  const sessionArchiveMutation = useMutation({
    mutationKey: SESSION_ARCHIVE_MUTATION_KEY,
    retry: false,
    mutationFn: async (payload: { sessionId: string; archive: boolean }) => (
      payload.archive
        ? archiveChatSession(payload.sessionId)
        : unarchiveChatSession(payload.sessionId)
    ),
    onMutate: async (variables) => {
      const telemetry = startUserAction(
        variables.archive ? "session_archive" : "session_unarchive",
        { sessionId: variables.sessionId },
      );
      // A select captured before this metadata write must not restore the old
      // read-only flags after the archive command has completed.
      if (latestDirectSessionSelectionRef.current === variables.sessionId) {
        directSessionSelectionGenerationRef.current += 1;
      }
      await queryClient.cancelQueries({ queryKey: queryKeys.sessions() });
      const nextArchiveState = variables.archive
        ? {
            status: "archived",
            source: "session_archive",
            archivedAt: new Date().toISOString(),
          }
        : {};
      const patchArchivedSummary = (session: SessionSummary) => (
        session.id === variables.sessionId
          ? {
              ...session,
              archiveState: nextArchiveState,
              hiddenFromIndex: variables.archive,
              ...(variables.archive ? { pinnedAtMs: null } : {}),
            }
          : session
      );
      updateSessionSummaryCaches(queryClient, (sessions) => sessions?.map(patchArchivedSummary));
      updateAgentSessionSummaryCaches(queryClient, (sessions) => sessions?.map(patchArchivedSummary));
      return { telemetry };
    },
    onSuccess: (_result, variables, context) => {
      context?.telemetry?.succeeded({ sessionId: variables.sessionId });
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      // Archive state is another stream-invisible metadata flip: announce it to
      // the other windows so their index/archive listings refetch.
      broadcastSessionIndexChange({
        sessionId: variables.sessionId,
        changeType: variables.archive ? "archive" : "unarchive",
        sourceId: getPageInstanceId(),
      });
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, { sessionId: variables.sessionId });
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeUncertainChatWrite(error, lang, describeError(
          error,
          variables.archive
            ? lang === "zh" ? "归档会话失败" : "Failed to archive session"
            : lang === "zh" ? "取消归档失败" : "Failed to unarchive session",
        )),
      }));
    },
    onSettled: (_result, _error, variables) => {
      // Read back canonical detail and both directories after success or
      // failure; optimistic summaries cannot own composer admission flags.
      refreshChatInBackground(() => Promise.all([
        chatWorkspaceCache.afterSessionChanged({ sessionId: variables.sessionId }),
        queryClient.invalidateQueries({ queryKey: queryKeys.sessionArchive() }),
        queryClient.invalidateQueries({ queryKey: ["sessions", "finance"] }),
        queryClient.invalidateQueries({ queryKey: ["sessions", "finance-archived"] }),
        queryClient.invalidateQueries({ queryKey: queryKeys.financialAssistants() }),
      ]));
    },
  });
  const pinSessionMutation = useMutation({
    mutationFn: async (payload: { sessionId: string; pinned: boolean }) => (
      payload.pinned
        ? pinChatSession(payload.sessionId)
        : unpinChatSession(payload.sessionId)
    ),
    onMutate: async (variables) => {
      const telemetry = startUserAction(
        variables.pinned ? "session_pin" : "session_unpin",
        { sessionId: variables.sessionId },
      );
      void queryClient.cancelQueries({ queryKey: queryKeys.sessions() });
      // Snapshot for rollback; the optimistic patch flips pinnedAtMs so the
      // pinned rail section reacts on the next render.
      const indexSnapshots = captureSessionIndexCacheSnapshots(queryClient);
      const agentSnapshots = captureAgentSessionCacheSnapshots(queryClient);
      const pinnedAtMs = variables.pinned ? Date.now() : null;
      updateSessionSummaryCaches(queryClient, (sessions) =>
        sessions?.map((session) => session.id === variables.sessionId
          ? { ...session, pinnedAtMs }
          : session),
      );
      updateAgentSessionSummaryCaches(queryClient, (sessions) =>
        sessions?.map((session) => session.id === variables.sessionId
          ? { ...session, pinnedAtMs }
          : session),
      );
      return { telemetry, indexSnapshots, agentSnapshots };
    },
    onSuccess: (_result, variables, context) => {
      context?.telemetry?.succeeded({ sessionId: variables.sessionId });
      // Authoritative pinned_at_ms and ordering come from the next refetch.
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
      // Other windows keep their index poll off while a stream owns live
      // queries; announce the metadata flip so their rail converges too.
      broadcastSessionIndexChange({
        sessionId: variables.sessionId,
        changeType: variables.pinned ? "pin" : "unpin",
        sourceId: getPageInstanceId(),
      });
    },
    onError: (error, variables, context) => {
      restoreSessionIndexCacheSnapshots(queryClient, context?.indexSnapshots);
      restoreAgentSessionCacheSnapshots(queryClient, context?.agentSnapshots);
      context?.telemetry?.failed(error, { sessionId: variables.sessionId });
      setSessionComposerErrors((current) => ({
        ...current,
        __sessions__: describeError(
          error,
          variables.pinned
            ? lang === "zh" ? "置顶会话失败" : "Failed to pin session"
            : lang === "zh" ? "取消置顶失败" : "Failed to unpin session",
        ),
      }));
    },
  });

  const renameAgentMutation = useMutation({
    mutationFn: (payload: { agentId: string; displayName: string }) =>
      updateAgent(payload.agentId, { displayName: payload.displayName }) as Promise<AgentInstance>,
    onMutate: async (payload) => {
      const telemetry = startUserAction("agent_rename", { agentId: payload.agentId });
      await queryClient.cancelQueries({ queryKey: queryKeys.agents() });
      const previousAgents = queryClient.getQueryData<AgentInstance[]>(queryKeys.agents());
      queryClient.setQueryData<AgentInstance[]>(queryKeys.agents(), (current) =>
        current?.map((agent) => agent.agentId === payload.agentId
          ? { ...agent, displayName: payload.displayName }
          : agent),
      );
      return { previousAgents, telemetry };
    },
    onSuccess: (updatedAgent, _variables, context) => {
      context?.telemetry?.succeeded({ agentId: updatedAgent.agentId });
      queryClient.setQueryData<AgentInstance[]>(queryKeys.agents(), (current) =>
        current?.map((agent) => agent.agentId === updatedAgent.agentId ? updatedAgent : agent),
      );
      setSessionComposerErrors((current) => ({ ...current, __sessions__: "" }));
      void chatWorkspaceCache.afterAgentRenamed(updatedAgent.agentId);
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, { agentId: variables.agentId });
      if (context?.previousAgents) {
        queryClient.setQueryData(queryKeys.agents(), context.previousAgents);
      }
      setSessionComposerErrors((current) => ({
        ...current,
        __sessions__: describeError(error, t("loadFailed")),
      }));
    },
  });

  // Branch feature fork exit: ConversationView owns the scope dialog; this
  // handler executes the fork, caches the returned detail, and navigates to
  // the new session. Errors surface on the source session composer and keep
  // the dialog open for retry.
  const handleForkSessionFromNode = useCallback(
    async (message: ConversationMessage, scope: ConversationForkScope) => {
      const sourceSessionId = activeSessionId;
      const nodeId = String(message.nodeId || "").trim();
      if (!sourceSessionId || !nodeId) {
        return;
      }
      try {
        const nextDetail = await forkSessionFromNode(sourceSessionId, { nodeId, scope });
        const nextId = String(nextDetail.id || "").trim();
        if (!nextId) {
          return;
        }
        queryClient.setQueryData(queryKeys.session(nextId), nextDetail);
        updateSessionSummaryCaches(queryClient, (sessions) =>
          mergeSessionDetailIntoSummaries(sessions, nextDetail),
        );
        syncSessionDetail(nextDetail);
        openSession(nextId);
      } catch (exc) {
        setSessionComposerErrors((current) => ({
          ...current,
          [sourceSessionId]: `${t("forkSessionFailed")}: ${describeError(exc, lang === "zh" ? "分叉会话失败" : "Failed to fork session")}`,
        }));
        throw exc;
      }
    },
    [activeSessionId, lang, openSession, queryClient, setSessionComposerErrors, syncSessionDetail, t],
  );

  return {
    sessionArchiveMutation: { ...sessionArchiveMutation, ...archivePending },
    pinSessionMutation, renameAgentMutation, handleForkSessionFromNode,
  };
}
