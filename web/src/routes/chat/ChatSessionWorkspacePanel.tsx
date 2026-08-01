import { lazy, Suspense, type ComponentProps } from "react";

import type {
  FileContent,
  SessionRuntimeNotice,
} from "../../api/types";
import { VStateSurface } from "../../components/vui";
import { ChatConversationComposerBridge } from "./ChatConversationComposerBridge";
import { ConversationWorkspaceLoadingShell } from "./ChatLoadingShell";
import { ChatRuntimeNoticeStack } from "./ChatRuntimeNoticeStack";
import { ChatToolApprovalDialog, type ChatToolApprovalLabel } from "./ChatToolApprovalDialog";
import styles from "./ChatSessionWorkspacePanel.styles";

/** T2: file preview only when that surface is active. Tool approval is eager (blocking path). */
const ChatFilePreviewPanel = lazy(() =>
  import("./ChatFilePreviewPanel").then((module) => ({ default: module.ChatFilePreviewPanel })),
);

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
  onApproveToolForSession?: () => void;
  onRejectToolApproval: () => void;
  sessionsPending: boolean;
  toolApproval: {
    pending: boolean;
    rawTitle: string;
    riskLabel: string;
    scopeLabel: string;
    toolLabels: ChatToolApprovalLabel[];
    actionPreview?: string;
    sessionGrantScope?: Record<string, unknown>;
    toolName?: string;
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
  onApproveToolForSession,
  onRejectToolApproval,
  sessionsPending,
  toolApproval,
  transientErrorMessage,
  workspaceActiveTab,
}: ChatSessionWorkspacePanelProps) {
  const conversationLoadingFallback = (
    <ConversationWorkspaceLoadingShell label={loadingSessionLabel} />
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

    // Sticky host above the transcript (main chat column), not nested under left-aligned
    // tool rows inside process disclosure — that made approvals sit on the left and look broken.
    const approvalDialog = toolApproval ? (
      <ChatToolApprovalDialog
        lang={lang}
        pending={toolApproval.pending}
        rawTitle={toolApproval.rawTitle}
        riskLabel={toolApproval.riskLabel}
        scopeLabel={toolApproval.scopeLabel}
        toolLabels={toolApproval.toolLabels}
        actionPreview={toolApproval.actionPreview}
        sessionGrantScope={toolApproval.sessionGrantScope}
        toolName={toolApproval.toolName}
        variant="banner"
        onApprove={onApproveToolApproval}
        onApproveForSession={onApproveToolForSession}
        onReject={onRejectToolApproval}
      />
    ) : null;

    return (
      <div className={conversationFocused ? `${styles.conversationShell} ${styles.conversationFrameFocus}` : styles.conversationShell}>
        <div className={styles.conversationFrame}>
          {hasTransientError ? (
            <div className={styles.inlineNotice} role="status">
              {transientErrorMessage}
            </div>
          ) : null}
          {approvalDialog ? (
            <div className={styles.toolApprovalHost} data-chat-tool-approval-host="sticky">
              {approvalDialog}
            </div>
          ) : null}
          <ChatRuntimeNoticeStack lang={lang} notices={notices} />
          <div className={styles.conversationBody}>
            <ChatConversationComposerBridge
              {...conversation}
              toolApproval={null}
              composer={conversation.composer}
              fallback={conversationLoadingFallback}
            />
          </div>
        </div>
      </div>
    );
  }

  if (activeCliAgentRunId) {
    return activeCliAgentRunAvailable ? null : (
      <VStateSurface className={styles.emptySurface} tone="empty" title={cliAgentRunEmptyLabel} />
    );
  }

  return (
    <Suspense fallback={<ConversationWorkspaceLoadingShell label={filePreview.loadingLabel} />}>
      <ChatFilePreviewPanel
        changed={filePreview.changed}
        errorMessage={filePreview.errorMessage}
        file={filePreview.file}
        loadingLabel={filePreview.loadingLabel}
        sourceLabel={filePreview.sourceLabel}
      />
    </Suspense>
  );
}
