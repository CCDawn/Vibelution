/**
 * Index-rail state shell: error / loading / empty + directory children.
 * Keeps ChatCodingRouteWorkbench free of repeated VStateSurface scaffolding.
 *
 * Loading jitter latch: once the real list has rendered, brief loading pulses
 * (bootstrap ready-bit flips, 3s polls, SSE invalidates) no longer swap the
 * mounted list back to the skeleton — unmounting would reset scroll and flash
 * the rows. First render without any list data still shows the skeleton, and
 * a genuine blocking error still replaces the list.
 */
import { useEffect, useState, type ReactNode } from "react";

import { VStateSurface } from "../../components/vui";
import { ConversationIndexLoadingShell } from "./ChatLoadingShell";

export type ChatConversationIndexPanelContentProps = {
  /** Route style map (ChatCodingRoute.styles is Record<string, string>). */
  styles: Record<string, string>;
  loadingLabel: string;
  emptyTitle: string;
  sessionsErrorMessage: string;
  sessionComposerSessionsError?: string;
  sessionsTransientError: boolean;
  sessionsBlockingError: boolean;
  conversationIndexLoading: boolean;
  isEmpty: boolean;
  children: ReactNode;
};

export function ChatConversationIndexPanelContent({
  styles,
  loadingLabel,
  emptyTitle,
  sessionsErrorMessage,
  sessionComposerSessionsError,
  sessionsTransientError,
  sessionsBlockingError,
  conversationIndexLoading,
  isEmpty,
  children,
}: ChatConversationIndexPanelContentProps) {
  const [hasRenderedList, setHasRenderedList] = useState(false);
  const listReady = !conversationIndexLoading && !sessionsBlockingError && !isEmpty;
  useEffect(() => {
    if (listReady) {
      setHasRenderedList(true);
    }
  }, [listReady]);
  // Hold the mounted list through loading pulses once it has rendered; the
  // hold never overrides a blocking error, which is a real state change.
  const holdListDuringLoading = hasRenderedList && conversationIndexLoading && !sessionsBlockingError;

  return (
    <>
      {sessionComposerSessionsError ? (
        <VStateSurface
          className={styles.panelState}
          tone="error"
          title={sessionComposerSessionsError}
        />
      ) : null}
      {sessionsTransientError ? (
        <div className={styles.panelNotice} role="status">{sessionsErrorMessage}</div>
      ) : null}
      {sessionsBlockingError ? (
        <VStateSurface className={styles.panelState} tone="error" title={sessionsErrorMessage} />
      ) : conversationIndexLoading && !holdListDuringLoading ? (
        <ConversationIndexLoadingShell label={loadingLabel} />
      ) : isEmpty && !holdListDuringLoading ? (
        <VStateSurface
          className={styles.panelState}
          tone="empty"
          title={emptyTitle}
        />
      ) : (
        <>
          {holdListDuringLoading ? (
            <div className={styles.panelNotice} role="status">{loadingLabel}</div>
          ) : null}
          {children}
        </>
      )}
    </>
  );
}
