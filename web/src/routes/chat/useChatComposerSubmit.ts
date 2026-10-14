import { type QueryClient } from "@tanstack/react-query";
import type { MutationCacheNotifyEvent } from "@tanstack/query-core";
import {
  useCallback,
  useEffect,
  useRef,
  type Dispatch,
  type MutableRefObject,
  type SetStateAction,
} from "react";

import {
} from "../../api/chat";
import { queryKeys } from "../../api/queryKeys";
import type {
  ConversationAttachment,
  ConversationMessage,
  SessionDetail,
  SessionGuidanceMode,
  SessionModelSelection,
  SessionQueuedTurn,
  SessionReferenceAttachment,
  SessionTurnAcceptedResponse,
} from "../../api/types";
import type { RuntimeSummary } from "../../api/types/runtime";
import type { TranslationKey } from "../../i18n/dictionary";
import { removeChatTurnFromRuntimeSummary } from "./chatActiveWorkCache";
import { fetchSessionDetailWindow } from "./chatSessionDetailHelpers";
import {
  bindActiveTurnLayerToTurnId,
  createOptimisticActiveTurnLayer,
  latestUserTurnId,
  settleActiveTurnLayerFromDetail,
  setActiveTurnLayerForSession,
  type ActiveTurnLayerState,
} from "../chatActiveTurnLayer";
import type { ActiveTurnLayersStore } from "./activeTurnLayersStore";
import { isTempSessionId } from "../sessionOptimisticIds";
import { isSteerGuidanceMessage } from "../../components/conversation/conversationMessagePredicates";
import { sessionCreateAttemptState, tempSessionSendBlockedMessage } from "./sessionCreateAttempt";
import {
  useComposerAttachmentActions,
  useComposerAttachmentPreview,
} from "./useComposerAttachmentLifecycle";
import { useRerunFileChoice } from "./useRerunFileChoice";
import {
  appendOptimisticUserMessage,
  applyOptimisticEditResubmit,
  applyOptimisticRegenerate,
  clearSessionDetailStopping,
  createClientSubmissionId,
  markOptimisticUserMessageAccepted,
  markSessionDetailRunning,
  markSessionDetailStopping,
  markSessionSummaryRunning,
  mergeSessionDetailMessageWindow,
  type OptimisticUserMessageInput,
} from "../chatSessionState";
import { updateSessionSummaryCaches } from "../chatSessionIndexQuery";
import type { ChatEditTarget } from "../chatComposerState";
import type { createChatWorkspaceCache } from "../chatWorkspaceCache";
import {
  chatStreamPerformanceNowMs,
  describeChatSubmitError,
  isBusyPhase,
  isRunningPhase,
} from "./chatCodingRouteViewModel";
import {
  MAX_COMPOSER_DOCUMENT_ATTACHMENTS,
  MAX_COMPOSER_IMAGE_ATTACHMENTS,
  applyComposerAttachmentUploadOutcomes,
  clearSessionDraftForSubmittedTurn,
  clearSessionImageAttachments,
  clearUnsupportedSessionImageAttachments,
  clearSessionReferenceAttachments,
  composerUploadedArtifactIds,
  markComposerAttachmentsUploading,
  needsComposerAttachmentUpload,
  resolveComposerSubmitGuard,
  sessionReferenceId,
  uploadComposerAttachmentsSettled,
  uploadSessionImageAttachment,
  writeStoredMentalModelToggle,
  writeStoredRuntimeStatusToggle,
  type ComposerAttachmentUploadOutcome,
  type ComposerImageAttachment,
} from "./chatComposerSubmitModel";
import { loadTurnStatusTailConfig } from "./turnStatusTailModel";
import { createSubmittedAttachmentPreviews } from "./chatSubmittedAttachmentPreviews";
import {
  beginSessionDraftRecoveryGuard,
  releaseSessionDraftRecoveryGuard,
  removeStoredSessionDraft,
  scheduleSessionDraftRecoverySave,
  scheduleSessionDraftSave,
  type SessionDraftRecoveryGuard,
} from "./chatDraftPersistence";
import { type ComposerQueueItem } from "../../components/conversation/composerFollowupQueueModel";
import { postSubmitTelemetry } from "./chatSubmitTelemetry";
import { startUserAction } from "../../app/userActionTelemetry";
import {
  resolveSessionStopTurnId,
  cancelCongestedQueriesForSessionStop,
  type DeferredStopIntent,
} from "./chatStopTurnModel";

import {
  QUEUED_TURN_STUCK_CHECK_INTERVAL_MS,
  exactSubmitTurnId,
  isCurrentRunningSessionTurn,
  isFailedUploadOutcome,
  queuedTurnWaitingSinceMs,
  queuedTurnsWaitingBeyondMs,
  removeOptimisticUserMessageFromCache,
  resolveEditCarryOverAttachmentIds,
  restoreSubmittedDraftAfterFailure,
  type ChatComposerTurnMutations,
} from "./useChatComposerTurnMutations";
import { useComposerFollowupQueue } from "./useComposerFollowupQueue";

export {
  QUEUED_TURN_STUCK_HINT_MS,
  queuedTurnsWaitingBeyondMs,
  resolveEditCarryOverAttachmentIds,
  useChatComposerTurnMutations,
  type ChatComposerTurnMutations,
  type EditResubmitVariables,
  type RegenerateVariables,
  type StopTurnVariables,
  type SubmitTurnVariables,
  type SwitchHeadVariables,
  type UseChatComposerTurnMutationsOptions,
} from "./useChatComposerTurnMutations";

export type UseChatComposerSubmitActionsOptions = ChatComposerTurnMutations & {
  queryClient: QueryClient;
  setActiveTurnLayersBySession?: Dispatch<SetStateAction<Record<string, ActiveTurnLayerState>>>;
  lang: "zh" | "en";
  describeError: (error: unknown, fallback: string) => string;
  setSessionDrafts: Dispatch<SetStateAction<Record<string, string>>>;
  sessionFollowupQueues: Record<string, ComposerQueueItem[]>;
  setSessionComposerErrors: Dispatch<SetStateAction<Record<string, string>>>;
  setSessionImageAttachments: Dispatch<SetStateAction<Record<string, ComposerImageAttachment[]>>>;
  setSessionReferenceAttachments: Dispatch<SetStateAction<Record<string, SessionReferenceAttachment[]>>>;
  setSessionImageUploadPending: Dispatch<SetStateAction<Record<string, boolean>>>;
  setSessionEditTargets: Dispatch<SetStateAction<Record<string, ChatEditTarget>>>;
  imageUploadInFlightRef: MutableRefObject<Record<string, boolean>>;
  activeSessionId: string | null | undefined;
  activeDraftEffective: string;
  activeImageAttachments: ComposerImageAttachment[];
  activeReferenceAttachments: SessionReferenceAttachment[];
  mentalModelEnabledForNextTurn: boolean;
  runtimeStatusEnabledForNextTurn: boolean;
  /** Sticky per-turn model override for the next send; null follows the session default. */
  turnModelSelection: SessionModelSelection | null;
  resolvedEditTarget: ChatEditTarget | null;
  activeEditTarget: ChatEditTarget | null;
  composerDisabled: boolean;
  sessionBusy: boolean;
  sessionStopping: boolean;
  activePhase: string | null | undefined;
  activeAgentImageInputUnsupported: boolean;
  activeImageInputModelId: string;
  latestUserMessageId: string;
  activeTurnId: string | undefined;
  detail: SessionDetail | undefined;
  setMentalModelEnabledForNextTurn: Dispatch<SetStateAction<boolean>>;
  setRuntimeStatusEnabledForNextTurn: Dispatch<SetStateAction<boolean>>;
  companionAgentId?: string;
  /** Synchronous Agent-scoped settings-save gate; omitted on other surfaces. */
  isModelParametersSavePending?: () => boolean;
};

export type UseChatComposerSubmitActionsResult = {
  handleComposerChange: (value: string) => void;
  handleMentalModelEnabledChange: (enabled: boolean) => void;
  handleRuntimeStatusEnabledChange: (enabled: boolean) => void;
  handleAddComposerAttachments: (files: FileList | File[]) => void;
  handleRemoveComposerAttachment: (attachmentId: string) => void;
  /** Re-upload one failed attachment chip; never auto-sends the draft. */
  handleRetryComposerAttachmentUpload: (attachmentId: string) => void;
  /** Re-upload every failed attachment chip of the active session at once. */
  handleRetryComposerAttachmentUploads: () => void;
  /** Session-keyed retry core (tests and advanced callers). */
  retryComposerAttachmentUploads: (sessionId: string, onlyAttachmentId?: string) => Promise<void>;
  /** Move preview URL ownership with a temporary session's attachment state. */
  rebaseComposerPreviewOwners: (fromSessionId: string, toSessionId: string) => void;
  handleAddComposerReference: (reference: SessionReferenceAttachment) => void;
  handleRemoveComposerReference: (referenceId: string) => void;
  handleSubmitTurn: () => void;
  handleStopTurn: () => void;
  handleSubmitGuidance: (mode: SessionGuidanceMode) => void;
  handleFollowupQueueUpdate: (id: string, text: string) => void;
  handleFollowupQueueRemove: (id: string) => void;
  handleFollowupQueueMove: (fromIndex: number, toIndex: number) => void;
  handleFollowupQueueSteer: (id: string) => void;
  handleFollowupQueueTogglePause: (id: string, paused: boolean) => void;
  handleFollowupQueueSendNow: (id: string) => void;
  handleEditUserMessage: (message: ConversationMessage) => void;
  handleCancelEditMessage: () => void;
  handleRegenerateAssistantMessage: (message: ConversationMessage) => void;
  handleRetryFailedTurn: () => void;
  handleSwitchMessageVersion: (message: ConversationMessage, targetNodeId: string) => void;
  rerunFileChoice: {
    paths: string[];
    error: string;
    restoring: boolean;
  } | null;
  confirmRerunFileRestore: () => Promise<void>;
  keepFilesAndRerun: () => void;
  dismissRerunFileChoice: () => void;
};

/**
 * Composer submit/stop/guidance/edit handlers. Call after composerDisabled is derived.
 */
export function useChatComposerSubmitActions({
  queryClient,
  setActiveTurnLayersBySession,
  lang,
  describeError,
  submitTurnMutation,
  editResubmitMutation,
  regenerateMutation,
  switchHeadMutation,
  stopTurnMutation,
  sessionGuidanceMutation,
  setSessionDrafts,
  sessionFollowupQueues,
  setSessionComposerErrors,
  setSessionImageAttachments,
  setSessionReferenceAttachments,
  setSessionImageUploadPending,
  setSessionEditTargets,
  imageUploadInFlightRef,
  activeSessionId,
  activeDraftEffective,
  activeImageAttachments,
  activeReferenceAttachments,
  mentalModelEnabledForNextTurn,
  runtimeStatusEnabledForNextTurn,
  turnModelSelection,
  resolvedEditTarget,
  activeEditTarget,
  composerDisabled,
  sessionBusy,
  sessionStopping,
  activePhase,
  activeAgentImageInputUnsupported,
  activeImageInputModelId,
  activeTurnId,
  detail,
  setMentalModelEnabledForNextTurn,
  setRuntimeStatusEnabledForNextTurn,
  companionAgentId,
  isModelParametersSavePending,
}: UseChatComposerSubmitActionsOptions): UseChatComposerSubmitActionsResult {
  const isModelParametersSavePendingNow = useCallback(
    () => Boolean(isModelParametersSavePending?.()),
    [isModelParametersSavePending],
  );
  const pendingStopAfterAcceptRef = useRef<Map<string, DeferredStopIntent>>(new Map());
  // Uploading attachments happens before React Query creates the submit/edit
  // mutation. Keep the same submission identity visible to Stop during that
  // gap so a stop requested before upload completion can still match the late
  // mutation acceptance, even after switching sessions.
  const pendingUploadSubmissionRef = useRef<Map<string, string>>(new Map());
  // Per-id optimistic queue intents (mirrors pendingAgentIds in
  // useChatAgentArchiveQueue): a second click on a row whose withdraw is still
  // in flight must not re-send the DELETE, while different rows stay free to
  // race in parallel.
  const pendingQueueWithdrawalIdsRef = useRef<Set<string>>(new Set());
  const pendingQueueStatusRef = useRef<Map<string, Promise<boolean>>>(new Map());
  // This hook owns every composer object URL, including URLs for attachments
  // that are rejected after classification. Files remain in the session tray
  // when its preview URLs are released, so returning to a session can restore
  // its previews without keeping Blob URLs alive in the background.
  const composerPreviewUrlsBySessionRef = useRef<Map<string, Map<string, {
    file: File;
    previewUrl: string | null;
  }>>>(new Map());
  const composerSessionAliasesRef = useRef(new Map<string, string>());
  const pendingPreviewReleaseTokenBySessionRef = useRef(new Map<string, number>());
  const composerLifecycleTokenRef = useRef(0);
  const isMountedRef = useRef(false);
  const clearedEditMutationVariablesRef = useRef<unknown>(null);
  // Defect-① observability: a queued turn whose drain never fires (ghost
  // running marker) would sit silently forever. Surface one composer hint per
  // row once its wait exceeds the threshold; forget a row when it leaves the
  // queue so a re-queued row can be hinted again.
  const queuedStuckHintedIdsRef = useRef<Set<string>>(new Set());
  const queuedStuckErrorsRef = useRef<Map<string, { rowId: string; text: string }>>(new Map());
  const resolveComposerSessionId = useCallback((sessionId: string) => {
    let resolved = String(sessionId || "").trim();
    if (!resolved) return resolved;
    const visited = new Set<string>();
    while (!visited.has(resolved)) {
      visited.add(resolved);
      const next = composerSessionAliasesRef.current.get(resolved);
      if (!next) break;
      resolved = next;
    }
    return resolved;
  }, []);
  const {
    rerunFileChoice,
    interceptRerun,
    confirmRerunFileRestore,
    keepFilesAndRerun,
    dismissRerunFileChoice,
  } = useRerunFileChoice({
    sessionId: activeSessionId,
    lang,
    describeError,
  });
  const activeQueuedTurns = detail?.queuedTurns;
  useEffect(() => {
    const sessionId = activeSessionId;
    if (!sessionId) {
      return;
    }
    const surfaceStuckHints = () => {
      const rows = activeQueuedTurns ?? [];
      const aliveIds = new Set(rows.map((row) => row.id));
      for (const hinted of [...queuedStuckHintedIdsRef.current]) {
        if (!aliveIds.has(hinted)) {
          queuedStuckHintedIdsRef.current.delete(hinted);
        }
      }
      const stuckRows = queuedTurnsWaitingBeyondMs(rows, Date.now());
      const previousHint = queuedStuckErrorsRef.current.get(sessionId);
      if (previousHint && !stuckRows.some(row => row.id === previousHint.rowId)) {
        queuedStuckErrorsRef.current.delete(sessionId);
        queuedStuckHintedIdsRef.current.delete(previousHint.rowId);
        // Clear only the hint owned by this effect, preserving newer errors.
        setSessionComposerErrors(current => current[sessionId] === previousHint.text
          ? { ...current, [sessionId]: "" }
          : current);
      }
      const firstStuck = stuckRows[0];
      if (!firstStuck || queuedStuckHintedIdsRef.current.has(firstStuck.id)) {
        return;
      }
      queuedStuckHintedIdsRef.current.add(firstStuck.id);
      const waitedSeconds = Math.max(
        1,
        Math.round((Date.now() - queuedTurnWaitingSinceMs(firstStuck)) / 1000),
      );
      const text = lang === "zh"
        ? `有排队消息等待超过 ${waitedSeconds} 秒仍未开始，当前轮可能卡住了。可停止当前轮让队列立即发送，或撤回后重发。`
        : `A queued message has waited over ${waitedSeconds} seconds without starting; the current turn may be stuck. Stop the current turn to send the queue now, or withdraw it and resend.`;
      queuedStuckErrorsRef.current.set(sessionId, { rowId: firstStuck.id, text });
      setSessionComposerErrors((current) => ({
        ...current,
        [sessionId]: text,
      }));
    };
    surfaceStuckHints();
    const timer = window.setInterval(surfaceStuckHints, QUEUED_TURN_STUCK_CHECK_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [activeSessionId, lang, activeQueuedTurns, setSessionComposerErrors]);
  const {
    attachmentSnapshotRef,
    restorePendingStopAfterUploadFailure,
    rememberComposerAttachmentUrls,
    restoreComposerAttachmentUrls,
    releaseComposerSessionPreviewUrls,
    forgetComposerAttachmentUrl,
    isComposerAttachmentOwned,
    retainOwnedComposerUploadOutcomes,
    rebaseComposerPreviewOwners,
  } = useComposerAttachmentPreview({
    queryClient,
    activeSessionId,
    activeImageAttachments,
    resolveComposerSessionId,
    pendingStopAfterAcceptRef,
    pendingUploadSubmissionRef,
    composerPreviewUrlsBySessionRef,
    composerSessionAliasesRef,
    pendingPreviewReleaseTokenBySessionRef,
    composerLifecycleTokenRef,
    isMountedRef,
    clearedEditMutationVariablesRef,
    imageUploadInFlightRef,
    setSessionImageAttachments,
    setSessionImageUploadPending,
    editResubmitMutation,
  });

  const handleComposerChange = useCallback((value: string) => {
    if (!activeSessionId) {
      return;
    }
    setSessionDrafts((current) => ({
      ...current,
      [activeSessionId]: value,
    }));
    // Debounced localStorage persistence: drafts survive a reload/restart.
    scheduleSessionDraftSave(activeSessionId, value);
    setSessionComposerErrors((current) => ({
      ...current,
      [activeSessionId]: "",
    }));
  }, [activeSessionId, setSessionComposerErrors, setSessionDrafts]);

  const handleMentalModelEnabledChange = useCallback((enabled: boolean) => {
    setMentalModelEnabledForNextTurn(enabled);
    writeStoredMentalModelToggle(enabled);
  }, [setMentalModelEnabledForNextTurn]);

  const handleRuntimeStatusEnabledChange = useCallback((enabled: boolean) => {
    setRuntimeStatusEnabledForNextTurn(enabled);
    writeStoredRuntimeStatusToggle(enabled);
  }, [setRuntimeStatusEnabledForNextTurn]);

  const {
    handleAddComposerAttachments,
    handleRemoveComposerAttachment,
    retryComposerAttachmentUploads,
    handleRetryComposerAttachmentUploads,
    handleRetryComposerAttachmentUpload,
  } = useComposerAttachmentActions({
    activeSessionId,
    activeAgentImageInputUnsupported,
    activeImageAttachments,
    lang,
    sessionBusy,
    describeError,
    attachmentSnapshotRef,
    isMountedRef,
    imageUploadInFlightRef,
    resolveComposerSessionId,
    rememberComposerAttachmentUrls,
    forgetComposerAttachmentUrl,
    isComposerAttachmentOwned,
    retainOwnedComposerUploadOutcomes,
    setSessionComposerErrors,
    setSessionImageAttachments,
    setSessionImageUploadPending,
  });

  const handleAddComposerReference = useCallback((reference: SessionReferenceAttachment) => {
    if (!activeSessionId) {
      return;
    }
    if (activeEditTarget || resolvedEditTarget) {
      setSessionComposerErrors((current) => ({
        ...current,
        [activeSessionId]: lang === "zh"
          ? "编辑重发暂不支持会话引用，请取消编辑后再添加。"
          : "Session references are not supported while editing a message. Cancel the edit first.",
      }));
      return;
    }
    const referenceId = sessionReferenceId(reference);
    if (!referenceId) {
      setSessionComposerErrors((current) => ({
        ...current,
        [activeSessionId]: lang === "zh" ? "会话引用缺少有效 id。" : "Session reference is missing a valid id.",
      }));
      return;
    }
    setSessionReferenceAttachments((current) => {
      const existing = current[activeSessionId] ?? [];
      if (existing.some((item) => sessionReferenceId(item) === referenceId)) {
        return current;
      }
      return {
        ...current,
        [activeSessionId]: [...existing, reference].slice(-6),
      };
    });
    setSessionComposerErrors((current) => ({
      ...current,
      [activeSessionId]: "",
    }));
  }, [
    activeEditTarget,
    activeSessionId,
    lang,
    resolvedEditTarget,
    sessionBusy,
    setSessionComposerErrors,
    setSessionReferenceAttachments,
  ]);

  const handleRemoveComposerReference = useCallback((referenceId: string) => {
    if (!activeSessionId) {
      return;
    }
    setSessionReferenceAttachments((current) => {
      const existing = current[activeSessionId] ?? [];
      const next = existing.filter((reference) => sessionReferenceId(reference) !== referenceId);
      if (next.length === existing.length) {
        return current;
      }
      if (!next.length) {
        return clearSessionReferenceAttachments(current, activeSessionId);
      }
      return {
        ...current,
        [activeSessionId]: next,
      };
    });
  }, [activeSessionId, setSessionReferenceAttachments]);

  const submitTurnWithAttachments = useCallback(async (
    sessionId: string,
    content: string,
    attachments: ComposerImageAttachment[],
    references: SessionReferenceAttachment[],
    mentalModelEnabled: boolean,
    runtimeStatusEnabled: boolean,
    clientSubmissionId: string,
    queuedBehindActiveTurn = false,
    modelSelection: SessionModelSelection | null = null,
  ) => {
    if (!isMountedRef.current || isModelParametersSavePendingNow()) {
      return;
    }
    if (imageUploadInFlightRef.current[sessionId]) {
      postSubmitTelemetry(
        "browser.chat_submit.blocked",
        "Direct chat submit was blocked while image upload was already in flight.",
        sessionId,
        {
          content,
          attachmentCount: attachments.length,
          referenceCount: references.length,
          mentalModelEnabled,
          guardReason: "image_upload_in_flight",
          clientSubmissionId,
        },
        "warning",
      );
      return;
    }
    rememberComposerAttachmentUrls(sessionId, attachments);
    let submittedAttachments = attachments;
    let submittedSessionId = resolveComposerSessionId(sessionId);
    const restoreAttachmentsAfterFailure = () => {
      if (!isMountedRef.current || !attachments.length) return;
      const restoreSessionId = resolveComposerSessionId(sessionId);
      const restored = restoreComposerAttachmentUrls(restoreSessionId, submittedAttachments);
      setSessionImageAttachments((current) => {
        const byId = new Map(restored.map((attachment) => [attachment.id, attachment]));
        for (const attachment of current[restoreSessionId] ?? []) {
          if (!byId.has(attachment.id)) byId.set(attachment.id, attachment);
        }
        return { ...current, [restoreSessionId]: [...byId.values()] };
      });
    };
    const releaseSubmittedComposerAttachmentOwners = () => {
      submittedAttachments.forEach((attachment) => forgetComposerAttachmentUrl(sessionId, attachment));
    };
    imageUploadInFlightRef.current[sessionId] = true;
    pendingUploadSubmissionRef.current.set(sessionId, clientSubmissionId);
    setSessionImageUploadPending((current) => ({
      ...current,
      [sessionId]: true,
    }));
    setSessionDrafts((current) => clearSessionDraftForSubmittedTurn(current, sessionId));
    // The submitted draft must not resurrect from localStorage after a reload.
    removeStoredSessionDraft(sessionId);
    let draftRecoveryGuard = beginSessionDraftRecoveryGuard(sessionId);
    let mutationOwnsRecoveryGuard = false;
    setSessionComposerErrors((current) => ({
      ...current,
      [sessionId]: "",
    }));
    const immediatePreview = !companionAgentId && !queuedBehindActiveTurn;
    let previewAttachments: ConversationAttachment[] = [];
    try {
      previewAttachments = immediatePreview
        ? createSubmittedAttachmentPreviews(queryClient, sessionId, clientSubmissionId, attachments)
        : [];
      if (immediatePreview && previewAttachments.length) {
        const submittedIds = new Set(attachments.map((attachment) => attachment.id));
        // Move the submitted snapshot without revoking the upload owner's URLs.
        setSessionImageAttachments((current) => ({
          ...current,
          [sessionId]: (current[sessionId] ?? []).filter((attachment) => !submittedIds.has(attachment.id)),
        }));
      }
      if (!queuedBehindActiveTurn && (content || references.length || previewAttachments.length)) {
        queryClient.setQueryData<SessionDetail>(queryKeys.session(sessionId), (detailState) =>
          markSessionDetailRunning(appendOptimisticUserMessage(detailState, { sessionId, content, references, clientSubmissionId, attachments: previewAttachments })),
        );
        if (immediatePreview) {
          setActiveTurnLayersBySession?.((current) => setActiveTurnLayerForSession(current, sessionId,
            createOptimisticActiveTurnLayer({ sessionId, clientSubmissionId, accepted: false }),
          ));
        }
      }
      if (attachments.length) {
        postSubmitTelemetry(
          "browser.chat_submit.upload_started",
          "Direct chat submit image upload started.",
          sessionId,
          {
            content,
            attachmentCount: attachments.length,
            referenceCount: references.length,
            mentalModelEnabled,
            clientSubmissionId,
          },
        );
      }
      // Per-attachment settle: successes keep their artifactId (reused on
      // resubmit), failures flip their chip to the retryable failed state
      // instead of discarding the whole batch.
      const needUpload = attachments.filter(needsComposerAttachmentUpload);
      let outcomes: ComposerAttachmentUploadOutcome[] = [];
      if (needUpload.length) {
        setSessionImageAttachments((current) => ({
          ...current,
          [sessionId]: markComposerAttachmentsUploading(current[sessionId] ?? []),
        }));
        const settledOutcomes = await uploadComposerAttachmentsSettled(sessionId, needUpload);
        if (!isMountedRef.current) {
          return;
        }
        submittedSessionId = resolveComposerSessionId(sessionId);
        if (draftRecoveryGuard?.sessionId !== submittedSessionId) {
          releaseSessionDraftRecoveryGuard(draftRecoveryGuard);
          draftRecoveryGuard = beginSessionDraftRecoveryGuard(submittedSessionId);
        }
        outcomes = retainOwnedComposerUploadOutcomes(submittedSessionId, needUpload, settledOutcomes);
        submittedAttachments = applyComposerAttachmentUploadOutcomes(attachments, outcomes);
        setSessionImageAttachments((current) => ({
          ...current,
          [submittedSessionId]: applyComposerAttachmentUploadOutcomes(current[submittedSessionId] ?? [], outcomes),
        }));
      }
      if (!isMountedRef.current) {
        return;
      }
      submittedSessionId = resolveComposerSessionId(sessionId);
      const failedOutcomes = outcomes.filter(isFailedUploadOutcome);
      if (failedOutcomes.length) {
        const firstFailure = failedOutcomes[0];
        postSubmitTelemetry(
          "browser.chat_submit.upload_failed",
          "Direct chat submit image upload failed before message POST.",
          submittedSessionId,
          {
            content,
            attachmentCount: attachments.length,
            uploadedAttachmentCount: attachments.length - failedOutcomes.length,
            referenceCount: references.length,
            mentalModelEnabled,
            clientSubmissionId,
            error: firstFailure.error,
          },
          "error",
        );
        setSessionComposerErrors((current) => ({
          ...current,
          [submittedSessionId]: describeError(firstFailure.error, lang === "zh" ? "图片上传失败" : "Image upload failed"),
        }));
        restoreAttachmentsAfterFailure();
        if (content || references.length || previewAttachments.length) {
          removeOptimisticUserMessageFromCache(queryClient, submittedSessionId, { sessionId: submittedSessionId, content, references, clientSubmissionId });
          restoreSubmittedDraftAfterFailure(setSessionDrafts, submittedSessionId, content, draftRecoveryGuard);
        }
        if (immediatePreview) setActiveTurnLayersBySession?.((current) => setActiveTurnLayerForSession(current, submittedSessionId, undefined));
        restorePendingStopAfterUploadFailure(submittedSessionId);
        return;
      }
      if (attachments.length) {
        postSubmitTelemetry(
          "browser.chat_submit.upload_succeeded",
          "Direct chat submit image upload succeeded.",
          submittedSessionId,
          {
            content,
            attachmentCount: attachments.length,
            uploadedAttachmentCount: attachments.length,
            referenceCount: references.length,
            mentalModelEnabled,
            clientSubmissionId,
          },
        );
      }
      if (isModelParametersSavePendingNow()) {
        restoreAttachmentsAfterFailure();
        if (content || references.length || previewAttachments.length) {
          removeOptimisticUserMessageFromCache(queryClient, submittedSessionId, {
            sessionId: submittedSessionId,
            content,
            references,
            clientSubmissionId,
          });
          restoreSubmittedDraftAfterFailure(setSessionDrafts, submittedSessionId, content, draftRecoveryGuard);
        }
        if (immediatePreview) {
          setActiveTurnLayersBySession?.((current) => setActiveTurnLayerForSession(current, submittedSessionId, undefined));
        }
        restorePendingStopAfterUploadFailure(submittedSessionId);
        return;
      }
      const stillOwnedAttachments = attachments.filter((attachment) => (
        isComposerAttachmentOwned(submittedSessionId, attachment.id)
      ));
      const uploadedAttachmentIds = composerUploadedArtifactIds(
        applyComposerAttachmentUploadOutcomes(stillOwnedAttachments, outcomes),
      );
      postSubmitTelemetry(
        "browser.chat_submit.submit_mutate_requested",
        "Direct chat submit mutation was requested.",
        submittedSessionId,
        {
          content,
          attachmentCount: attachments.length,
          uploadedAttachmentCount: uploadedAttachmentIds.length,
          referenceCount: references.length,
          mentalModelEnabled,
          clientSubmissionId,
        },
      );
      submitTurnMutation.mutate({
        sessionId: submittedSessionId,
        clientSubmissionId,
        content,
        draftRecoveryGuard,
        mentalModelEnabled,
        runtimeStatusEnabled,
        turnStatusTail: loadTurnStatusTailConfig(submittedSessionId),
        attachmentIds: uploadedAttachmentIds,
        attachments: previewAttachments,
        composerAttachments: submittedAttachments,
        restoreAttachmentsAfterFailure,
        releaseComposerAttachmentOwners: releaseSubmittedComposerAttachmentOwners,
        references,
        requestStartedAtMs: chatStreamPerformanceNowMs(),
        queuedBehindActiveTurn,
        modelSelection,
      });
      mutationOwnsRecoveryGuard = true;
    } catch (error) {
      if (!isMountedRef.current) {
        return;
      }
      // Defense net only: attachment uploads settle per attachment above, so
      // this keeps any unexpected throw on the same failure semantics.
      postSubmitTelemetry(
          "browser.chat_submit.upload_failed",
          "Direct chat submit image upload failed before message POST.",
          submittedSessionId,
        {
          content,
          attachmentCount: attachments.length,
          referenceCount: references.length,
          mentalModelEnabled,
          clientSubmissionId,
          error,
        },
        "error",
      );
      setSessionComposerErrors((current) => ({
        ...current,
        [submittedSessionId]: describeError(error, lang === "zh" ? "图片上传失败" : "Image upload failed"),
      }));
      restoreAttachmentsAfterFailure();
      if (content || references.length || previewAttachments.length) {
        removeOptimisticUserMessageFromCache(queryClient, submittedSessionId, { sessionId: submittedSessionId, content, references, clientSubmissionId });
        restoreSubmittedDraftAfterFailure(setSessionDrafts, submittedSessionId, content, draftRecoveryGuard);
      }
      if (immediatePreview) setActiveTurnLayersBySession?.((current) => setActiveTurnLayerForSession(current, submittedSessionId, undefined));
      restorePendingStopAfterUploadFailure(submittedSessionId);
    } finally {
      if (!mutationOwnsRecoveryGuard) {
        releaseSessionDraftRecoveryGuard(draftRecoveryGuard);
      }
      const finishedSessionId = resolveComposerSessionId(sessionId);
      if (pendingUploadSubmissionRef.current.get(finishedSessionId) === clientSubmissionId) {
        pendingUploadSubmissionRef.current.delete(finishedSessionId);
      }
      imageUploadInFlightRef.current[finishedSessionId] = false;
      if (isMountedRef.current) {
        setSessionImageUploadPending((current) => ({
          ...current,
          [finishedSessionId]: false,
        }));
      }
    }
  }, [
    companionAgentId,
    isModelParametersSavePendingNow,
    restoreComposerAttachmentUrls,
    setSessionImageAttachments,
    setActiveTurnLayersBySession,
    describeError,
    imageUploadInFlightRef,
    isComposerAttachmentOwned,
    forgetComposerAttachmentUrl,
    retainOwnedComposerUploadOutcomes,
    resolveComposerSessionId,
    lang,
    queryClient,
    rememberComposerAttachmentUrls,
    restorePendingStopAfterUploadFailure,
    setSessionComposerErrors,
    setSessionDrafts,
    setSessionImageUploadPending,
    submitTurnMutation,
  ]);

  const {
    handleFollowupQueueUpdate,
    handleFollowupQueueRemove,
    handleFollowupQueueSteer,
    handleFollowupQueueMove,
    handleFollowupQueueTogglePause,
    handleFollowupQueueSendNow,
  } = useComposerFollowupQueue({
    queryClient,
    activeSessionId,
    activeTurnId,
    detail,
    lang,
    describeError,
    setSessionComposerErrors,
    isModelParametersSavePendingNow,
    sessionFollowupQueues,
    sessionGuidanceMutation,
    pendingQueueWithdrawalIdsRef,
    pendingQueueStatusRef,
  });

  const handleSubmitTurn = useCallback(() => {
    if (!activeSessionId || isModelParametersSavePendingNow()) {
      return;
    }
    // Optimistic create shells are local-only until the server id is rebased.
    if (isTempSessionId(activeSessionId)) {
      setSessionComposerErrors((current) => ({
        ...current,
        [activeSessionId]: tempSessionSendBlockedMessage(sessionCreateAttemptState(activeSessionId), lang),
      }));
      return;
    }
    if (sessionBusy && !resolvedEditTarget) {
      const content = activeDraftEffective.trim();
      const hasAttachmentsOrReferences = activeImageAttachments.length > 0 || activeReferenceAttachments.length > 0;
      if (!content && !hasAttachmentsOrReferences) {
        // Codex-style steer: an empty submit on a running turn pushes the first
        // queued item into the active turn instead of waiting for the drain.
        const first = (sessionFollowupQueues[activeSessionId] ?? [])[0];
        if (first) {
          handleFollowupQueueSteer(first.id);
        }
        return;
      }
      if (companionAgentId && (activeImageAttachments.length || activeReferenceAttachments.length)) {
        setSessionComposerErrors((current) => ({
          ...current,
          [activeSessionId]: lang === "zh"
            ? "人物正在回复时只能继续发送文字；附件和会话引用请等当前回复结束后再发送。"
            : "While the companion is replying, only text can be queued. Send attachments or session references after the current reply finishes.",
        }));
        return;
      }
      // The backend owns the queue: this POST lands in the server queue when the
      // requested turn is still running and drains after the turn settles.
      void submitTurnWithAttachments(
        activeSessionId,
        content,
        companionAgentId ? [] : activeImageAttachments,
        companionAgentId ? [] : activeReferenceAttachments,
        mentalModelEnabledForNextTurn,
        runtimeStatusEnabledForNextTurn,
        createClientSubmissionId(activeSessionId),
        true,
        turnModelSelection,
      );
      return;
    }
    const content = activeDraftEffective.trim();
    const clientSubmissionId = createClientSubmissionId(activeSessionId);
    const telemetryActivePhase = activePhase ?? undefined;
    postSubmitTelemetry(
      "browser.chat_submit.requested",
      "Direct chat submit was requested from the composer.",
      activeSessionId,
      {
        content,
        attachmentCount: activeImageAttachments.length,
        referenceCount: activeReferenceAttachments.length,
        mentalModelEnabled: mentalModelEnabledForNextTurn,
        editTargetId: resolvedEditTarget?.messageId,
        composerDisabled,
        sessionBusy,
        activePhase: telemetryActivePhase,
        clientSubmissionId,
      },
    );
    const unsupportedImageAttachments = activeImageAttachments.filter((attachment) => attachment.kind === "image");
    if (unsupportedImageAttachments.length && activeAgentImageInputUnsupported) {
      startUserAction("session_message_submit", {
        sessionId: activeSessionId,
        clientSubmissionId,
        attachmentCount: unsupportedImageAttachments.length,
      }).blocked("image_input_unsupported", {
        imageInputModelId: activeImageInputModelId,
      });
      postSubmitTelemetry(
        "browser.chat_submit.blocked",
        "Direct chat submit image upload was blocked because the active Agent model does not support image input.",
        activeSessionId,
        {
          content,
          attachmentCount: unsupportedImageAttachments.length,
          referenceCount: activeReferenceAttachments.length,
          mentalModelEnabled: mentalModelEnabledForNextTurn,
          editTargetId: resolvedEditTarget?.messageId,
          composerDisabled,
          sessionBusy,
          activePhase: telemetryActivePhase,
          guardReason: "image_input_unsupported",
          imageInputModelId: activeImageInputModelId,
          clientSubmissionId,
        },
        "warning",
      );
      setSessionComposerErrors((current) => ({
        ...current,
        [activeSessionId]: lang === "zh" ? "当前 Agent 模型不支持图片输入。" : "The current Agent model does not support image input.",
      }));
      return;
    }
    const guardReason = resolveComposerSubmitGuard({
      composerDisabled,
      content,
      imageAttachmentCount: activeImageAttachments.length,
      referenceAttachmentCount: activeReferenceAttachments.length,
    });
    if (guardReason) {
      startUserAction("session_message_submit", {
        sessionId: activeSessionId,
        clientSubmissionId,
        attachmentCount: activeImageAttachments.length,
        referenceCount: activeReferenceAttachments.length,
      }).blocked(guardReason, {
        composerDisabled,
        sessionBusy,
        activePhase: telemetryActivePhase,
      });
      postSubmitTelemetry(
        "browser.chat_submit.blocked",
        "Direct chat submit was blocked by the composer guard.",
        activeSessionId,
        {
          content,
          attachmentCount: activeImageAttachments.length,
          referenceCount: activeReferenceAttachments.length,
          mentalModelEnabled: mentalModelEnabledForNextTurn,
          editTargetId: resolvedEditTarget?.messageId,
          composerDisabled,
          sessionBusy,
          activePhase: telemetryActivePhase,
          guardReason,
          clientSubmissionId,
        },
        "warning",
      );
      return;
    }
    if (resolvedEditTarget) {
      postSubmitTelemetry(
        "browser.chat_submit.edit_resubmit_requested",
        "Edit-resubmit mutation was requested from the composer.",
        activeSessionId,
        {
          content,
          attachmentCount: activeImageAttachments.length,
          referenceCount: activeReferenceAttachments.length,
          mentalModelEnabled: mentalModelEnabledForNextTurn,
          editTargetId: resolvedEditTarget.messageId,
          composerDisabled,
          sessionBusy,
          activePhase: telemetryActivePhase,
          clientSubmissionId,
        },
      );
      const editTarget = resolvedEditTarget;
      const editAttachments = activeImageAttachments;
      const carriedAttachmentIds = resolveEditCarryOverAttachmentIds(detail, editTarget.messageId);
      const editMessages = detail?.messages ?? [];
      const editStartIndex = editMessages.findIndex(
        (message) => String(message.id || "").trim() === editTarget.messageId,
      );
      const continueEdit = () => {
        void (async () => {
          if (!isMountedRef.current || isModelParametersSavePendingNow()) {
            return;
          }
          let editSessionId = resolveComposerSessionId(activeSessionId);
          if (editAttachments.length && imageUploadInFlightRef.current[editSessionId]) {
            return;
          }
          let uploadedAttachmentIds: string[] = [];
          if (editAttachments.length) {
            rememberComposerAttachmentUrls(activeSessionId, editAttachments);
            imageUploadInFlightRef.current[activeSessionId] = true;
            pendingUploadSubmissionRef.current.set(activeSessionId, clientSubmissionId);
            setSessionImageUploadPending((current) => ({
              ...current,
              [activeSessionId]: true,
            }));
            try {
              // Same per-attachment settle as the direct submit: chips that
              // already carry an artifactId ride along without a re-upload, and
              // failures stay in the tray as retryable failed chips.
              let outcomes: ComposerAttachmentUploadOutcome[] = [];
              const needUpload = editAttachments.filter(needsComposerAttachmentUpload);
              if (needUpload.length) {
                setSessionImageAttachments((current) => ({
                  ...current,
                  [activeSessionId]: markComposerAttachmentsUploading(current[activeSessionId] ?? []),
                }));
                const settledOutcomes = await uploadComposerAttachmentsSettled(activeSessionId, needUpload);
                if (!isMountedRef.current) {
                  return;
                }
                editSessionId = resolveComposerSessionId(activeSessionId);
                outcomes = retainOwnedComposerUploadOutcomes(editSessionId, needUpload, settledOutcomes);
                setSessionImageAttachments((current) => ({
                  ...current,
                  [editSessionId]: applyComposerAttachmentUploadOutcomes(current[editSessionId] ?? [], outcomes),
                }));
              }
              editSessionId = resolveComposerSessionId(activeSessionId);
              const failedOutcomes = outcomes.filter(isFailedUploadOutcome);
              if (failedOutcomes.length) {
                setSessionComposerErrors((current) => ({
                  ...current,
                  [editSessionId]: describeError(
                    failedOutcomes[0].error,
                    lang === "zh" ? "图片上传失败" : "Image upload failed",
                  ),
                }));
                restorePendingStopAfterUploadFailure(editSessionId);
                return;
              }
              const stillOwnedAttachments = editAttachments.filter((attachment) => (
                isComposerAttachmentOwned(editSessionId, attachment.id)
              ));
              uploadedAttachmentIds = composerUploadedArtifactIds(
                applyComposerAttachmentUploadOutcomes(stillOwnedAttachments, outcomes),
              );
            } catch (error) {
              if (!isMountedRef.current) {
                return;
              }
              editSessionId = resolveComposerSessionId(activeSessionId);
              setSessionComposerErrors((current) => ({
                ...current,
                [editSessionId]: describeError(error, lang === "zh" ? "图片上传失败" : "Image upload failed"),
              }));
              restorePendingStopAfterUploadFailure(editSessionId);
              return;
            } finally {
              const finishedSessionId = resolveComposerSessionId(activeSessionId);
              if (pendingUploadSubmissionRef.current.get(finishedSessionId) === clientSubmissionId) {
                pendingUploadSubmissionRef.current.delete(finishedSessionId);
              }
              imageUploadInFlightRef.current[finishedSessionId] = false;
              if (isMountedRef.current) {
                setSessionImageUploadPending((current) => ({
                  ...current,
                  [finishedSessionId]: false,
                }));
              }
            }
          }
          if (!isMountedRef.current) {
            return;
          }
          editSessionId = resolveComposerSessionId(activeSessionId);
          if (isModelParametersSavePendingNow()) {
            return;
          }
          editResubmitMutation.mutate({
            sessionId: editSessionId,
            messageId: editTarget.messageId,
            ...(editTarget.nodeId ? { baseMessageId: editTarget.nodeId } : {}),
            clientSubmissionId,
            content,
            attachmentIds: [...carriedAttachmentIds, ...uploadedAttachmentIds],
            mentalModelEnabled: mentalModelEnabledForNextTurn,
            runtimeStatusEnabled: runtimeStatusEnabledForNextTurn,
            turnStatusTail: loadTurnStatusTailConfig(editSessionId),
          });
        })();
      };
      interceptRerun(editMessages, editStartIndex, continueEdit);
      return;
    }
    void submitTurnWithAttachments(
      activeSessionId,
      content,
      activeImageAttachments,
      activeReferenceAttachments,
      mentalModelEnabledForNextTurn,
      runtimeStatusEnabledForNextTurn,
      clientSubmissionId,
      false,
      turnModelSelection,
    );
  }, [
    activeAgentImageInputUnsupported,
    activeDraftEffective,
    activeImageAttachments,
    activeImageInputModelId,
    isModelParametersSavePendingNow,
    activePhase,
    activeReferenceAttachments,
    activeSessionId,
    composerDisabled,
    companionAgentId,
    describeError,
    detail,
    editResubmitMutation,
    imageUploadInFlightRef,
    interceptRerun,
    isComposerAttachmentOwned,
    lang,
    mentalModelEnabledForNextTurn,
    runtimeStatusEnabledForNextTurn,
    restorePendingStopAfterUploadFailure,
    resolveComposerSessionId,
    resolvedEditTarget,
    sessionBusy,
    sessionFollowupQueues,
    sessionGuidanceMutation,
    sessionStopping,
    turnModelSelection,
    setSessionComposerErrors,
    setSessionDrafts,
    setSessionImageUploadPending,
    rememberComposerAttachmentUrls,
    retainOwnedComposerUploadOutcomes,
    handleFollowupQueueSteer,
    submitTurnWithAttachments,
  ]);

  const handleEditUserMessage = useCallback((message: ConversationMessage) => {
    if (message.role !== "user") {
      return;
    }
    if (!activeSessionId || sessionBusy) {
      return;
    }
    setSessionEditTargets((current) => ({
      ...current,
      [activeSessionId]: {
        messageId: message.id,
        ...(message.nodeId ? { nodeId: message.nodeId } : {}),
        original: message.content,
      },
    }));
    releaseComposerSessionPreviewUrls(activeSessionId, true);
    setSessionImageAttachments((current) => clearSessionImageAttachments(current, activeSessionId));
    setSessionReferenceAttachments((current) => clearSessionReferenceAttachments(current, activeSessionId));
    setSessionDrafts((current) => ({
      ...current,
      [activeSessionId]: message.content,
    }));
    setSessionComposerErrors((current) => ({
      ...current,
      [activeSessionId]: "",
    }));
  }, [
    activeSessionId,
    sessionBusy,
    setSessionComposerErrors,
    setSessionDrafts,
    setSessionEditTargets,
    setSessionImageAttachments,
    setSessionReferenceAttachments,
    releaseComposerSessionPreviewUrls,
  ]);

  useEffect(() => {
    if (!activeSessionId || !detail || !activeEditTarget) {
      return;
    }
    const targetStillVisible = (detail.messages ?? []).some(
      (message) => String(message.id || "").trim() === activeEditTarget.messageId,
    );
    if (targetStillVisible) {
      return;
    }
    setSessionEditTargets((current) => {
      const { [activeSessionId]: _removed, ...remaining } = current;
      return remaining;
    });
    setSessionDrafts((current) => ({
      ...current,
      [activeSessionId]: "",
    }));
  }, [activeEditTarget, activeSessionId, detail, setSessionDrafts, setSessionEditTargets]);

  const handleCancelEditMessage = useCallback(() => {
    if (!activeSessionId) {
      return;
    }
    setSessionEditTargets((current) => {
      const { [activeSessionId]: _removed, ...remaining } = current;
      return remaining;
    });
    setSessionDrafts((current) => ({
      ...current,
      [activeSessionId]: "",
    }));
    removeStoredSessionDraft(activeSessionId);
    releaseComposerSessionPreviewUrls(activeSessionId, true);
    setSessionImageAttachments((current) => clearSessionImageAttachments(current, activeSessionId));
    setSessionReferenceAttachments((current) => clearSessionReferenceAttachments(current, activeSessionId));
  }, [
    activeSessionId,
    setSessionDrafts,
    setSessionEditTargets,
    setSessionImageAttachments,
    setSessionReferenceAttachments,
    releaseComposerSessionPreviewUrls,
  ]);

  const handleRegenerateAssistantMessage = useCallback((message: ConversationMessage) => {
    if (message.role !== "assistant" || !activeSessionId || isModelParametersSavePendingNow() || sessionBusy) {
      return;
    }
    const messages = detail?.messages ?? [];
    const assistantIndex = messages.findIndex(
      (item) => String(item.id || "").trim() === String(message.id || "").trim(),
    );
    if (assistantIndex <= 0) {
      return;
    }
    let userMessage: ConversationMessage | undefined;
    for (let index = assistantIndex - 1; index >= 0; index -= 1) {
      if (messages[index].role === "user" && !isSteerGuidanceMessage(messages[index])) {
        userMessage = messages[index];
        break;
      }
    }
    if (!userMessage || userMessage.role !== "user") {
      return;
    }
    const rerunUser = userMessage;
    // Branch from the clicked assistant answer when it carries a node id;
    // otherwise fall back to the legacy latest-only regenerate.
    const baseMessageId = String(message.nodeId || rerunUser.nodeId || "").trim();
    const clientSubmissionId = createClientSubmissionId(activeSessionId);
    interceptRerun(messages, assistantIndex, () => {
      if (isModelParametersSavePendingNow()) return;
      regenerateMutation.mutate({
        sessionId: activeSessionId,
        messageId: rerunUser.id,
        ...(baseMessageId ? { baseMessageId } : {}),
        clientSubmissionId,
        content: String(rerunUser.content || ""),
        mentalModelEnabled: mentalModelEnabledForNextTurn,
        runtimeStatusEnabled: runtimeStatusEnabledForNextTurn,
        turnStatusTail: loadTurnStatusTailConfig(activeSessionId),
      });
    });
  }, [
    activeSessionId,
    detail,
    interceptRerun,
    isModelParametersSavePendingNow,
    mentalModelEnabledForNextTurn,
    regenerateMutation,
    runtimeStatusEnabledForNextTurn,
    sessionBusy,
  ]);

  // A failed turn has no assistant answer to branch from: retry reruns the
  // latest user message through the same regenerate pipeline as the retry trail.
  const handleRetryFailedTurn = useCallback(() => {
    if (!activeSessionId || isModelParametersSavePendingNow() || sessionBusy) {
      return;
    }
    const messages = detail?.messages ?? [];
    let userMessage: ConversationMessage | undefined;
    let userIndex = -1;
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      if (messages[index].role === "user" && !isSteerGuidanceMessage(messages[index])) {
        userMessage = messages[index];
        userIndex = index;
        break;
      }
    }
    if (!userMessage || userMessage.role !== "user" || userIndex < 0) {
      return;
    }
    const rerunUser = userMessage;
    const baseMessageId = String(rerunUser.nodeId || "").trim();
    const clientSubmissionId = createClientSubmissionId(activeSessionId);
    interceptRerun(messages, userIndex, () => {
      if (isModelParametersSavePendingNow()) return;
      regenerateMutation.mutate({
        sessionId: activeSessionId,
        messageId: rerunUser.id,
        ...(baseMessageId ? { baseMessageId } : {}),
        clientSubmissionId,
        content: String(rerunUser.content || ""),
        mentalModelEnabled: mentalModelEnabledForNextTurn,
        runtimeStatusEnabled: runtimeStatusEnabledForNextTurn,
        turnStatusTail: loadTurnStatusTailConfig(activeSessionId),
      });
    });
  }, [
    activeSessionId,
    detail,
    interceptRerun,
    isModelParametersSavePendingNow,
    mentalModelEnabledForNextTurn,
    regenerateMutation,
    runtimeStatusEnabledForNextTurn,
    sessionBusy,
  ]);

  // Head switching is a server-projected snapshot change: no local tree work,
  // the timeline is replaced by the returned detail.
  const handleSwitchMessageVersion = useCallback((message: ConversationMessage, targetNodeId: string) => {
    if (!activeSessionId || sessionBusy) {
      return;
    }
    const nodeId = String(targetNodeId || "").trim();
    if (!nodeId || nodeId === String(message.nodeId || "").trim()) {
      return;
    }
    switchHeadMutation.mutate({ sessionId: activeSessionId, nodeId });
  }, [activeSessionId, sessionBusy, switchHeadMutation]);

  const handleStopTurn = useCallback(() => {
    if (!activeSessionId || sessionStopping) {
      return;
    }
    const submitPending = Boolean(
      (submitTurnMutation.isPending && submitTurnMutation.variables?.sessionId === activeSessionId)
      || (editResubmitMutation.isPending && editResubmitMutation.variables?.sessionId === activeSessionId)
      || (regenerateMutation.isPending && regenerateMutation.variables?.sessionId === activeSessionId)
    );
    if (!sessionBusy && !submitPending) {
      return;
    }
    void cancelCongestedQueriesForSessionStop(queryClient, activeSessionId);
    const turnId = resolveSessionStopTurnId(detail, activeTurnId);
    if (!turnId) {
      const sessionKey = queryKeys.session(activeSessionId);
      const previousDetail = queryClient.getQueryData<SessionDetail>(sessionKey);
      const stoppingAt = new Date().toISOString();
      const optimisticDetail = markSessionDetailStopping(previousDetail, { requestedAt: stoppingAt });
      if (optimisticDetail) {
        queryClient.setQueryData(sessionKey, optimisticDetail);
      }
      const pendingSubmissionId = submitTurnMutation.isPending
        && submitTurnMutation.variables?.sessionId === activeSessionId
        ? submitTurnMutation.variables.clientSubmissionId
        : editResubmitMutation.isPending
          && editResubmitMutation.variables?.sessionId === activeSessionId
          ? editResubmitMutation.variables.clientSubmissionId
          : regenerateMutation.isPending
            && regenerateMutation.variables?.sessionId === activeSessionId
            ? regenerateMutation.variables.clientSubmissionId
            : pendingUploadSubmissionRef.current.get(activeSessionId);
      pendingStopAfterAcceptRef.current.set(activeSessionId, {
        sessionId: activeSessionId,
        previousDetail,
        stoppingAt,
        clientSubmissionId: pendingSubmissionId,
      });
      return;
    }
    pendingStopAfterAcceptRef.current.delete(activeSessionId);
    stopTurnMutation.mutate({
      sessionId: activeSessionId,
      turnId,
    });
  }, [
    activeSessionId,
    activeTurnId,
    detail,
    editResubmitMutation.isPending,
    editResubmitMutation.variables?.sessionId,
    regenerateMutation.isPending,
    regenerateMutation.variables,
    queryClient,
    sessionBusy,
    sessionStopping,
    stopTurnMutation,
    submitTurnMutation.isPending,
    submitTurnMutation.variables?.sessionId,
  ]);

  const discardDeferredStop = useCallback((sessionId: string, pendingStop: DeferredStopIntent) => {
    pendingStopAfterAcceptRef.current.delete(sessionId);
    if (!pendingStop.stoppingAt) return;
    queryClient.setQueryData<SessionDetail>(queryKeys.session(sessionId), (current) => {
      if (!current) return current;
      return clearSessionDetailStopping(current, {
        requestedAt: pendingStop.stoppingAt!,
        previous: pendingStop.previousDetail,
      });
    });
  }, [queryClient]);

  const dispatchDeferredStop = useCallback((
    sessionId: string,
    pendingStop: DeferredStopIntent,
    acceptedTurnId: string,
    requireCurrentRunningCheck = false,
  ) => {
    const currentDetail = queryClient.getQueryData<SessionDetail>(queryKeys.session(sessionId));
    if (requireCurrentRunningCheck
      && !isCurrentRunningSessionTurn(currentDetail, sessionId, acceptedTurnId)) {
      discardDeferredStop(sessionId, pendingStop);
      return;
    }
    if (stopTurnMutation.isPending) {
      pendingStop.acceptedTurnId = acceptedTurnId;
      if (requireCurrentRunningCheck) pendingStop.recoveredAcceptedTurnId = acceptedTurnId;
      return;
    }
    pendingStopAfterAcceptRef.current.delete(sessionId);
    stopTurnMutation.mutate({
      sessionId,
      turnId: acceptedTurnId,
      deferredStop: {
        previousDetail: pendingStop.previousDetail,
        stoppingAt: pendingStop.stoppingAt,
      },
    });
  }, [discardDeferredStop, queryClient, stopTurnMutation]);

  // Mutation observers only expose the most recently submitted mutation. A
  // late acceptance from session A can therefore disappear behind a newer
  // submission in session B. Subscribe to the cache so every mutation keeps
  // its own submission identity until the deferred stop is dispatched.
  useEffect(() => {
    const unsubscribe = queryClient.getMutationCache().subscribe((event: MutationCacheNotifyEvent) => {
      if (event.type !== "updated") return;
      const { mutation } = event;
      const variables = mutation.state.variables as {
        sessionId?: unknown;
        clientSubmissionId?: unknown;
        messageId?: unknown;
        recoveredAcceptedTurnId?: unknown;
      } | undefined;
      const sessionId = typeof variables?.sessionId === "string" ? variables.sessionId : "";
      const clientSubmissionId = typeof variables?.clientSubmissionId === "string"
        ? variables.clientSubmissionId
        : "";
      if (!sessionId || !clientSubmissionId) return;
      const pendingStop = pendingStopAfterAcceptRef.current.get(sessionId);
      if (!pendingStop || pendingStop.clientSubmissionId !== clientSubmissionId) return;

      if (mutation.state.status === "error") {
        const recoveredTurnId = typeof variables?.recoveredAcceptedTurnId === "string"
          ? variables.recoveredAcceptedTurnId.trim()
          : "";
        if (recoveredTurnId) {
          pendingStop.recoveredAcceptedTurnId = recoveredTurnId;
          dispatchDeferredStop(sessionId, pendingStop, recoveredTurnId, true);
        } else {
          discardDeferredStop(sessionId, pendingStop);
        }
        return;
      }
      if (mutation.state.status !== "success") return;

      const data = mutation.state.data as {
        sessionId?: unknown;
        turnId?: unknown;
      } | SessionDetail | undefined;
      const isResubmit = mutation.options.mutationKey?.[0] === "session_regenerate"
        || mutation.options.mutationKey?.[0] === "session_edit_resubmit";
      const cachedDetail = queryClient.getQueryData<SessionDetail>(queryKeys.session(sessionId));
      const acceptedTurnId = isResubmit
        ? exactSubmitTurnId(cachedDetail, clientSubmissionId)
          || exactSubmitTurnId(data as SessionDetail | undefined, clientSubmissionId)
        : data && typeof data === "object" && "turnId" in data
          ? String(data.turnId || "").trim()
          : "";
      if (!acceptedTurnId) {
        if (isResubmit) discardDeferredStop(sessionId, pendingStop);
        return;
      }
      dispatchDeferredStop(sessionId, pendingStop, acceptedTurnId, isResubmit);
    });
    return unsubscribe;
  }, [discardDeferredStop, dispatchDeferredStop, queryClient]);

  useEffect(() => {
    const acceptedSubmit = submitTurnMutation.data;
    const submitVariables = submitTurnMutation.variables;
    const acceptedEdit = editResubmitMutation.data;
    const editVariables = editResubmitMutation.variables;

    for (const [sessionId, pendingStop] of pendingStopAfterAcceptRef.current) {
      if (!pendingStop.clientSubmissionId) continue;
      const submitMatches = acceptedSubmit?.sessionId === sessionId
        && acceptedSubmit.clientSubmissionId === pendingStop.clientSubmissionId;
      const editMatches = editVariables?.sessionId === sessionId
        && editVariables.clientSubmissionId === pendingStop.clientSubmissionId
        && !editResubmitMutation.isPending
        && !editResubmitMutation.error
        && Boolean(acceptedEdit);
      const recoveredSubmitTurnId = submitVariables?.sessionId === sessionId
        && submitVariables.clientSubmissionId === pendingStop.clientSubmissionId
        ? String(submitVariables.recoveredAcceptedTurnId || "").trim()
        : "";
      const recoveredEditTurnId = editVariables?.sessionId === sessionId
        && editVariables.clientSubmissionId === pendingStop.clientSubmissionId
        ? String(editVariables.recoveredAcceptedTurnId || "").trim()
        : "";
      const acceptedTurnId = pendingStop.acceptedTurnId || recoveredSubmitTurnId || recoveredEditTurnId || (submitMatches
        ? String(acceptedSubmit?.turnId || "").trim()
        : editMatches
          ? exactSubmitTurnId(queryClient.getQueryData<SessionDetail>(queryKeys.session(sessionId)), pendingStop.clientSubmissionId)
            || exactSubmitTurnId(acceptedEdit, pendingStop.clientSubmissionId)
          : "");
      if (acceptedTurnId) {
        dispatchDeferredStop(
          sessionId,
          pendingStop,
          acceptedTurnId,
          Boolean(pendingStop.recoveredAcceptedTurnId || recoveredSubmitTurnId || recoveredEditTurnId || editMatches),
        );
        return;
      }
      const submitFailed = submitVariables?.sessionId === sessionId
        && submitVariables.clientSubmissionId === pendingStop.clientSubmissionId
        && !submitTurnMutation.isPending
        && Boolean(submitTurnMutation.error)
        && !submitMatches;
      const editFailed = editVariables?.sessionId === sessionId
        && editVariables.clientSubmissionId === pendingStop.clientSubmissionId
        && !editResubmitMutation.isPending
        && Boolean(editResubmitMutation.error)
        && !editMatches;
      if (submitFailed || editFailed) {
        discardDeferredStop(sessionId, pendingStop);
      }
    }

    if (!activeSessionId) return;
    const pendingStop = pendingStopAfterAcceptRef.current.get(activeSessionId);
    if (!pendingStop || pendingStop.clientSubmissionId) return;
    const submitPending = Boolean(
      (submitTurnMutation.isPending && submitTurnMutation.variables?.sessionId === activeSessionId)
      || (editResubmitMutation.isPending && editResubmitMutation.variables?.sessionId === activeSessionId)
      || (regenerateMutation.isPending && regenerateMutation.variables?.sessionId === activeSessionId)
    );
    if (!sessionBusy && !submitPending) {
      pendingStopAfterAcceptRef.current.delete(activeSessionId);
      return;
    }
    if (stopTurnMutation.isPending && stopTurnMutation.variables?.sessionId === activeSessionId) {
      return;
    }
    const turnId = resolveSessionStopTurnId(detail, activeTurnId);
    if (!turnId) {
      return;
    }
    pendingStopAfterAcceptRef.current.delete(activeSessionId);
    stopTurnMutation.mutate({
      sessionId: activeSessionId,
      turnId,
      deferredStop: {
        previousDetail: pendingStop.previousDetail,
        stoppingAt: pendingStop.stoppingAt,
      },
    });
  }, [
    activeSessionId,
    activeTurnId,
    detail,
    editResubmitMutation.isPending,
    editResubmitMutation.variables?.sessionId,
    regenerateMutation.isPending,
    regenerateMutation.variables,
    sessionBusy,
    stopTurnMutation,
    submitTurnMutation.isPending,
    submitTurnMutation.data,
    submitTurnMutation.error,
    submitTurnMutation.variables,
    dispatchDeferredStop,
    discardDeferredStop,
    queryClient,
    editResubmitMutation.data,
    editResubmitMutation.error,
    editResubmitMutation.variables,
    submitTurnMutation.variables?.sessionId,
  ]);

  const handleSubmitGuidance = useCallback((mode: SessionGuidanceMode) => {
    if (!activeSessionId || isModelParametersSavePendingNow() || !sessionBusy || sessionStopping) {
      return;
    }
    const content = activeDraftEffective.trim();
    if (!content) {
      return;
    }
    sessionGuidanceMutation.mutate({
      sessionId: activeSessionId,
      content,
      mode,
    });
  }, [activeDraftEffective, activeSessionId, isModelParametersSavePendingNow, sessionBusy, sessionGuidanceMutation, sessionStopping]);

  // Deferred stop intents remain keyed by session while the user moves between
  // sessions. A late submit acceptance is matched by submission identity and
  // stopped immediately, without being applied to a newer turn.

  return {
    handleComposerChange,
    handleMentalModelEnabledChange,
    handleRuntimeStatusEnabledChange,
    handleAddComposerAttachments,
    handleRemoveComposerAttachment,
    handleRetryComposerAttachmentUpload,
    handleRetryComposerAttachmentUploads,
    retryComposerAttachmentUploads,
    rebaseComposerPreviewOwners,
    handleAddComposerReference,
    handleRemoveComposerReference,
    handleSubmitTurn,
    handleStopTurn,
    handleSubmitGuidance,
    handleFollowupQueueUpdate,
    handleFollowupQueueRemove,
    handleFollowupQueueMove,
    handleFollowupQueueSteer,
    handleFollowupQueueTogglePause,
    handleFollowupQueueSendNow,
    handleEditUserMessage,
    handleCancelEditMessage,
    handleRegenerateAssistantMessage,
    handleRetryFailedTurn,
    handleSwitchMessageVersion,
    rerunFileChoice,
    confirmRerunFileRestore,
    keepFilesAndRerun,
    dismissRerunFileChoice,
  };
}
