import { lazy, Suspense, type ComponentProps } from "react";

import type {
  FileContent,
  SessionAgentPromptSnapshot,
  SessionPromptAssemblyManifest,
  SessionRuntimeNotice,
} from "../../api/types";
import { VStateSurface } from "../../components/vui";
import { ChatConversationComposerBridge } from "./ChatConversationComposerBridge";
import { ConversationWorkspaceLoadingShell } from "./ChatLoadingShell";
import { ChatRuntimeNoticeStack } from "./ChatRuntimeNoticeStack";
import { ChatPromptAssemblyInspector } from "./ChatPromptAssemblyInspector";
import type { ChatToolApprovalLabel } from "./ChatToolApprovalDialog";
import styles from "./ChatSessionWorkspacePanel.styles";

/** T2: file preview / tool approval only when those surfaces are active. */
const ChatFilePreviewPanel = lazy(() =>
  import("./ChatFilePreviewPanel").then((module) => ({ default: module.ChatFilePreviewPanel })),
);
const ChatToolApprovalDialog = lazy(() =>
  import("./ChatToolApprovalDialog").then((module) => ({ default: module.ChatToolApprovalDialog })),
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
  onRejectToolApproval: () => void;
  sessionsPending: boolean;
  promptSnapshot?: SessionAgentPromptSnapshot;
  promptAssembly?: SessionPromptAssemblyManifest;
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
  promptSnapshot,
  promptAssembly,
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

    return (
      <div className={conversationFocused ? `${styles.conversationFrame} ${styles.conversationFrameFocus}` : styles.conversationFrame}>
        {hasTransientError ? (
          <div className={styles.inlineNotice} role="status">
            {transientErrorMessage}
          </div>
        ) : null}
        <ChatRuntimeNoticeStack lang={lang} notices={notices} />
        {promptSnapshot ? (
          <ChatPromptAssemblyInspector lang={lang} snapshot={promptSnapshot} manifest={promptAssembly} />
        ) : null}
        {toolApproval ? (
          <Suspense fallback={null}>
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
          </Suspense>
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
