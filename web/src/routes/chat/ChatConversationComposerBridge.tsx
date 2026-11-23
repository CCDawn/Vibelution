import { memo, useEffect, useMemo, useRef, type ReactNode } from "react";
import {
  liveComposerDraftOr,
} from "./composerLiveDraft";

import type { SessionReferenceAttachment } from "../../api/types";
import { postBrowserTelemetry } from "../../app/browserTelemetry";
import { useChatStartupPresentation } from "./useChatStartupPresentation";
import { LazyConversationView } from "../../components/conversation/LazyConversationView";
import { resolveComposerViewKey } from "./composerViewIdentity";
import {
  createComposerDraftStore,
  registerComposerDraftStore,
  syncComposerDraftStoreFromUpstream,
} from "../../components/conversation/composerDraftStore";
import type { ComposerQueueItem } from "../../components/conversation/composerFollowupQueueModel";
import type {
  ConversationComposerAttachment,
  ConversationViewProps,
} from "../../components/conversation/conversationViewTypes";
import { projectActiveTurnLayerMessage, type ActiveTurnAuthority } from "../chatActiveTurnLayer";
import type { ComposerImageAttachment } from "./chatComposerSubmitModel";
import {
  useActiveTurnLayerForSession,
  useActiveTurnLayersStore,
} from "./activeTurnLayersStore";

/** Wire-safe projection of a composer attachment (no File/localPath across the bridge). */
export type ChatComposerImageAttachment = Omit<ComposerImageAttachment, "file" | "localPath">;

export type ChatConversationComposerBridgeLabels = {
  editMessageModeNotice: string;
  editMessagePlaceholder: string;
  loadingSession: string;
  messageInputPlaceholder: string;
  readOnlySession?: string;
  saveAndRerunMessage: string;
  /** ZCode followUpQueue state: empty queue, the draft will queue behind the running turn. */
  sessionBusyQueuePlaceholder: string;
  /** ZCode followUpQueue state: items already queued, further input appends. */
  sessionBusyQueuedPlaceholder: string;
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
  readOnly?: boolean;
  followupQueue?: ComposerQueueItem[];
  safeGuidancePending: boolean;
  sessionBusy: boolean;
  sessionId?: string | null;
  sessionStopping: boolean;
  stopPending: boolean;
  submitPending: boolean;
  continueAvailable?: boolean;
  value: string;
};

export type ChatConversationComposerBridgeState = {
  readOnly?: boolean;
  actionDisabled: boolean;
  /** Structural lock only; empty drafts come from the island live text. */
  actionDisabledByState: boolean;
  actionMode: "send" | "stop" | "continue";
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
  submitPending: boolean;
  stopPending: boolean;
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
  | "composerSubmitPending"
  | "composerStopPending"
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
  activeTurnAuthority?: ActiveTurnAuthority;
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
    uploadStatus: attachment.uploadStatus,
    artifactId: attachment.artifactId,
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
      ? "本轮运行中：图片会随发送一起排队，点发送后本轮结束即自动发出。"
      : "This turn is still running: the image queues when you send; it goes out as soon as the turn ends.";
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
  // Submission acknowledgement and native execution are separate sources.
  const hasDraftContent = Boolean(input.value.trim());
  const hasAttachments = input.imageAttachments.length > 0;
  const hasReferences = input.references.length > 0;
  const canContinue = input.continueAvailable && !isEditingMessage && !hasDraftContent && !hasAttachments && !hasReferences
    && !input.followupQueue?.length;
  const actionMode = input.sessionBusy || input.submitPending || input.sessionStopping ? "stop" : canContinue ? "continue" : "send";
  const pending = input.submitPending || input.stopPending || input.sessionStopping;
  const disabled = Boolean(input.readOnly) || !hasSession
    || input.submitPending;
  const actionDisabled = Boolean(input.readOnly) || !hasSession || (
    actionMode === "stop"
      ? input.submitPending || input.sessionStopping || input.stopPending
      : input.submitPending || (actionMode !== "continue" && !hasDraftContent && !hasAttachments && !hasReferences)
  );
  // Structural lock only: an empty draft is never decided here. The island
  // reads the live draft, so a keystroke followed by Enter must not wait for
  // the debounced mirror that produces input.value.
  const actionDisabledByState = Boolean(input.readOnly) || !hasSession || (
    actionMode === "stop"
      ? input.submitPending || input.sessionStopping || input.stopPending
      : input.submitPending
  );
  // ZCode chatPlaceholder tri-state parity: while a turn runs the composer
  // always names the queueing semantics instead of going blank — the empty
  // queue shows the plain "queues and sends after this turn" hint, and once
  // items are queued the placeholder flips to the append hint. An active
  // guidance notice already owns that line, so the placeholder must not
  // restate the queueing rule beside it: two stacked hints that contradict
  // each other above one input read as one broken state.
  const placeholder = input.readOnly
    ? input.labels.readOnlySession ?? input.labels.loadingSession
    : !hasSession
    ? input.labels.loadingSession
    : input.sessionBusy && !input.sessionStopping && !input.guidance
      ? (input.followupQueue?.length
        ? input.labels.sessionBusyQueuedPlaceholder
        : input.labels.sessionBusyQueuePlaceholder)
      : isEditingMessage
        ? input.labels.editMessagePlaceholder
        : input.labels.messageInputPlaceholder;

  return {
    readOnly: Boolean(input.readOnly),
    actionDisabled,
    actionDisabledByState,
    actionMode,
    // Image capability applies to image files only. The route filters those
    // files individually, while document attachments remain available.
    attachmentInputDisabled: disabled || Boolean(input.editTargetMessageId),
    attachments: mapChatComposerImageAttachments(input.imageAttachments),
    disabled,
    editUserMessageDisabled: Boolean(input.readOnly) || input.submitPending,
    editingMessageId: input.editTargetMessageId,
    error: input.error ?? "",
    followupQueue: [...(input.followupQueue ?? [])],
    guidance: input.guidance ?? "",
    interruptGuidancePending: input.interruptGuidancePending,
    modeNotice: isEditingMessage ? input.labels.editMessageModeNotice : "",
    modeTargetPreview: isEditingMessage ? input.editTargetPreview?.trim() ?? "" : "",
    pending,
    submitPending: input.submitPending,
    stopPending: input.stopPending || input.sessionStopping,
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
  activeTurnAuthority,
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
        ? projectActiveTurnLayerMessage(streamedActiveTurnLayer, messages, activeTurnAuthority)
        : activeTurnMessage
    ),
    [activeTurnLayersStore, streamedActiveTurnLayer, messages, activeTurnMessage, activeTurnAuthority],
  );
  useChatStartupPresentation({
    sessionId,
    enabled: !props.companionMode && !composer.readOnly,
    transcriptPending: Boolean(props.transcriptPending),
  });
  const terminalActivityLoggedRef = useRef("");
  const terminalActivityRetained = Boolean(
    streamedActiveTurnLayer
    && streamedActiveTurnMessage?.role === "assistant"
    && streamedActiveTurnMessage.status === "completed"
    && streamedActiveTurnMessage.metadata?.processStage === activeTurnAuthority?.terminalReason
    && activeTurnAuthority?.lastTurnTerminalTurnId === streamedActiveTurnLayer.turnId,
  );
  useEffect(() => {
    if (!terminalActivityRetained || !streamedActiveTurnLayer || !activeTurnAuthority) return;
    const key = `${sessionId}:${streamedActiveTurnLayer.turnId}:${activeTurnAuthority.terminalReason}`;
    if (terminalActivityLoggedRef.current === key) return;
    terminalActivityLoggedRef.current = key;
    postBrowserTelemetry({
      phase: "session_stream",
      eventCode: "browser.session_stream.terminal_activity_reconciled",
      message: "Terminal session receipt ended the activity presentation while partial output awaits canonical hydration.",
      level: "info",
      fields: {
        sessionId,
        turnId: streamedActiveTurnLayer.turnId,
        terminalReason: activeTurnAuthority.terminalReason,
        terminalLedgerSeq: activeTurnAuthority.ledgerSeq,
        layerLedgerSeq: streamedActiveTurnLayer.ledgerSeq,
        retainedItemCount: streamedActiveTurnLayer.turnItems.length,
      },
    });
  }, [terminalActivityRetained, streamedActiveTurnLayer, activeTurnAuthority, sessionId]);
  // The draft lives in a store the composer subscribes to, so typing no longer
  // re-renders this bridge or the session view behind it. It is rebuilt when the
  // edit target changes, because the upstream draft is a different string then.
  const draftStore = useMemo(
    () => createComposerDraftStore(liveComposerDraftOr(sessionId, composer.value)),
    [sessionId, composer.editingMessageId],
  );
  // Submitting clears the upstream draft while the store keeps the keystroke
  // text, so without this the composer keeps showing the message just sent.
  useEffect(() => {
    syncComposerDraftStoreFromUpstream(draftStore, composer.value);
  }, [composer.value, draftStore]);
  // The submit path can clear the upstream draft without a state change:
  // typing reaches `composer.value` after the typing pause, so a submit
  // inside that window leaves both values empty and this sync never runs.
  // Registration lets the submit path clear the mounted store directly.
  useEffect(() => registerComposerDraftStore(sessionId, draftStore), [draftStore, sessionId]);
  // Ordinary switches resolve to their own id and remount; only the create
  // rebase keeps the temp id, so that one swap stops remounting the pane.
  const conversationViewKey = resolveComposerViewKey(sessionId);

  return (
    <LazyConversationView
      key={conversationViewKey}
      {...props}
      turnModelControl={composer.readOnly ? undefined : props.turnModelControl}
      sessionId={sessionId}
      messages={messages}
      activeTurnMessage={streamedActiveTurnMessage}
      composerVariant="codex"
      slashCommandSuggestions={slashCommandSuggestions}
      composerDraftStore={draftStore}
      composerPlaceholder={composer.placeholder}
      composerDisabled={composer.disabled}
      regenerateDisabled={composer.disabled || props.regenerateDisabled}
      branchVersionSwitchDisabled={composer.disabled || props.branchVersionSwitchDisabled}
      composerActionDisabled={composer.actionDisabledByState}
      composerActionMode={composer.actionMode}
      composerPending={composer.pending}
      composerSubmitPending={composer.submitPending}
      composerStopPending={composer.stopPending}
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
