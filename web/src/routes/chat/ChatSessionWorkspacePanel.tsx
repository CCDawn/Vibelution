import { lazy, Suspense, useMemo, type ComponentProps, type ReactNode } from "react";

import type {
  FileContent,
  SessionRuntimeNotice,
} from "../../api/types";
import { VStateSurface } from "../../components/vui";
import {
  ActiveTurnStreamStateContext,
  type ActiveTurnStreamState,
} from "../../components/conversation/activeTurnStreamState";
import { ConversationShareExportButton } from "../../components/conversation/ConversationShareExportButton";
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

/**
 * Stable empty context value: an inline `{}` default would re-create the
 * provider value on every panel render and re-render every context consumer.
 */
const EMPTY_ACTIVE_TURN_STREAM_STATE: ActiveTurnStreamState = {};

export type ChatSessionWorkspaceFilePreview = {
  changed: boolean;
  errorMessage: string;
  file: FileContent | null | undefined;
  loadingLabel: string;
  sourceLabel: string;
};

/** Empty-session and hydration gate. Checked before any workspace surface. */
export type ChatSessionWorkspaceSessionGate = {
  activeSessionId: string | null | undefined;
  sessionsPending: boolean;
  noSessionsLabel: string;
  loadingSessionLabel: string;
};

/** Blocking, link, and transient session errors. Transient copy stays on the agent frame. */
export type ChatSessionWorkspaceErrorGate = {
  hasBlockingError: boolean;
  blockingErrorMessage: string;
  hasTransientError: boolean;
  invalidChildSessionLinkMessage: string;
  transientErrorMessage: string;
};

/** Non-agent center surfaces: CLI run placeholder, otherwise the file preview. */
export type ChatSessionWorkspaceAlternateSurface = {
  workspaceActiveTab: string;
  activeCliAgentRunId: string;
  activeCliAgentRunAvailable: boolean;
  cliAgentRunEmptyLabel: string;
  filePreview: ChatSessionWorkspaceFilePreview;
};

/** Agent-tab transcript frame. `conversation` null keeps the loading shell. */
export type ChatSessionWorkspaceConversationFrame = {
  conversation: ConversationBridgeProps | null;
  conversationFocused: boolean;
  /** Fixed note at the start of one specialist chat. Ordinary sessions pass nothing. */
  preface?: ReactNode;
  hideExportControl?: boolean;
  notices: SessionRuntimeNotice[];
  /** Guarded-stream transport state projected into the active-turn status note. */
  activeTurnStreamState?: ActiveTurnStreamState;
};

export type ChatSessionWorkspaceToolApproval = {
  /** Stable identity for the pending request — keeps the dialog from remount-flashing. */
  requestId?: string;
  pending: boolean;
  rawTitle: string;
  riskLabel: string;
  scopeLabel: string;
  toolLabels: ChatToolApprovalLabel[];
  actionPreview?: string;
  sessionGrantScope?: Record<string, unknown>;
  toolName?: string;
  onApprove: () => void;
  onApproveForSession?: () => void;
  onReject: () => void;
};

type ChatSessionWorkspacePanelProps = {
  lang: "zh" | "en";
  sessionGate: ChatSessionWorkspaceSessionGate;
  errorGate: ChatSessionWorkspaceErrorGate;
  alternateSurface: ChatSessionWorkspaceAlternateSurface;
  conversationFrame: ChatSessionWorkspaceConversationFrame;
  toolApproval: ChatSessionWorkspaceToolApproval | null;
};

export function ChatSessionWorkspacePanel({
  lang,
  sessionGate,
  errorGate,
  alternateSurface,
  conversationFrame,
  toolApproval,
}: ChatSessionWorkspacePanelProps) {
  const {
    activeSessionId,
    sessionsPending,
    noSessionsLabel,
    loadingSessionLabel,
  } = sessionGate;
  const {
    hasBlockingError,
    blockingErrorMessage,
    hasTransientError,
    invalidChildSessionLinkMessage,
    transientErrorMessage,
  } = errorGate;
  const {
    workspaceActiveTab,
    activeCliAgentRunId,
    activeCliAgentRunAvailable,
    cliAgentRunEmptyLabel,
    filePreview,
  } = alternateSurface;
  const {
    conversation,
    conversationFocused,
    preface = null,
    hideExportControl = false,
    notices,
    activeTurnStreamState,
  } = conversationFrame;
  // Stable ReactNode/object identities so the memoized
  // ChatConversationComposerBridge below only re-renders when content changes.
  const conversationLoadingFallback = useMemo(
    () => (<ConversationWorkspaceLoadingShell label={loadingSessionLabel} />),
    [loadingSessionLabel],
  );
  const approvalSurface = useMemo(() => (toolApproval
    ? {
      toolName: toolApproval.toolName,
      content: (
        <div
          key={toolApproval.requestId || toolApproval.toolName || "tool-approval"}
          data-chat-tool-approval-host="composer"
          data-chat-tool-approval-request={toolApproval.requestId || undefined}
        >
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
            onApprove={toolApproval.onApprove}
            onApproveForSession={toolApproval.onApproveForSession}
            onReject={toolApproval.onReject}
          />
        </div>
      ),
    }
    : null), [
    lang,
    toolApproval,
  ]);

  if (!activeSessionId && !sessionsPending) {
    return <VStateSurface className={styles.emptyConversationSurface} tone="empty" title={noSessionsLabel} />;
  }

  if (hasBlockingError) {
    return <VStateSurface className={styles.emptySurface} tone="error" title={blockingErrorMessage || (lang === "zh" ? "此会话已不可用" : "This session is unavailable")} />;
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

    // Composer-adjacent only: ConversationView mounts the card just above the input
    // (toolApprovalFallback). Do not stick to the column top or re-attach into process rows.
    // Key by requestId so SSE/poll re-renders update props instead of remounting the dialog.
    return (
      <div className={conversationFocused ? `${styles.conversationShell} ${styles.conversationFrameFocus}` : styles.conversationShell}>
        <div className={styles.conversationFrame}>
          {preface}
          {hasTransientError ? (
            <div className={styles.inlineNotice} role="status">
              {transientErrorMessage}
            </div>
          ) : null}
          <ChatRuntimeNoticeStack lang={lang} notices={notices} />
          {conversation && !hideExportControl ? (
            <div className={styles.conversationToolbar}>
              {/* Session-level local HTML export; direct sessions only — group
                  rooms render through their own transcript component above. */}
              <ConversationShareExportButton
                sessionId={conversation.sessionId}
                messages={conversation.messages}
                language={lang}
                isDisabled={conversation.messages.length === 0}
              />
            </div>
          ) : null}
          <div className={styles.conversationBody}>
            {/*
              key=sessionId remounts clean per thread (no cross-session scroll/expansion bleed).
              Sticky last-good paint ensures the first frame already has messages (Codex resume feel).
            */}
            <div
              key={conversation.sessionId}
              className={styles.conversationKeepAlivePane}
              data-session-conversation={conversation.sessionId}
            >
              <ActiveTurnStreamStateContext.Provider value={activeTurnStreamState ?? EMPTY_ACTIVE_TURN_STREAM_STATE}>
                <ChatConversationComposerBridge
                  {...conversation}
                  toolApproval={approvalSurface}
                  composer={conversation.composer}
                  fallback={conversationLoadingFallback}
                />
              </ActiveTurnStreamStateContext.Provider>
            </div>
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
