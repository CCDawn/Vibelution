import type { ComponentProps } from "react";

import type { FileContent, SessionRuntimeNotice } from "../../api/types";
import { VStateSurface } from "../../components/vui";
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
    <VStateSurface
      className={styles.loadingSurface}
      tone="loading"
      title={loadingSessionLabel}
      skeletonLines={2}
      role="status"
      aria-live="polite"
    />
  );

  if (!activeSessionId && !sessionsPending) {
    return <VStateSurface className={styles.emptyConversationSurface} tone="empty" title={noSessionsLabel} />;
  }

  if (hasBlockingError) {
    return <VStateSurface className={styles.emptySurface} tone="error" title={blockingErrorMessage} />;
  }

  if (invalidChildSessionLinkMessage) {
    return (
      <VStateSurface
        className={styles.emptySurface}
        tone="unavailable"
        title={invalidChildSessionLinkMessage}
      />
    );
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
      <VStateSurface className={styles.emptySurface} tone="empty" title={cliAgentRunEmptyLabel} />
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
