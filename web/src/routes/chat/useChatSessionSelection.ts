import { useMutation, type QueryClient, type UseMutationResult } from "@tanstack/react-query";
import { useEffect, useRef, type Dispatch, type MutableRefObject, type SetStateAction } from "react";

import { selectChatSession } from "../../api/chat";
import type { SessionDetail } from "../../api/types";
import type { createChatWorkspaceCache } from "../chatWorkspaceCache";
import { isTempSessionId } from "../sessionOptimisticIds";

type ChatWorkspaceCache = ReturnType<typeof createChatWorkspaceCache>;
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
  /** Committed-route session target ("" while a room/bus/bare route is active). */
  routeSessionId: string;
  /** Monotonic generation for the latest committed route target (stale responses discarded). */
  directSessionSelectionGenerationRef: MutableRefObject<number>;
  /** Latest committed route target (network dedup only; never a navigation input). */
  latestDirectSessionSelectionRef: MutableRefObject<string>;
  /** Epoch ms when the latest committed route target was stamped. */
  latestDirectSessionSelectionAtRef: MutableRefObject<number>;
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
 * Direct-session last-viewed preference sync + select mutation.
 *
 * The backend `/select` response is only allowed to update the target session
 * cache; it never navigates and never chases a newer pointer. A late response
 * for A while the user already views B updates only A's cache.
 */
export function useChatSessionSelection({
  chatWorkspaceCache,
  lang,
  describeError,
  syncSessionDetail,
  setSessionComposerErrors,
  routeSessionId,
  directSessionSelectionGenerationRef,
  latestDirectSessionSelectionRef,
  latestDirectSessionSelectionAtRef,
}: UseChatSessionSelectionOptions): UseChatSessionSelectionResult {
  const selectDirectSessionMutation = useMutation({
    mutationFn: async ({ sessionId, generation }: DirectSessionSelectionVariables) => {
      const detail = await selectChatSession(sessionId);
      return { detail, generation, sessionId };
    },
    onSuccess: ({ detail: nextDetail, generation }) => {
      // Drop stale select responses after rapid route thrash (network dedup only).
      if (generation !== directSessionSelectionGenerationRef.current) {
        return;
      }
      // Late response for a session the user already left: cache only, never navigate.
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

  // Short debounce collapses rapid A→B→A route thrash into one select POST.
  const selectDebounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const normalizedSessionId = String(routeSessionId || "").trim();
    if (!normalizedSessionId || isTempSessionId(normalizedSessionId)) {
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
      // Only fire if this generation is still the latest committed route target.
      if (generation !== directSessionSelectionGenerationRef.current) {
        return;
      }
      const latestSessionId = latestDirectSessionSelectionRef.current;
      if (!latestSessionId) {
        return;
      }
      selectDirectSessionMutation.mutate({ sessionId: latestSessionId, generation });
    }, 80);
  }, [
    directSessionSelectionGenerationRef,
    latestDirectSessionSelectionAtRef,
    latestDirectSessionSelectionRef,
    routeSessionId,
    selectDirectSessionMutation.mutate,
  ]);

  useEffect(() => () => {
    if (selectDebounceTimerRef.current != null) {
      clearTimeout(selectDebounceTimerRef.current);
      selectDebounceTimerRef.current = null;
    }
  }, []);

  return { selectDirectSessionMutation };
}
