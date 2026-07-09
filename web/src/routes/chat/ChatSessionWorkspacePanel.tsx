import type { ComponentProps } from "react";

import type { FileContent, SessionRuntimeNotice } from "../../api/types";
import { ChatConversationComposerBridge } from "./ChatConversationComposerBridge";
import { ChatFilePreviewPanel } from "./ChatFilePreviewPanel";
import { ChatRuntimeNoticeStack } from "./ChatRuntimeNoticeStack";
import { ChatToolApprovalDialog, type ChatToolApprovalLabel } from "./ChatToolApprovalDialog";
import styles from "./ChatSessionWorkspacePanel.styles";

type ConversationBridgeProps = Omit<ComponentProps<typeof ChatConversationComposerBridge>, "fallback">;

type ChatSessionWorkspacePanelProps = {
  activeCliAgentRunAvailable: boolean;
  activeCliAgentRunId: string;
  activeSessionId: string | null | undefined;
  blockingErrorMessage: string;
  cliAgentRunEmptyLabel: string;
  conversation: ConversationBridgeProps | null;
  conversationFocused: boolean;
  filePreview: {
    changed: boolean;
    errorMessage: string;
    file: FileContent | null | undefined;
    loadingLabel: string;
    sourceLabel: string;
  };
  hasBlockingError: boolean;
  hasTransientError: boolean;
  invalidChildSessionLinkMessage: string;
  lang: "zh" | "en";
  loadingSessionLabel: string;
  noSessionsLabel: string;
  notices: SessionRuntimeNotice[];
  onApproveToolApproval: () => void;
  onRejectToolApproval: () => void;
  sessionsPending: boolean;
  toolApproval: {
    pending: boolean;
    rawTitle: string;
    riskLabel: string;
    scopeLabel: string;
    toolLabels: ChatToolApprovalLabel[];
  } | null;
  transientErrorMessage: string;
  workspaceActiveTab: string;
};

export function ChatSessionWorkspacePanel({
  activeCliAgentRunAvailable,
  activeCliAgentRunId,
  activeSessionId,
  blockingErrorMessage,
  cliAgentRunEmptyLabel,
  conversation,
  conversationFocused,
  filePreview,
  hasBlockingError,
  hasTransientError,
  invalidChildSessionLinkMessage,
  lang,
  loadingSessionLabel,
  noSessionsLabel,
  notices,
  onApproveToolApproval,
  onRejectToolApproval,
  sessionsPending,
  toolApproval,
  transientErrorMessage,
  workspaceActiveTab,
}: ChatSessionWorkspacePanelProps) {
  const conversationLoadingFallback = (
    <div className={styles.loadingSurface} role="status" aria-live="polite">
      <div className={styles.loadingSurfaceBody}>
        <strong>{loadingSessionLabel}</strong>
        <span className={styles.loadingSkeletonLine} />
        <span className={styles.loadingSkeletonLineShort} />
      </div>
    </div>
  );

  if (!activeSessionId && !sessionsPending) {
    return <div className={styles.emptyConversationSurface}>{noSessionsLabel}</div>;
  }

  if (hasBlockingError) {
    return <div className={styles.emptySurface}>{blockingErrorMessage}</div>;
  }

  if (invalidChildSessionLinkMessage) {
    return <div className={styles.emptySurface}>{invalidChildSessionLinkMessage}</div>;
  }

  if (workspaceActiveTab === "agent") {
    if (!conversation) {
      return conversationLoadingFallback;
    }

    return (
      <div className={conversationFocused ? `${styles.conversationFrame} ${styles.conversationFrameFocus}` : styles.conversationFrame}>
        {hasTransientError ? (
          <div className={styles.inlineNotice} role="status">
            {transientErrorMessage}
          </div>
        ) : null}
        <ChatRuntimeNoticeStack lang={lang} notices={notices} />
        {toolApproval ? (
          <ChatToolApprovalDialog
            lang={lang}
            pending={toolApproval.pending}
            rawTitle={toolApproval.rawTitle}
            riskLabel={toolApproval.riskLabel}
            scopeLabel={toolApproval.scopeLabel}
            toolLabels={toolApproval.toolLabels}
            onApprove={onApproveToolApproval}
            onReject={onRejectToolApproval}
          />
        ) : null}
        <ChatConversationComposerBridge
          {...conversation}
          composer={conversation.composer}
          fallback={conversationLoadingFallback}
        />
      </div>
    );
  }

  if (activeCliAgentRunId) {
    return activeCliAgentRunAvailable ? null : (
      <div className={styles.emptySurface}>
        {cliAgentRunEmptyLabel}
      </div>
    );
  }

  return (
    <ChatFilePreviewPanel
      changed={filePreview.changed}
      errorMessage={filePreview.errorMessage}
      file={filePreview.file}
      loadingLabel={filePreview.loadingLabel}
      sourceLabel={filePreview.sourceLabel}
    />
  );
}
