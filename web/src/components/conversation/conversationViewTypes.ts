import type { ReactNode } from "react";

import type {
  ChatNextStateSignalSummary,
  ConversationMessage,
  SessionReferenceAttachment,
  SessionLlmModelOption,
  SessionTurnError,
  SkillLibraryItem,
} from "../../api/types";
import type { TurnAvatarResolution } from "./conversationTurnAvatar";
import type { ConversationStreamingFramePaintMetrics } from "./conversationStreamingMetrics";

export type ConversationProcessDisplayMode = "answer" | "trace";

export type ConversationComposerAttachment = {
  id: string;
  filename: string;
  previewUrl: string;
  sizeBytes: number;
  contentType: string;
};

export type ConversationLlmControl = {
  models: SessionLlmModelOption[];
  currentModelId: string;
  currentReasoningEffort: string;
  disabled: boolean;
  pending: boolean;
  onSelectionChange: (modelId: string, reasoningEffort: string) => void;
};

export type ConversationViewProps = {
  sessionId: string;
  title: string;
  phase: string;
  messages: ConversationMessage[];
  activeTurnMessage?: ConversationMessage;
  className?: string;
  density?: "default" | "compact";
  eyebrowLabel?: string;
  assistantDisplayName?: string;
  assistantAvatarImageUrl?: string;
  assistantAvatarFallback?: string;
  resolveTurnAvatar?: (message: ConversationMessage) => TurnAvatarResolution | undefined;
  userDisplayName?: string;
  userAvatarPreset?: string;
  userAvatarImageUrl?: string;
  taskSummary?: string;
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
  llmControl?: ConversationLlmControl;
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
