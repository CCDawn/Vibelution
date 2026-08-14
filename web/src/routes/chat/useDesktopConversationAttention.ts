import { useEffect, useRef, type MutableRefObject } from "react";

import type { SessionSummary } from "../../api/types";
import {
  browserDesktopNotificationBridge,
  subscribeConversationNotificationOpened,
  type DesktopConversationNotifier,
} from "../chatDesktopNotifications";

export type UseDesktopConversationAttentionOptions = {
  sessions: SessionSummary[] | undefined;
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
    notifierRef.current.handleSessionSummaries(sessions, {
      viewedSessionId: viewedSessionIdRef.current,
    });
  }, [notifierRef, sessions]);

  useEffect(() => {
    return subscribeConversationNotificationOpened(
      browserDesktopNotificationBridge(),
      (sessionId) => {
        onOpenSessionRef.current(sessionId);
      },
    );
  }, []);
}
