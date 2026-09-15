import type { ReactNode } from "react";

import type { SessionReferenceAttachment } from "../../api/types";
import { LazyConversationView } from "../../components/conversation/LazyConversationView";
import type { ComposerQueueItem } from "../../components/conversation/composerFollowupQueueModel";
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
  followupQueue?: ComposerQueueItem[];
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
  followupQueue: ComposerQueueItem[];
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
  | "followupQueue"
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

export function buildComposerImageInputGuidance(input: {
  attachmentCount: number;
  queuedUntilTurnEnds: boolean;
  imageInputSupport: boolean | null;
  modelLabel: string;
  lang: "zh" | "en";
}): string {
  if (input.attachmentCount <= 0) {
    return "";
  }
  const modelLabel = input.modelLabel || (input.lang === "zh" ? "当前模型" : "the current model");
  if (input.queuedUntilTurnEnds) {
    return input.lang === "zh"
      ? "当前轮运行中：图片会随这条消息一起排队，本轮结束后自动发送。"
      : "This turn is still running: the image queues with this message and sends automatically when the turn ends.";
  }
  if (input.imageInputSupport === true) {
    return input.lang === "zh"
      ? `图片将发送给已验证支持图像输入的 ${modelLabel}。`
      : `The image will be sent to ${modelLabel}, which has verified image-input support.`;
  }
  if (input.imageInputSupport === false) {
    return input.lang === "zh"
      ? `${modelLabel} 明确不支持图像输入，无法发送图片。`
      : `${modelLabel} explicitly does not support image input, so the image cannot be sent.`;
  }
  return input.lang === "zh"
    ? `${modelLabel} 的图像输入能力尚未验证；将尝试发送，失败时会保留诊断。`
    : `${modelLabel}'s image-input capability is not verified yet. Vibelution will try the request and retain diagnostics if it fails.`;
}

export function buildConversationComposerBridgeState(
  input: ChatConversationComposerBridgeInput,
): ChatConversationComposerBridgeState {
  const hasSession = Boolean(input.sessionId);
  const isEditingMessage = Boolean(input.editTargetMessageId);
  // A requested stop ends the turn for the composer immediately: the user can
  // queue the next message while the worker is still confirming the stop.
  const actionMode = input.sessionStopping
    ? "send"
    : input.sessionBusy || input.submitPending
      ? "stop"
      : "send";
  const pending = actionMode === "stop"
    ? input.stopPending || input.sessionStopping
    : input.submitPending;
  const disabled = !hasSession
    || (input.submitPending && (input.sessionBusy || input.sessionStopping));
  const hasDraftContent = Boolean(input.value.trim());
  const hasAttachments = input.imageAttachments.length > 0;
  const hasReferences = input.references.length > 0;
  const actionDisabled = !hasSession || (
    actionMode === "stop"
      ? input.sessionStopping
      : input.submitPending || (!hasDraftContent && !hasAttachments && !hasReferences)
  );
  const placeholder = !hasSession
    ? input.labels.loadingSession
    : input.sessionBusy && !input.sessionStopping
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
    followupQueue: [...(input.followupQueue ?? [])],
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
      followupQueue={composer.followupQueue}
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
