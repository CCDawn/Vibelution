import { useMutation, type QueryClient, type UseMutationResult } from "@tanstack/react-query";
import { useEffect, useRef, type Dispatch, type MutableRefObject, type SetStateAction } from "react";

import { fetchJson } from "../../api/client";
import type { SessionDetail, SessionSummary } from "../../api/types";
import type { createChatWorkspaceCache } from "../chatWorkspaceCache";
import { isTempSessionId } from "../sessionOptimisticIds";
import {
  shouldCanonicalizeUrlSessionSelection,
  shouldDeferUrlSessionSync,
} from "./chatSessionRouteSync";
import { storedChatSelectionBlocksServerBootstrap } from "./useChatSelectionPersistence";

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
  /** Epoch ms when latestDirectSessionSelectionRef was last written by user intent. */
  latestDirectSessionSelectionAtRef: MutableRefObject<number>;
  /** Monotonic generation for the latest user tab selection (stale responses discarded). */
  directSessionSelectionGenerationRef: MutableRefObject<number>;
  /** Permanently retired session ids for this mounted Chat surface. */
  retiredDirectSessionIdsRef: MutableRefObject<ReadonlySet<string>>;
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
  latestDirectSessionSelectionAtRef,
  directSessionSelectionGenerationRef,
  retiredDirectSessionIdsRef,
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
    if (!normalizedSessionId || retiredDirectSessionIdsRef.current.has(normalizedSessionId)) {
      return;
    }
    latestDirectSessionSelectionRef.current = normalizedSessionId;
    latestDirectSessionSelectionAtRef.current = Date.now();
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
    if (storedChatSelectionBlocksServerBootstrap(sessions)) {
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
    sessions,
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
      if (retiredDirectSessionIdsRef.current.has(requestedSessionId)) {
        return;
      }
      // Optimistic switch sets active before React Router updates ?session=.
      // Do not stomp that intent back to the stale URL (looks "stuck" on terra).
      if (
        shouldDeferUrlSessionSync({
          requestedSessionId,
          activeSessionId,
          intentSessionId: latestDirectSessionSelectionRef.current,
          intentAtMs: latestDirectSessionSelectionAtRef.current,
        })
      ) {
        return;
      }
      const shouldCanonicalize = shouldCanonicalizeUrlSessionSelection({
        requestedSessionId,
        activeSessionId,
        intentSessionId: latestDirectSessionSelectionRef.current,
      });
      if (activeSessionId !== requestedSessionId) {
        setActiveGroupRoomId("");
        setActiveSession(requestedSessionId);
        if (isTempSessionId(requestedSessionId)) {
          latestDirectSessionSelectionRef.current = requestedSessionId;
          latestDirectSessionSelectionAtRef.current = Date.now();
        }
      }
      if (shouldCanonicalize) {
        // Explicit deep links must update the same backend active pointer as
        // an in-app tab click; otherwise a remount bootstraps the old session.
        reselectDirectSessionRef.current(requestedSessionId);
      }
      return;
    }
    if (
      requestedSessionId
      && !requestedRoomId
      && !retiredDirectSessionIdsRef.current.has(requestedSessionId)
      && shouldCanonicalizeUrlSessionSelection({
        requestedSessionId,
        activeSessionId,
        intentSessionId: latestDirectSessionSelectionRef.current,
      })
    ) {
      // A hard deep link can paint the same local session while the backend
      // active pointer is still different; canonicalize that route explicitly.
      reselectDirectSessionRef.current(requestedSessionId);
      return;
    }
    if (!activeSessionId && sessions && sessions.length > 0) {
      if (storedChatSelectionBlocksServerBootstrap(sessions)) {
        return;
      }
      setActiveSession(sessions[0].id);
      return;
    }
  }, [
    activeGroupRoomId,
    activeSessionId,
    latestDirectSessionSelectionAtRef,
    latestDirectSessionSelectionRef,
    retiredDirectSessionIdsRef,
    requestedRoomId,
    requestedSessionId,
    reselectDirectSessionRef,
    sessions,
    setActiveGroupRoomId,
    setActiveSession,
    setGroupRoomActionError,
    setRightIndexPanel,
    setRightPaneCollapsed,
  ]);

  return { selectDirectSessionMutation };
}
