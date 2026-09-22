import { memo, useMemo, type ReactNode } from "react";

import type { SessionReferenceAttachment } from "../../api/types";
import { LazyConversationView } from "../../components/conversation/LazyConversationView";
import type { ComposerQueueItem } from "../../components/conversation/composerFollowupQueueModel";
import type {
  ConversationComposerAttachment,
  ConversationViewProps,
} from "../../components/conversation/conversationViewTypes";
import { projectActiveTurnLayerMessage } from "../chatActiveTurnLayer";
import {
  useActiveTurnLayerForSession,
  useActiveTurnLayersStore,
} from "./activeTurnLayersStore";

export type ChatComposerImageAttachment = {
  id: string;
  filename: string;
  previewUrl: string;
  sizeBytes: number;
  contentType: string;
  kind?: "image" | "document";
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
    kind: attachment.kind,
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
  if (input.imageInputSupport === false) {
    return input.lang === "zh"
      ? `${modelLabel} 明确不支持图像输入，无法发送图片。`
      : `${modelLabel} explicitly does not support image input, so the image cannot be sent.`;
  }
  // Verified support and unverified capability stay quiet: the attachment sends
  // either way and a failed request already surfaces its own diagnostic. Only a
  // blocked case (explicitly unsupported) still needs a visible reason here.
  return "";
}

export function buildConversationComposerBridgeState(
  input: ChatConversationComposerBridgeInput,
): ChatConversationComposerBridgeState {
  const hasSession = Boolean(input.sessionId);
  const isEditingMessage = Boolean(input.editTargetMessageId);
  // Keep the stop affordance visible until the server confirms a terminal
  // snapshot. This makes the click feedback explicit and prevents a pending
  // submit from looking like a new-message spinner.
  const actionMode = input.sessionBusy || input.submitPending || input.sessionStopping ? "stop" : "send";
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
      ? input.sessionStopping || input.stopPending
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

/**
 * Memo gate between the workbench and ConversationView: with stable props the
 * bridge never re-renders on unrelated workbench state changes. The
 * active-turn layer store subscription below still fires through the memo —
 * streaming frames re-render exactly this component and ConversationView.
 */
export const ChatConversationComposerBridge = memo(function ChatConversationComposerBridge({
  composer,
  fallback,
  activeTurnMessage,
  messages,
  sessionId,
  slashCommandSuggestions,
  ...props
}: ChatConversationComposerBridgeProps) {
  // Outside the workbench provider (no active-turn store) the prop passes
  // through unchanged; inside it, the streaming layer is projected from the
  // store for this session with the same settle rule the route used.
  const activeTurnLayersStore = useActiveTurnLayersStore();
  const streamedActiveTurnLayer = useActiveTurnLayerForSession(
    activeTurnLayersStore ? sessionId : null,
  );
  const streamedActiveTurnMessage = useMemo(
    () => (
      activeTurnLayersStore
        ? projectActiveTurnLayerMessage(streamedActiveTurnLayer, messages)
        : activeTurnMessage
    ),
    [activeTurnLayersStore, streamedActiveTurnLayer, messages, activeTurnMessage],
  );
  return (
    <LazyConversationView
      {...props}
      activeTurnMessage={streamedActiveTurnMessage}
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
});
