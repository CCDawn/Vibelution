import type { ReactNode } from "react";

import type { SessionReferenceAttachment } from "../../api/types";
import { LazyConversationView } from "../../components/conversation/LazyConversationView";
import type {
  ConversationComposerAttachment,
  ConversationViewProps,
} from "../../components/conversation/conversationViewTypes";

export type ChatComposerImageAttachment = {
  id: string;
  filename: string;
  previewUrl: string;
  sizeBytes: number;
  contentType: string;
};

export type ChatConversationComposerBridgeLabels = {
  editMessageModeNotice: string;
  editMessagePlaceholder: string;
  loadingSession: string;
  messageInputPlaceholder: string;
  saveAndRerunMessage: string;
};

export type ChatConversationComposerBridgeInput = {
  editTargetMessageId?: string;
  editTargetPreview?: string;
  error?: string;
  guidance?: string;
  imageAttachments: readonly ChatComposerImageAttachment[];
  imageInputUnsupported: boolean;
  interruptGuidancePending: boolean;
  labels: ChatConversationComposerBridgeLabels;
  references: readonly SessionReferenceAttachment[];
  safeGuidancePending: boolean;
  sessionBusy: boolean;
  sessionId?: string | null;
  sessionStopping: boolean;
  stopPending: boolean;
  submitPending: boolean;
  value: string;
};

export type ChatConversationComposerBridgeState = {
  actionDisabled: boolean;
  actionMode: "send" | "stop";
  attachmentInputDisabled: boolean;
  attachments: ConversationComposerAttachment[];
  disabled: boolean;
  editUserMessageDisabled: boolean;
  editingMessageId?: string;
  error: string;
  guidance: string;
  interruptGuidancePending: boolean;
  modeNotice: string;
  modeTargetPreview: string;
  pending: boolean;
  placeholder: string;
  references: SessionReferenceAttachment[];
  safeGuidancePending: boolean;
  submitLabel: string;
  value: string;
};

type BridgeManagedConversationProps =
  | "composerVariant"
  | "composerActionDisabled"
  | "composerActionMode"
  | "composerAttachmentInputDisabled"
  | "composerAttachments"
  | "composerDisabled"
  | "composerError"
  | "composerGuidance"
  | "composerInterruptGuidancePending"
  | "composerModeNotice"
  | "composerModeTargetPreview"
  | "composerPending"
  | "composerPlaceholder"
  | "composerReferences"
  | "composerSafeGuidancePending"
  | "composerValue"
  | "editingMessageId"
  | "editUserMessageDisabled"
  | "submitLabel";

type ChatConversationComposerBridgeProps = Omit<ConversationViewProps, BridgeManagedConversationProps> & {
  composer: ChatConversationComposerBridgeState;
  fallback: ReactNode;
};

export function mapChatComposerImageAttachments(
  attachments: readonly ChatComposerImageAttachment[],
): ConversationComposerAttachment[] {
  return attachments.map((attachment) => ({
    id: attachment.id,
    filename: attachment.filename,
    previewUrl: attachment.previewUrl,
    sizeBytes: attachment.sizeBytes,
    contentType: attachment.contentType,
  }));
}

export function buildConversationComposerBridgeState(
  input: ChatConversationComposerBridgeInput,
): ChatConversationComposerBridgeState {
  const hasSession = Boolean(input.sessionId);
  const isEditingMessage = Boolean(input.editTargetMessageId);
  const actionMode = input.sessionBusy ? "stop" : "send";
  const pending = actionMode === "stop"
    ? input.stopPending || input.sessionStopping
    : input.submitPending;
  const disabled = !hasSession || input.submitPending;
  const hasDraftContent = Boolean(input.value.trim());
  const hasAttachments = input.imageAttachments.length > 0;
  const hasReferences = input.references.length > 0;
  const actionDisabled = !hasSession || (
    actionMode === "stop"
      ? pending
      : input.submitPending || (!hasDraftContent && !hasAttachments && !hasReferences)
  );
  const placeholder = !hasSession
    ? input.labels.loadingSession
    : input.sessionStopping || input.sessionBusy
      ? ""
      : isEditingMessage
        ? input.labels.editMessagePlaceholder
        : input.labels.messageInputPlaceholder;

  return {
    actionDisabled,
    actionMode,
    attachmentInputDisabled: disabled || Boolean(input.editTargetMessageId) || input.imageInputUnsupported,
    attachments: mapChatComposerImageAttachments(input.imageAttachments),
    disabled,
    editUserMessageDisabled: input.submitPending,
    editingMessageId: input.editTargetMessageId,
    error: input.error ?? "",
    guidance: input.guidance ?? "",
    interruptGuidancePending: input.interruptGuidancePending,
    modeNotice: isEditingMessage ? input.labels.editMessageModeNotice : "",
    modeTargetPreview: isEditingMessage ? input.editTargetPreview?.trim() ?? "" : "",
    pending,
    placeholder,
    references: [...input.references],
    safeGuidancePending: input.safeGuidancePending,
    submitLabel: isEditingMessage ? input.labels.saveAndRerunMessage : "",
    value: input.value,
  };
}

export function ChatConversationComposerBridge({
  composer,
  fallback,
  slashCommandSuggestions,
  ...props
}: ChatConversationComposerBridgeProps) {
  return (
    <LazyConversationView
      {...props}
      composerVariant="codex"
      slashCommandSuggestions={slashCommandSuggestions}
      composerValue={composer.value}
      composerPlaceholder={composer.placeholder}
      composerDisabled={composer.disabled}
      composerActionDisabled={composer.actionDisabled}
      composerActionMode={composer.actionMode}
      composerPending={composer.pending}
      composerSafeGuidancePending={composer.safeGuidancePending}
      composerInterruptGuidancePending={composer.interruptGuidancePending}
      composerError={composer.error}
      composerGuidance={composer.guidance}
      composerAttachments={composer.attachments}
      composerReferences={composer.references}
      composerAttachmentInputDisabled={composer.attachmentInputDisabled}
      composerModeNotice={composer.modeNotice}
      composerModeTargetPreview={composer.modeTargetPreview}
      editingMessageId={composer.editingMessageId}
      editUserMessageDisabled={composer.editUserMessageDisabled}
      submitLabel={composer.submitLabel || undefined}
      fallback={fallback}
    />
  );
}
