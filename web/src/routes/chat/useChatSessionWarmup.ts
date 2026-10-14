/**
 * Keep the active session's workspace shell, transcript module, and neighbor
 * detail windows warm. Called after session selection has settled.
 */
import { useEffect, useRef } from "react";
import type { QueryClient } from "@tanstack/react-query";

import { queryKeys } from "../../api/queryKeys";
import type { SessionSummary } from "../../api/types";
import { prefetchConversationView } from "../../components/conversation/prefetchConversationView";
import {
  cancelUnobservedSessionPrefetches,
  prefetchSessionDetailWindow,
  resolveNeighborSessionIdsForPrefetch,
} from "./chatSessionDetailHelpers";
import { touchSessionKeepAlive } from "./chatSessionPaintCache";

export type UseChatSessionWarmupInput = {
  activeSessionId: string | null;
  sessionDetailId: string | undefined;
  hydrateSession: (sessionId: string, previewTabs: string[], activePreviewPath?: string) => void;
  financeSurface: boolean;
  groupPanelActive: boolean;
  secondaryChatDataEnabled: boolean;
  pageVisible: boolean;
  sessions: SessionSummary[] | undefined;
  queryClient: QueryClient;
};

export function useChatSessionWarmup({
  activeSessionId,
  sessionDetailId,
  hydrateSession,
  financeSurface,
  groupPanelActive,
  secondaryChatDataEnabled,
  pageVisible,
  sessions,
  queryClient,
}: UseChatSessionWarmupInput) {
  useEffect(() => {
    if (activeSessionId && sessionDetailId === activeSessionId) {
      hydrateSession(activeSessionId, [], "agent");
    }
  }, [activeSessionId, hydrateSession, sessionDetailId]);

  // C5: keep recent session ids warm (sticky paint + scroll memory lifetime ring).
  useEffect(() => {
    if (!activeSessionId) {
      return;
    }
    touchSessionKeepAlive(activeSessionId);
  }, [activeSessionId]);

  // T1: warm ConversationView after session intent is known (does not mount).
  useEffect(() => {
    if (!activeSessionId || groupPanelActive) {
      return;
    }
    let cancelled = false;
    const run = () => {
      if (!cancelled) {
        void prefetchConversationView();
      }
    };
    const idleRequest = (window as Window & {
      requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => number;
    }).requestIdleCallback;
    const handle = typeof idleRequest === "function"
      ? idleRequest(run, { timeout: 800 })
      : window.setTimeout(run, 120);
    return () => {
      cancelled = true;
      if (typeof idleRequest === "function") {
        (window as Window & { cancelIdleCallback?: (id: number) => void }).cancelIdleCallback?.(handle as number);
      } else {
        window.clearTimeout(handle as number);
      }
    };
  }, [activeSessionId, groupPanelActive]);

  // C: idle-prefetch a few neighbor session detail windows (Cursor list warm pattern).
  const activePrefetchTargetRef = useRef(activeSessionId);
  activePrefetchTargetRef.current = activeSessionId;
  useEffect(() => {
    if (financeSurface || groupPanelActive || !secondaryChatDataEnabled || !pageVisible || !sessions?.length) {
      return;
    }
    const neighborIds = resolveNeighborSessionIdsForPrefetch({
      sessions,
      activeSessionId,
    });
    if (!neighborIds.length) {
      return;
    }
    let cancelled = false;
    const ownedPendingIds = new Set<string>();
    const run = async () => {
      for (const sessionId of neighborIds) {
        if (cancelled) {
          return;
        }
        try {
          const alreadyFetching = queryClient.getQueryState(queryKeys.session(sessionId))?.fetchStatus === "fetching";
          if (!alreadyFetching) ownedPendingIds.add(sessionId);
          await prefetchSessionDetailWindow(queryClient, sessionId);
        } catch {
          return;
        } finally {
          ownedPendingIds.delete(sessionId);
        }
      }
    };
    const idleRequest = (window as Window & {
      requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => number;
    }).requestIdleCallback;
    const handle = typeof idleRequest === "function"
      ? idleRequest(() => void run(), { timeout: 1_500 })
      : window.setTimeout(() => void run(), 280);
    return () => {
      cancelled = true;
      void cancelUnobservedSessionPrefetches(queryClient, ownedPendingIds, activePrefetchTargetRef.current || "");
      if (typeof idleRequest === "function") {
        (window as Window & { cancelIdleCallback?: (id: number) => void }).cancelIdleCallback?.(handle as number);
      } else {
        window.clearTimeout(handle as number);
      }
    };
  }, [activeSessionId, financeSurface, groupPanelActive, pageVisible, queryClient, secondaryChatDataEnabled, sessions]);
}
