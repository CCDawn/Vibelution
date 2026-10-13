import type { Dispatch, RefObject, SetStateAction } from "react";
import { useMutation, type QueryClient } from "@tanstack/react-query";

import { pinChatSession, unpinChatSession } from "../../api/chat";
import { archiveChatSession, unarchiveChatSession } from "../../api/sessionArchive";
import { queryKeys } from "../../api/queryKeys";
import type { SessionSummary } from "../../api/types";
import { startUserAction } from "../../app/userActionTelemetry";
import {
  captureAgentSessionCacheSnapshots,
  captureSessionIndexCacheSnapshots,
  restoreAgentSessionCacheSnapshots,
  restoreSessionIndexCacheSnapshots,
  updateAgentSessionSummaryCaches,
  updateSessionSummaryCaches,
} from "../chatSessionIndexQuery";
import { describeChatRouteError as describeError } from "./chatCodingRouteViewModel";
import type { createChatWorkspaceCache } from "../chatWorkspaceCache";

export type ChatSessionMutationsInput = {
  queryClient: QueryClient;
  chatWorkspaceCache: ReturnType<typeof createChatWorkspaceCache>;
  lang: "zh" | "en";
  setSessionComposerErrors: Dispatch<SetStateAction<Record<string, string>>>;
  /** A select captured before an archive write must not restore old read-only flags. */
  latestDirectSessionSelectionRef: RefObject<string | null>;
  directSessionSelectionGenerationRef: RefObject<number>;
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
  setSessionComposerErrors,
  latestDirectSessionSelectionRef,
  directSessionSelectionGenerationRef,
}: ChatSessionMutationsInput) {
  // Session-level archive (ZCode-style metadata flip). Optimistic cache update
  // keeps the default list clean immediately; the archived listing refetches.
  const sessionArchiveMutation = useMutation({
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
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, { sessionId: variables.sessionId });
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(
          error,
          variables.archive
            ? lang === "zh" ? "归档会话失败" : "Failed to archive session"
            : lang === "zh" ? "取消归档失败" : "Failed to unarchive session",
        ),
      }));
    },
    onSettled: async (_result, _error, variables) => {
      // Read back canonical detail and both directories after success or
      // failure; optimistic summaries cannot own composer admission flags.
      await Promise.all([
        chatWorkspaceCache.afterSessionChanged({ sessionId: variables.sessionId }),
        queryClient.invalidateQueries({ queryKey: queryKeys.sessionArchive() }),
        queryClient.invalidateQueries({ queryKey: ["sessions", "finance"] }),
        queryClient.invalidateQueries({ queryKey: ["sessions", "finance-archived"] }),
        queryClient.invalidateQueries({ queryKey: queryKeys.financialAssistants() }),
      ]);
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

  return { sessionArchiveMutation, pinSessionMutation };
}
