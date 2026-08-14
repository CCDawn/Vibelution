import type { ReactNode } from "react";

import type {
  ChatNextStateSignalSummary,
  ConversationMessage,
  SessionReferenceAttachment,
  SessionLlmModelOption,
  SessionTurnError,
  SkillLibraryItem,
  AgentPermissionPreset,
} from "../../api/types";
import type { TurnAvatarResolution } from "./conversationTurnAvatar";
import type { ConversationStreamingFramePaintMetrics } from "./conversationStreamingMetrics";
import type { ComposerContextRingModel } from "../../routes/chat/composerContextModel";

export type ConversationProcessDisplayMode = "answer" | "trace";

export type ConversationComposerAttachment = {
  id: string;
  filename: string;
  previewUrl: string;
  sizeBytes: number;
  contentType: string;
};

export type ConversationLlmControl = {
  model: SessionLlmModelOption | null;
  currentReasoningEffort: string;
  disabled: boolean;
  pending: boolean;
  onReasoningEffortChange: (reasoningEffort: string) => void;
};

export type ConversationComposerVariant = "compact" | "codex";

export type ConversationPermissionControl = {
  value: AgentPermissionPreset;
  disabled: boolean;
  pending: boolean;
  agentName?: string;
  onChange: (permissionPreset: AgentPermissionPreset) => void;
};

/** Codex-style per-call tool approval bound into the transcript tool activity. */
export type ConversationToolApprovalSurface = {
  /** Match against the open tool cell name (e.g. web_fetch_tool). */
  toolName?: string;
  /** Pre-built approval card (owned by the chat route). */
  content: ReactNode;
};

export type ConversationViewProps = {
  sessionId: string;
  title: string;
  phase: string;
  messages: ConversationMessage[];
  activeTurnMessage?: ConversationMessage;
  /**
   * True while the session message window is still hydrating after a switch.
   * Empty timeline then shows a loading surface instead of the empty-session copy.
   */
  transcriptPending?: boolean;
  className?: string;
  density?: "default" | "compact";
  composerVariant?: ConversationComposerVariant;
  eyebrowLabel?: string;
  assistantDisplayName?: string;
  assistantAvatarImageUrl?: string;
  assistantAvatarFallback?: string;
  resolveTurnAvatar?: (message: ConversationMessage) => TurnAvatarResolution | undefined;
  userDisplayName?: string;
  userAvatarPreset?: string;
  userAvatarImageUrl?: string;
  taskSummary?: string;
  /** Session-level changed files for Codex-style turn footer badge. */
  changedFiles?: string[];
  defaultFileContext: string;
  summaryItems?: Array<{
    label: string;
    value: string;
  }>;
  stats?: Array<{
    label: string;
    value: string | number;
  }>;
  headerActions?: ReactNode;
  supplementalContent?: ReactNode;
  showHeader?: boolean;
  showSessionOverview?: boolean;
  showMentalSnapshots?: boolean;
  showComposer?: boolean;
  processDisplayMode?: ConversationProcessDisplayMode;
  autoScrollToLatest?: boolean;
  hasEarlierMessages?: boolean;
  earlierMessagesLoading?: boolean;
  onStreamingFramePaint?: (metrics: ConversationStreamingFramePaintMetrics) => void;
  composerValue: string;
  composerPlaceholder: string;
  composerDisabled: boolean;
  /** Explicit one-shot request used by destructive route handoffs. */
  composerFocusSignal?: string;
  onComposerFocusRequestSettled?: (focusSignal: string) => void;
  composerActionDisabled?: boolean;
  composerActionMode?: "send" | "stop";
  composerPending: boolean;
  composerSafeGuidancePending?: boolean;
  composerInterruptGuidancePending?: boolean;
  composerError?: string;
  composerGuidance?: string;
  composerAttachments?: ConversationComposerAttachment[];
  composerReferences?: SessionReferenceAttachment[];
  slashCommandSuggestions?: SkillLibraryItem[];
  composerAttachmentInputDisabled?: boolean;
  permissionControl?: ConversationPermissionControl;
  /** Pending tool approval shown under the matching running tool (Codex-style). */
  toolApproval?: ConversationToolApprovalSurface | null;
  llmControl?: ConversationLlmControl;
  /** Compact context composition ring (left of send). */
  composerContextRing?: ComposerContextRingModel | null;
  onOpenComposerContextDetail?: () => void;
  turnError?: SessionTurnError | null;
  nextStateSignals?: ChatNextStateSignalSummary[];
  submitLabel?: string;
  submitPendingLabel?: string;
  stopLabel?: string;
  stopPendingLabel?: string;
  safeGuidanceLabel?: string;
  safeGuidancePendingLabel?: string;
  interruptGuidanceLabel?: string;
  interruptGuidancePendingLabel?: string;
  editingMessageId?: string;
  editUserMessageLabel?: string;
  editUserMessageDisabled?: boolean;
  composerModeNotice?: string;
  composerModeTargetPreview?: string;
  cancelComposerModeLabel?: string;
  onComposerChange: (value: string) => void;
  onAddComposerAttachments?: (files: FileList | File[]) => void;
  onRemoveComposerAttachment?: (attachmentId: string) => void;
  onAddComposerReference?: (reference: SessionReferenceAttachment) => void;
  onRemoveComposerReference?: (referenceId: string) => void;
  onEditUserMessage?: (message: ConversationMessage) => void;
  onCancelComposerMode?: () => void;
  onLoadEarlierMessages?: () => void;
  onSubmit: () => void;
  onStop?: () => void;
  onSafeGuidance?: () => void;
  onInterruptGuidance?: () => void;
};
