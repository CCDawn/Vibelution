import { useMutation, type QueryClient, type UseMutationResult } from "@tanstack/react-query";
import { useEffect, type Dispatch, type MutableRefObject, type SetStateAction } from "react";

import { fetchJson } from "../../api/client";
import type { SessionDetail, SessionSummary } from "../../api/types";
import type { createChatWorkspaceCache } from "../chatWorkspaceCache";

type ChatWorkspaceCache = ReturnType<typeof createChatWorkspaceCache>;
type RightIndexPanel = "conversations" | "members";

export type UseChatSessionSelectionOptions = {
  queryClient: QueryClient;
  chatWorkspaceCache: ChatWorkspaceCache;
  lang: "zh" | "en";
  describeError: (error: unknown, fallback: string) => string;
  syncSessionDetail: (detail: SessionDetail) => void;
  setSessionComposerErrors: Dispatch<SetStateAction<Record<string, string>>>;
  latestDirectSessionSelectionRef: MutableRefObject<string>;
  reselectDirectSessionRef: MutableRefObject<(sessionId: string) => void>;
  activeSessionId: string | null | undefined;
  setActiveSession: (sessionId: string) => void;
  activeGroupRoomId: string;
  setActiveGroupRoomId: Dispatch<SetStateAction<string>>;
  requestedSessionId: string;
  requestedRoomId: string;
  bootstrapActiveSessionId: string | null | undefined;
  sessions: SessionSummary[] | undefined;
  setRightIndexPanel: Dispatch<SetStateAction<RightIndexPanel>>;
  setRightPaneCollapsed: Dispatch<SetStateAction<boolean>>;
  setGroupRoomActionError: Dispatch<SetStateAction<string>>;
};

export type UseChatSessionSelectionResult = {
  selectDirectSessionMutation: UseMutationResult<SessionDetail, Error, string, unknown>;
};

/**
 * Direct-session select mutation + URL/bootstrap selection effects.
 * Does not open EventSource streams.
 */
export function useChatSessionSelection({
  chatWorkspaceCache,
  lang,
  describeError,
  syncSessionDetail,
  setSessionComposerErrors,
  latestDirectSessionSelectionRef,
  reselectDirectSessionRef,
  activeSessionId,
  setActiveSession,
  activeGroupRoomId,
  setActiveGroupRoomId,
  requestedSessionId,
  requestedRoomId,
  bootstrapActiveSessionId,
  sessions,
  setRightIndexPanel,
  setRightPaneCollapsed,
  setGroupRoomActionError,
}: UseChatSessionSelectionOptions): UseChatSessionSelectionResult {
  const selectDirectSessionMutation = useMutation({
    mutationFn: async (sessionId: string) =>
      fetchJson<SessionDetail>(`/api/sessions/${encodeURIComponent(sessionId)}/select`, {
        method: "POST",
      }),
    onSuccess: (nextDetail) => {
      const latestSessionId = latestDirectSessionSelectionRef.current;
      if (latestSessionId && latestSessionId !== nextDetail.id) {
        reselectDirectSessionRef.current(latestSessionId);
        return;
      }
      setSessionComposerErrors((current) => ({
        ...current,
        [nextDetail.id]: "",
        __sessions__: "",
      }));
      syncSessionDetail(nextDetail);
      void chatWorkspaceCache.afterSessionSelected();
    },
    onError: (error, sessionId) => {
      if (latestDirectSessionSelectionRef.current !== sessionId) {
        return;
      }
      setSessionComposerErrors((current) => ({
        ...current,
        [sessionId]: describeError(error, lang === "zh" ? "选择会话失败" : "Select session failed"),
      }));
      void chatWorkspaceCache.refreshSessionRuntime(sessionId);
    },
  });

  reselectDirectSessionRef.current = (sessionId: string) => {
    const normalizedSessionId = String(sessionId || "").trim();
    if (!normalizedSessionId) {
      return;
    }
    selectDirectSessionMutation.mutate(normalizedSessionId);
  };

  useEffect(() => {
    if (requestedSessionId || requestedRoomId || activeSessionId) {
      return;
    }
    const bootstrapSessionId = String(bootstrapActiveSessionId ?? "").trim();
    if (!bootstrapSessionId) {
      return;
    }
    setActiveGroupRoomId("");
    setActiveSession(bootstrapSessionId);
  }, [
    activeSessionId,
    bootstrapActiveSessionId,
    requestedRoomId,
    requestedSessionId,
    setActiveGroupRoomId,
    setActiveSession,
  ]);

  useEffect(() => {
    if (requestedRoomId && activeGroupRoomId !== requestedRoomId) {
      setActiveGroupRoomId(requestedRoomId);
      setRightIndexPanel("members");
      setRightPaneCollapsed(false);
      setGroupRoomActionError("");
      return;
    }
    if (
      requestedSessionId
      && !requestedRoomId
      && activeSessionId !== requestedSessionId
    ) {
      setActiveGroupRoomId("");
      setActiveSession(requestedSessionId);
      return;
    }
    if (!activeSessionId && sessions && sessions.length > 0) {
      setActiveSession(sessions[0].id);
      return;
    }
  }, [
    activeGroupRoomId,
    activeSessionId,
    requestedRoomId,
    requestedSessionId,
    sessions,
    setActiveGroupRoomId,
    setActiveSession,
    setGroupRoomActionError,
    setRightIndexPanel,
    setRightPaneCollapsed,
  ]);

  return { selectDirectSessionMutation };
}
