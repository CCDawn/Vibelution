import type { SessionDetail } from "../../api/types";
import { ChatSessionWorkspacePanel } from "./ChatSessionWorkspacePanel";

export type ChatReadOnlySessionIdentity = {
  displayName: string;
  avatarImageUrl?: string;
  avatarFallback?: string;
  avatarPreset?: string;
};

export type ChatReadOnlySessionWorkspaceProps = {
  assistant: ChatReadOnlySessionIdentity;
  defaultFileContext: string;
  detail?: SessionDetail;
  emptyLabel: string;
  errorMessage?: string;
  lang: "zh" | "en";
  live: boolean;
  loading: boolean;
  loadingLabel: string;
  sessionId?: string | null;
  taskSummary?: string;
  user: ChatReadOnlySessionIdentity;
};

const ignoreReadOnlyAction = () => undefined;

export function ChatReadOnlySessionWorkspace({
  assistant,
  defaultFileContext,
  detail,
  emptyLabel,
  errorMessage = "",
  lang,
  live,
  loading,
  loadingLabel,
  sessionId,
  taskSummary = "",
  user,
}: ChatReadOnlySessionWorkspaceProps) {
  const normalizedSessionId = String(sessionId || "").trim();
  const sessionDetail = detail?.id === normalizedSessionId ? detail : undefined;
  const hasSessionError = Boolean(errorMessage);

  return (
    <ChatSessionWorkspacePanel
      activeCliAgentRunAvailable={false}
      activeCliAgentRunId=""
      activeSessionId={normalizedSessionId || null}
      blockingErrorMessage={errorMessage}
      cliAgentRunEmptyLabel={emptyLabel}
      conversation={sessionDetail ? {
        sessionId: sessionDetail.id,
        title: sessionDetail.title || assistant.displayName,
        phase: sessionDetail.currentPhase || sessionDetail.status || "idle",
        messages: sessionDetail.messages,
        assistantDisplayName: assistant.displayName,
        assistantAvatarImageUrl: assistant.avatarImageUrl,
        assistantAvatarFallback: assistant.avatarFallback,
        userDisplayName: user.displayName,
        userAvatarPreset: user.avatarPreset,
        userAvatarImageUrl: user.avatarImageUrl,
        taskSummary: sessionDetail.taskSummary || taskSummary,
        defaultFileContext: sessionDetail.defaultFileContext || defaultFileContext,
        showHeader: false,
        showSessionOverview: false,
        showComposer: false,
        autoScrollToLatest: live,
        composer: {
          actionDisabled: true,
          actionMode: "send",
          attachmentInputDisabled: true,
          attachments: [],
          disabled: true,
          editUserMessageDisabled: true,
          error: "",
          guidance: "",
          interruptGuidancePending: false,
          modeNotice: "",
          modeTargetPreview: "",
          pending: false,
          placeholder: lang === "zh" ? "会话只读" : "Session is read-only",
          references: [],
          safeGuidancePending: false,
          submitLabel: "",
          value: "",
        },
        onComposerChange: ignoreReadOnlyAction,
        onSubmit: ignoreReadOnlyAction,
      } : null}
      conversationFocused={true}
      filePreview={{
        changed: false,
        errorMessage: "",
        file: null,
        loadingLabel,
        sourceLabel: "",
      }}
      hasBlockingError={hasSessionError && !sessionDetail}
      hasTransientError={hasSessionError && Boolean(sessionDetail)}
      invalidChildSessionLinkMessage=""
      lang={lang}
      loadingSessionLabel={loadingLabel}
      noSessionsLabel={emptyLabel}
      notices={sessionDetail?.runtimeNotices ?? []}
      onApproveToolApproval={ignoreReadOnlyAction}
      onRejectToolApproval={ignoreReadOnlyAction}
      sessionsPending={loading || (live && !normalizedSessionId)}
      toolApproval={null}
      transientErrorMessage={errorMessage}
      workspaceActiveTab="agent"
    />
  );
}
