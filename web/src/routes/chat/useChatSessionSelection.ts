import { useMutation, type QueryClient, type UseMutationResult } from "@tanstack/react-query";
import { useEffect, useRef, type Dispatch, type MutableRefObject, type SetStateAction } from "react";

import { fetchJson } from "../../api/client";
import type { SessionDetail, SessionSummary } from "../../api/types";
import type { createChatWorkspaceCache } from "../chatWorkspaceCache";

type ChatWorkspaceCache = ReturnType<typeof createChatWorkspaceCache>;
type RightIndexPanel = "conversations" | "members";
type DirectSessionSelectionVariables = { sessionId: string; generation: number };
type DirectSessionSelectionResult = {
  detail: SessionDetail;
  generation: number;
  sessionId: string;
};

export type UseChatSessionSelectionOptions = {
  queryClient: QueryClient;
  chatWorkspaceCache: ChatWorkspaceCache;
  lang: "zh" | "en";
  describeError: (error: unknown, fallback: string) => string;
  syncSessionDetail: (detail: SessionDetail) => void;
  setSessionComposerErrors: Dispatch<SetStateAction<Record<string, string>>>;
  latestDirectSessionSelectionRef: MutableRefObject<string>;
  /** Monotonic generation for the latest user tab selection (stale responses discarded). */
  directSessionSelectionGenerationRef: MutableRefObject<number>;
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
  selectDirectSessionMutation: UseMutationResult<
    DirectSessionSelectionResult,
    Error,
    DirectSessionSelectionVariables,
    unknown
  >;
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
  directSessionSelectionGenerationRef,
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
    mutationFn: async ({ sessionId, generation }: DirectSessionSelectionVariables) => {
      const detail = await fetchJson<SessionDetail>(
        `/api/sessions/${encodeURIComponent(sessionId)}/select`,
        {
          method: "POST",
          headers: { Prefer: "respond-async" },
        },
      );
      return { detail, generation, sessionId };
    },
    onSuccess: ({ detail: nextDetail, generation, sessionId }) => {
      // Drop stale select responses after rapid tab thrash.
      if (generation !== directSessionSelectionGenerationRef.current) {
        return;
      }
      const latestSessionId = latestDirectSessionSelectionRef.current;
      if (latestSessionId && latestSessionId !== nextDetail.id && latestSessionId !== sessionId) {
        reselectDirectSessionRef.current(latestSessionId);
        return;
      }
      if (latestSessionId && latestSessionId !== nextDetail.id) {
        return;
      }
      setSessionComposerErrors((current) => ({
        ...current,
        [nextDetail.id]: "",
        __sessions__: "",
      }));
      // Windowed select payload seeds the session query; GET may still refine it.
      syncSessionDetail(nextDetail);
      void chatWorkspaceCache.afterSessionSelected();
    },
    onError: (error, variables) => {
      if (variables.generation !== directSessionSelectionGenerationRef.current) {
        return;
      }
      if (latestDirectSessionSelectionRef.current !== variables.sessionId) {
        return;
      }
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, lang === "zh" ? "选择会话失败" : "Select session failed"),
      }));
      void chatWorkspaceCache.refreshSessionRuntime(variables.sessionId);
    },
  });

  // Short debounce collapses rapid A→B→A tab thrash into one select POST.
  const selectDebounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  reselectDirectSessionRef.current = (sessionId: string) => {
    const normalizedSessionId = String(sessionId || "").trim();
    if (!normalizedSessionId) {
      return;
    }
    latestDirectSessionSelectionRef.current = normalizedSessionId;
    directSessionSelectionGenerationRef.current += 1;
    const generation = directSessionSelectionGenerationRef.current;
    if (selectDebounceTimerRef.current != null) {
      clearTimeout(selectDebounceTimerRef.current);
    }
    selectDebounceTimerRef.current = setTimeout(() => {
      selectDebounceTimerRef.current = null;
      // Only fire if this generation is still the latest user intent.
      if (generation !== directSessionSelectionGenerationRef.current) {
        return;
      }
      const latestSessionId = latestDirectSessionSelectionRef.current;
      if (!latestSessionId) {
        return;
      }
      selectDirectSessionMutation.mutate({ sessionId: latestSessionId, generation });
    }, 80);
  };

  useEffect(() => () => {
    if (selectDebounceTimerRef.current != null) {
      clearTimeout(selectDebounceTimerRef.current);
      selectDebounceTimerRef.current = null;
    }
  }, []);

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
