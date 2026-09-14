import { useEffect, useRef, type MutableRefObject } from "react";

import type { QueryClient } from "@tanstack/react-query";
import { queryKeys } from "../../api/queryKeys";
import type { SessionSummary } from "../../api/types";
import {
  browserDesktopNotificationBridge,
  subscribeConversationNotificationOpened,
  type DesktopConversationNotifier,
} from "../chatDesktopNotifications";
import { fetchSessionDetailWindow } from "./chatSessionDetailHelpers";

export type UseDesktopConversationAttentionOptions = {
  sessions: SessionSummary[] | undefined;
  queryClient: QueryClient;
  viewedSessionId: string;
  notifierRef: MutableRefObject<DesktopConversationNotifier>;
  onOpenSession: (sessionId: string) => void;
};

/**
 * Watches the session index for background busy→idle completions and
 * routes Electron notification clicks to the owning session.
 */
export function useDesktopConversationAttention({
  sessions,
  queryClient,
  viewedSessionId,
  notifierRef,
  onOpenSession,
}: UseDesktopConversationAttentionOptions): void {
  const viewedSessionIdRef = useRef(viewedSessionId);
  viewedSessionIdRef.current = viewedSessionId;
  const onOpenSessionRef = useRef(onOpenSession);
  onOpenSessionRef.current = onOpenSession;

  useEffect(() => {
    if (!sessions) {
      return;
    }
    const detailSessionIds = notifierRef.current.handleSessionSummaries(sessions, {
      viewedSessionId: viewedSessionIdRef.current,
    });
    // The index summary has no stable turn id. Refresh the formal detail only
    // for a newly observed busy→terminal transition, so stale cached detail
    // cannot identify an older turn and no second polling loop is introduced.
    for (const sessionId of detailSessionIds) {
      void queryClient.fetchQuery({
        queryKey: queryKeys.session(sessionId),
        queryFn: ({ signal }) => fetchSessionDetailWindow(sessionId, {
          includeSecondary: false,
          signal,
        }),
        staleTime: 0,
      }).then((detail) => {
        if (detail) {
          notifierRef.current.handleSessionDetail(detail, {
            viewedSessionId: viewedSessionIdRef.current,
          });
        }
      }).catch(() => undefined);
    }
  }, [notifierRef, queryClient, sessions]);

  useEffect(() => {
    return subscribeConversationNotificationOpened(
      browserDesktopNotificationBridge(),
      (sessionId) => {
        onOpenSessionRef.current(sessionId);
      },
    );
  }, []);
}
