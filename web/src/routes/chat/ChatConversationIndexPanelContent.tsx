/**
 * Index-rail state shell: error / loading / empty + directory children.
 * Keeps ChatCodingRouteWorkbench free of repeated VStateSurface scaffolding.
 */
import type { ReactNode } from "react";

import { VStateSurface } from "../../components/vui";
import { ConversationIndexLoadingShell } from "./ChatLoadingShell";

export type ChatConversationIndexPanelContentProps = {
  styles: {
    panelState: string;
    panelNotice: string;
  };
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
      ) : conversationIndexLoading ? (
        <ConversationIndexLoadingShell label={loadingLabel} />
      ) : isEmpty ? (
        <VStateSurface
          className={styles.panelState}
          tone="empty"
          title={emptyTitle}
        />
      ) : (
        children
      )}
    </>
  );
}
