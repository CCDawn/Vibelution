/**
 * Upload-then-submit for a direct turn, and upload-then-edit-resubmit.
 * The submit callback stays a hook called at its original site. The edit path
 * is a plain function so it does not move the surrounding submit hook.
 */
import { useCallback, type Dispatch, type MutableRefObject, type SetStateAction } from "react";
import type { QueryClient } from "@tanstack/react-query";

import { queryKeys } from "../../api/queryKeys";
import type { ConversationAttachment, SessionDetail, SessionModelSelection, SessionReferenceAttachment } from "../../api/types";
import {
  createOptimisticActiveTurnLayer,
  setActiveTurnLayerForSession,
  type ActiveTurnLayerState,
} from "../chatActiveTurnLayer";
import type { ChatEditTarget } from "../chatComposerState";
import { appendOptimisticUserMessage, markSessionDetailRunning } from "../chatSessionState";
import {
  applyComposerAttachmentUploadOutcomes,
  clearSessionDraftForSubmittedTurn,
  composerUploadedArtifactIds,
  markComposerAttachmentsUploading,
  needsComposerAttachmentUpload,
  uploadComposerAttachmentsSettled,
  type ComposerAttachmentUploadOutcome,
  type ComposerImageAttachment,
} from "./chatComposerSubmitModel";
import {
  isFailedUploadOutcome,
  removeOptimisticUserMessageFromCache,
  restoreSubmittedDraftAfterFailure,
} from "./useChatComposerTurnMutations";
import { createSubmittedAttachmentPreviews } from "./chatSubmittedAttachmentPreviews";
import { chatStreamPerformanceNowMs } from "./chatCodingRouteViewModel";
import {
  beginSessionDraftRecoveryGuard,
  releaseSessionDraftRecoveryGuard,
  removeStoredSessionDraft,
} from "./chatDraftPersistence";
import { postSubmitTelemetry } from "./chatSubmitTelemetry";
import { loadTurnStatusTailConfig } from "./turnStatusTailModel";
import type { EditResubmitVariables, SubmitTurnVariables } from "./useChatComposerSubmit";

export type UseSubmitTurnWithAttachmentsInput = {
  queryClient: QueryClient;
  lang: "zh" | "en";
  describeError: (error: unknown, fallback: string) => string;
  companionAgentId?: string;
  isMountedRef: MutableRefObject<boolean>;
  isModelParametersSavePendingNow: () => boolean;
  imageUploadInFlightRef: MutableRefObject<Record<string, boolean>>;
  pendingUploadSubmissionRef: MutableRefObject<Map<string, string>>;
  resolveComposerSessionId: (sessionId: string) => string;
  rememberComposerAttachmentUrls: (sessionId: string, attachments: ComposerImageAttachment[]) => void;
  restoreComposerAttachmentUrls: (sessionId: string, attachments: ComposerImageAttachment[]) => ComposerImageAttachment[];
  forgetComposerAttachmentUrl: (sessionId: string, attachment: Pick<ComposerImageAttachment, "id" | "previewUrl">) => void;
  isComposerAttachmentOwned: (sessionId: string, attachmentId: string) => boolean;
  retainOwnedComposerUploadOutcomes: (
    sessionId: string,
    attachments: ComposerImageAttachment[],
    outcomes: ComposerAttachmentUploadOutcome[],
  ) => ComposerAttachmentUploadOutcome[];
  restorePendingStopAfterUploadFailure: (sessionId: string) => void;
  setSessionImageAttachments: Dispatch<SetStateAction<Record<string, ComposerImageAttachment[]>>>;
  setSessionImageUploadPending: Dispatch<SetStateAction<Record<string, boolean>>>;
  setSessionComposerErrors: Dispatch<SetStateAction<Record<string, string>>>;
  setSessionDrafts: Dispatch<SetStateAction<Record<string, string>>>;
  setActiveTurnLayersBySession?: Dispatch<SetStateAction<Record<string, ActiveTurnLayerState>>>;
  submitTurnMutation: { mutate: (variables: SubmitTurnVariables) => void };
};

export function useSubmitTurnWithAttachments({
  queryClient,
  lang,
  describeError,
  companionAgentId,
  isMountedRef,
  isModelParametersSavePendingNow,
  imageUploadInFlightRef,
  pendingUploadSubmissionRef,
  resolveComposerSessionId,
  rememberComposerAttachmentUrls,
  restoreComposerAttachmentUrls,
  forgetComposerAttachmentUrl,
  isComposerAttachmentOwned,
  retainOwnedComposerUploadOutcomes,
  restorePendingStopAfterUploadFailure,
  setSessionImageAttachments,
  setSessionImageUploadPending,
  setSessionComposerErrors,
  setSessionDrafts,
  setActiveTurnLayersBySession,
  submitTurnMutation,
}: UseSubmitTurnWithAttachmentsInput) {
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

  return submitTurnWithAttachments;
}

export type UploadAttachmentsThenEditResubmitInput = {
  activeSessionId: string;
  clientSubmissionId: string;
  content: string;
  editTarget: ChatEditTarget;
  editAttachments: ComposerImageAttachment[];
  carriedAttachmentIds: string[];
  lang: "zh" | "en";
  mentalModelEnabledForNextTurn: boolean;
  runtimeStatusEnabledForNextTurn: boolean;
  describeError: (error: unknown, fallback: string) => string;
  isMountedRef: MutableRefObject<boolean>;
  isModelParametersSavePendingNow: () => boolean;
  imageUploadInFlightRef: MutableRefObject<Record<string, boolean>>;
  pendingUploadSubmissionRef: MutableRefObject<Map<string, string>>;
  resolveComposerSessionId: (sessionId: string) => string;
  rememberComposerAttachmentUrls: (sessionId: string, attachments: ComposerImageAttachment[]) => void;
  isComposerAttachmentOwned: (sessionId: string, attachmentId: string) => boolean;
  retainOwnedComposerUploadOutcomes: UseSubmitTurnWithAttachmentsInput["retainOwnedComposerUploadOutcomes"];
  restorePendingStopAfterUploadFailure: (sessionId: string) => void;
  setSessionImageAttachments: Dispatch<SetStateAction<Record<string, ComposerImageAttachment[]>>>;
  setSessionImageUploadPending: Dispatch<SetStateAction<Record<string, boolean>>>;
  setSessionComposerErrors: Dispatch<SetStateAction<Record<string, string>>>;
  editResubmitMutation: { mutate: (variables: EditResubmitVariables) => void };
};

export async function uploadAttachmentsThenEditResubmit({
  activeSessionId,
  clientSubmissionId,
  content,
  editTarget,
  editAttachments,
  carriedAttachmentIds,
  lang,
  mentalModelEnabledForNextTurn,
  runtimeStatusEnabledForNextTurn,
  describeError,
  isMountedRef,
  isModelParametersSavePendingNow,
  imageUploadInFlightRef,
  pendingUploadSubmissionRef,
  resolveComposerSessionId,
  rememberComposerAttachmentUrls,
  isComposerAttachmentOwned,
  retainOwnedComposerUploadOutcomes,
  restorePendingStopAfterUploadFailure,
  setSessionImageAttachments,
  setSessionImageUploadPending,
  setSessionComposerErrors,
  editResubmitMutation,
}: UploadAttachmentsThenEditResubmitInput) {
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
}
