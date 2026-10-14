/**
 * Composer attachment preview URLs, tray edits, and upload retry.
 * Stop-during-upload state stays in the submit hook and is passed in, so the
 * queued-turn hint effect and rerun-file choice keep their original order.
 */
import { useCallback, useEffect, useRef, type Dispatch, type MutableRefObject, type SetStateAction } from "react";
import type { QueryClient } from "@tanstack/react-query";

import { resolveLocalFilePath } from "../../api/desktopPlatform";
import { queryKeys } from "../../api/queryKeys";
import type { SessionDetail } from "../../api/types";
import type { ComposerAttachmentUploadOutcome, ComposerImageAttachment } from "./chatComposerSubmitModel";
import {
  MAX_COMPOSER_DOCUMENT_ATTACHMENTS,
  MAX_COMPOSER_IMAGE_ATTACHMENTS,
  applyComposerAttachmentUploadOutcomes,
  classifyComposerFiles,
  failedComposerAttachmentUploads,
  markComposerAttachmentsUploading,
  mergeComposerAttachmentsWithRejections,
  uploadComposerAttachmentsSettled,
} from "./chatComposerSubmitModel";
import { clearSessionDetailStopping } from "../chatSessionState";
import { postSubmitTelemetry } from "./chatSubmitTelemetry";
import type { DeferredStopIntent } from "./chatStopTurnModel";

type PreviewOwner = { file: File; previewUrl: string | null };

export type ComposerAttachmentSnapshot = {
  sessionId: string | null | undefined;
  attachments: ComposerImageAttachment[];
};

type ComposerAttachmentUploadFailure = Extract<ComposerAttachmentUploadOutcome, { status: "failed" }>;

export function isFailedUploadOutcome(outcome: ComposerAttachmentUploadOutcome): outcome is ComposerAttachmentUploadFailure {
  return outcome.status === "failed";
}

export type UseComposerAttachmentPreviewInput = {
  queryClient: QueryClient;
  activeSessionId: string | null | undefined;
  activeImageAttachments: ComposerImageAttachment[];
  resolveComposerSessionId: (sessionId: string) => string;
  pendingStopAfterAcceptRef: MutableRefObject<Map<string, DeferredStopIntent>>;
  pendingUploadSubmissionRef: MutableRefObject<Map<string, string>>;
  composerPreviewUrlsBySessionRef: MutableRefObject<Map<string, Map<string, PreviewOwner>>>;
  composerSessionAliasesRef: MutableRefObject<Map<string, string>>;
  pendingPreviewReleaseTokenBySessionRef: MutableRefObject<Map<string, number>>;
  composerLifecycleTokenRef: MutableRefObject<number>;
  isMountedRef: MutableRefObject<boolean>;
  clearedEditMutationVariablesRef: MutableRefObject<unknown>;
  imageUploadInFlightRef: MutableRefObject<Record<string, boolean>>;
  setSessionImageAttachments: Dispatch<SetStateAction<Record<string, ComposerImageAttachment[]>>>;
  setSessionImageUploadPending: Dispatch<SetStateAction<Record<string, boolean>>>;
  editResubmitMutation: { isSuccess: boolean; variables?: { sessionId?: string } | undefined };
};

export function useComposerAttachmentPreview({
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
}: UseComposerAttachmentPreviewInput) {
  const restorePendingStopAfterUploadFailure = useCallback((sessionId: string) => {
    sessionId = resolveComposerSessionId(sessionId);
    const pendingStop = pendingStopAfterAcceptRef.current.get(sessionId);
    if (pendingStop?.stoppingAt) {
      queryClient.setQueryData<SessionDetail>(queryKeys.session(sessionId), (current) => {
        if (!current) {
          return current;
        }
        return clearSessionDetailStopping(current, {
          requestedAt: pendingStop.stoppingAt!,
          previous: pendingStop.previousDetail,
        });
      });
    }
    pendingStopAfterAcceptRef.current.delete(sessionId);
  }, [queryClient, resolveComposerSessionId]);
  const attachmentSnapshotRef = useRef<{ sessionId: string | null | undefined; attachments: ComposerImageAttachment[] }>({
    sessionId: activeSessionId,
    attachments: activeImageAttachments,
  });
  const lastAttachmentInputRef = useRef(activeImageAttachments);
  if (attachmentSnapshotRef.current.sessionId !== activeSessionId || lastAttachmentInputRef.current !== activeImageAttachments) {
    lastAttachmentInputRef.current = activeImageAttachments;
    attachmentSnapshotRef.current = { sessionId: activeSessionId, attachments: activeImageAttachments };
  }

  const rememberComposerAttachmentUrls = useCallback((sessionId: string, attachments: ComposerImageAttachment[]) => {
    sessionId = resolveComposerSessionId(sessionId);
    if (!sessionId || !attachments.length) {
      return;
    }
    let owners = composerPreviewUrlsBySessionRef.current.get(sessionId);
    if (!owners) {
      owners = new Map();
      composerPreviewUrlsBySessionRef.current.set(sessionId, owners);
    }
    for (const attachment of attachments) {
      if (!owners.has(attachment.id)) {
        owners.set(attachment.id, { file: attachment.file, previewUrl: attachment.previewUrl });
      }
    }
  }, [resolveComposerSessionId]);

  const restoreComposerAttachmentUrls = useCallback((sessionId: string, attachments: ComposerImageAttachment[]) => {
    sessionId = resolveComposerSessionId(sessionId);
    if (!sessionId || !attachments.length) {
      return attachments;
    }
    let owners = composerPreviewUrlsBySessionRef.current.get(sessionId);
    if (!owners) {
      owners = new Map();
      composerPreviewUrlsBySessionRef.current.set(sessionId, owners);
    }
    let changed = false;
    const restored = attachments.map((attachment) => {
      let owned = owners!.get(attachment.id);
      if (!owned) {
        owned = { file: attachment.file, previewUrl: attachment.previewUrl };
        owners!.set(attachment.id, owned);
      }
      if (!owned.previewUrl) {
        owned.previewUrl = URL.createObjectURL(owned.file);
      }
      if (owned.previewUrl === attachment.previewUrl) {
        return attachment;
      }
      changed = true;
      return { ...attachment, previewUrl: owned.previewUrl };
    });
    return changed ? restored : attachments;
  }, [resolveComposerSessionId]);

  const releaseComposerSessionPreviewUrls = useCallback((sessionId: string, forgetFiles: boolean) => {
    sessionId = resolveComposerSessionId(sessionId);
    const owners = composerPreviewUrlsBySessionRef.current.get(sessionId);
    if (!owners) {
      return;
    }
    for (const [attachmentId, owned] of owners) {
      if (owned.previewUrl) {
        URL.revokeObjectURL(owned.previewUrl);
      }
      if (forgetFiles) {
        owners.delete(attachmentId);
      } else {
        owned.previewUrl = null;
      }
    }
    if (forgetFiles || owners.size === 0) {
      composerPreviewUrlsBySessionRef.current.delete(sessionId);
    }
  }, [resolveComposerSessionId]);

  const forgetComposerAttachmentUrl = useCallback((
    sessionId: string,
    attachment: Pick<ComposerImageAttachment, "id" | "previewUrl">,
  ) => {
    sessionId = resolveComposerSessionId(sessionId);
    const owners = composerPreviewUrlsBySessionRef.current.get(sessionId);
    const owned = owners?.get(attachment.id);
    const previewUrl = owned ? owned.previewUrl : attachment.previewUrl;
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
    }
    owners?.delete(attachment.id);
    if (owners?.size === 0) {
      composerPreviewUrlsBySessionRef.current.delete(sessionId);
    }
  }, [resolveComposerSessionId]);

  const isComposerAttachmentOwned = useCallback((sessionId: string, attachmentId: string) => (
    composerPreviewUrlsBySessionRef.current.get(resolveComposerSessionId(sessionId))?.has(attachmentId) ?? false
  ), [resolveComposerSessionId]);

  const retainOwnedComposerUploadOutcomes = useCallback((
    sessionId: string,
    attachments: ComposerImageAttachment[],
    outcomes: ComposerAttachmentUploadOutcome[],
  ) => {
    const ownedIds = new Set(
      attachments
        .filter((attachment) => isComposerAttachmentOwned(sessionId, attachment.id))
        .map((attachment) => attachment.id),
    );
    return outcomes.filter((outcome) => ownedIds.has(outcome.id));
  }, [isComposerAttachmentOwned]);

  const cancelScheduledComposerPreviewRelease = useCallback((sessionId: string) => {
    const token = pendingPreviewReleaseTokenBySessionRef.current.get(sessionId) ?? 0;
    pendingPreviewReleaseTokenBySessionRef.current.set(sessionId, token + 1);
  }, []);

  const rebaseComposerPreviewOwners = useCallback((fromSessionId: string, toSessionId: string) => {
    const sourceId = resolveComposerSessionId(fromSessionId);
    const targetId = resolveComposerSessionId(toSessionId);
    if (!sourceId || !targetId || sourceId === targetId) return;
    cancelScheduledComposerPreviewRelease(sourceId);
    cancelScheduledComposerPreviewRelease(targetId);
    const sourceOwners = composerPreviewUrlsBySessionRef.current.get(sourceId);
    // `rekeySessionComposerEntry` keeps an already-present target entry, so
    // dispose the source owners in the same collision case.
    if (composerPreviewUrlsBySessionRef.current.has(targetId)) {
      releaseComposerSessionPreviewUrls(sourceId, true);
      return;
    }
    if (sourceOwners) {
      composerPreviewUrlsBySessionRef.current.set(targetId, sourceOwners);
      composerPreviewUrlsBySessionRef.current.delete(sourceId);
    }
    // An in-flight upload still closes over the temporary id. Keep that id as
    // an alias so settlement writes to the rekeyed attachment state and submits
    // against the newly-created session instead of dropping its upload result.
    composerSessionAliasesRef.current.set(sourceId, targetId);
    if (imageUploadInFlightRef.current[sourceId]) {
      imageUploadInFlightRef.current[targetId] = true;
      delete imageUploadInFlightRef.current[sourceId];
    }
    const pendingUploadSubmission = pendingUploadSubmissionRef.current.get(sourceId);
    if (pendingUploadSubmission) {
      if (!pendingUploadSubmissionRef.current.has(targetId)) {
        pendingUploadSubmissionRef.current.set(targetId, pendingUploadSubmission);
      }
      pendingUploadSubmissionRef.current.delete(sourceId);
    }
    const pendingStop = pendingStopAfterAcceptRef.current.get(sourceId);
    if (pendingStop) {
      if (!pendingStopAfterAcceptRef.current.has(targetId)) {
        pendingStopAfterAcceptRef.current.set(targetId, pendingStop);
      }
      pendingStopAfterAcceptRef.current.delete(sourceId);
    }
    setSessionImageUploadPending((current) => {
      if (!Object.hasOwn(current, sourceId)) return current;
      const { [sourceId]: sourcePending, ...remaining } = current;
      return Object.hasOwn(remaining, targetId)
        ? remaining
        : { ...remaining, [targetId]: sourcePending };
    });
  }, [
    cancelScheduledComposerPreviewRelease,
    imageUploadInFlightRef,
    pendingStopAfterAcceptRef,
    pendingUploadSubmissionRef,
    releaseComposerSessionPreviewUrls,
    resolveComposerSessionId,
    setSessionImageUploadPending,
  ]);

  const scheduleComposerPreviewRelease = useCallback((sessionId: string) => {
    const token = (pendingPreviewReleaseTokenBySessionRef.current.get(sessionId) ?? 0) + 1;
    pendingPreviewReleaseTokenBySessionRef.current.set(sessionId, token);
    void Promise.resolve().then(() => {
      if (pendingPreviewReleaseTokenBySessionRef.current.get(sessionId) !== token) {
        return;
      }
      pendingPreviewReleaseTokenBySessionRef.current.delete(sessionId);
      releaseComposerSessionPreviewUrls(sessionId, false);
    });
  }, [releaseComposerSessionPreviewUrls]);

  const releaseAllComposerPreviewUrls = useCallback(() => {
    for (const sessionId of [...composerPreviewUrlsBySessionRef.current.keys()]) {
      releaseComposerSessionPreviewUrls(sessionId, true);
    }
    composerSessionAliasesRef.current.clear();
  }, [releaseComposerSessionPreviewUrls]);

  useEffect(() => {
    isMountedRef.current = true;
    composerLifecycleTokenRef.current += 1;
    return () => {
      isMountedRef.current = false;
      const token = ++composerLifecycleTokenRef.current;
      void Promise.resolve().then(() => {
        if (composerLifecycleTokenRef.current === token && !isMountedRef.current) {
          releaseAllComposerPreviewUrls();
        }
      });
    };
  }, [releaseAllComposerPreviewUrls]);

  useEffect(() => {
    const sessionId = activeSessionId;
    if (!sessionId) {
      return;
    }
    cancelScheduledComposerPreviewRelease(sessionId);
    const snapshot = attachmentSnapshotRef.current.sessionId === sessionId
      ? attachmentSnapshotRef.current.attachments
      : [];
    const restored = restoreComposerAttachmentUrls(sessionId, snapshot);
    if (restored !== snapshot) {
      setSessionImageAttachments((current) => {
        const latest = current[sessionId] ?? snapshot;
        const owners = composerPreviewUrlsBySessionRef.current.get(sessionId);
        let changed = false;
        const next = latest.map((attachment) => {
          const previewUrl = owners?.get(attachment.id)?.previewUrl;
          if (!previewUrl || previewUrl === attachment.previewUrl) {
            return attachment;
          }
          changed = true;
          return { ...attachment, previewUrl };
        });
        return changed ? { ...current, [sessionId]: next } : current;
      });
    }
    return () => scheduleComposerPreviewRelease(sessionId);
  }, [
    activeSessionId,
    cancelScheduledComposerPreviewRelease,
    restoreComposerAttachmentUrls,
    scheduleComposerPreviewRelease,
    setSessionImageAttachments,
  ]);

  useEffect(() => {
    const variables = editResubmitMutation.variables;
    if (editResubmitMutation.isSuccess && variables?.sessionId && variables !== clearedEditMutationVariablesRef.current) {
      clearedEditMutationVariablesRef.current = variables;
      releaseComposerSessionPreviewUrls(variables.sessionId, true);
    }
  }, [
    editResubmitMutation.isSuccess,
    editResubmitMutation.variables,
    releaseComposerSessionPreviewUrls,
  ]);

  return {
    attachmentSnapshotRef,
    restorePendingStopAfterUploadFailure,
    rememberComposerAttachmentUrls,
    restoreComposerAttachmentUrls,
    releaseComposerSessionPreviewUrls,
    forgetComposerAttachmentUrl,
    isComposerAttachmentOwned,
    retainOwnedComposerUploadOutcomes,
    rebaseComposerPreviewOwners,
  };
}

export type UseComposerAttachmentActionsInput = {
  activeSessionId: string | null | undefined;
  activeAgentImageInputUnsupported: boolean;
  activeImageAttachments: ComposerImageAttachment[];
  lang: "zh" | "en";
  sessionBusy: boolean;
  describeError: (error: unknown, fallback: string) => string;
  attachmentSnapshotRef: MutableRefObject<ComposerAttachmentSnapshot>;
  isMountedRef: MutableRefObject<boolean>;
  imageUploadInFlightRef: MutableRefObject<Record<string, boolean>>;
  resolveComposerSessionId: (sessionId: string) => string;
  rememberComposerAttachmentUrls: (sessionId: string, attachments: ComposerImageAttachment[]) => void;
  forgetComposerAttachmentUrl: (sessionId: string, attachment: Pick<ComposerImageAttachment, "id" | "previewUrl">) => void;
  isComposerAttachmentOwned: (sessionId: string, attachmentId: string) => boolean;
  retainOwnedComposerUploadOutcomes: (
    sessionId: string,
    attachments: ComposerImageAttachment[],
    outcomes: ComposerAttachmentUploadOutcome[],
  ) => ComposerAttachmentUploadOutcome[];
  setSessionComposerErrors: Dispatch<SetStateAction<Record<string, string>>>;
  setSessionImageAttachments: Dispatch<SetStateAction<Record<string, ComposerImageAttachment[]>>>;
  setSessionImageUploadPending: Dispatch<SetStateAction<Record<string, boolean>>>;
};

export function useComposerAttachmentActions({
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
}: UseComposerAttachmentActionsInput) {
  const handleAddComposerAttachments = useCallback((files: FileList | File[]) => {
    if (!activeSessionId) {
      return;
    }
    // Desktop shell resolves drag/picker files back to their local paths so the
    // submit upload can register them zero-copy; clipboard screenshots and web
    // browsers resolve to null and keep the in-memory upload path.
    const { accepted: classifiedAccepted, rejected } = classifyComposerFiles(files, {
      resolveLocalPath: resolveLocalFilePath,
    });
    if (!classifiedAccepted.length && !rejected.length) {
      return;
    }
    // Own every URL returned by classification before applying model and
    // capacity filters, so rejected previews are covered by the same cleanup.
    rememberComposerAttachmentUrls(activeSessionId, classifiedAccepted);
    // Document attachments do not depend on the model's image input support;
    // only image attachments are dropped when the dialogue model lacks vision.
    const accepted = activeAgentImageInputUnsupported
      ? classifiedAccepted.filter((attachment) => attachment.kind !== "image")
      : classifiedAccepted;
    const unsupportedImageNames = activeAgentImageInputUnsupported
      ? classifiedAccepted.filter((attachment) => attachment.kind === "image").map((attachment) => attachment.filename)
      : [];
    if (activeAgentImageInputUnsupported) {
      classifiedAccepted
        .filter((attachment) => attachment.kind === "image")
        .forEach((attachment) => forgetComposerAttachmentUrl(activeSessionId, attachment));
    }
    let capacityRejected: ComposerImageAttachment[] = [];
    if (accepted.length) {
      const attachmentSnapshot = attachmentSnapshotRef.current.sessionId === activeSessionId
        ? attachmentSnapshotRef.current.attachments
        : activeImageAttachments;
      const mergePreview = mergeComposerAttachmentsWithRejections(attachmentSnapshot, accepted, {
        maxTotal: MAX_COMPOSER_IMAGE_ATTACHMENTS + MAX_COMPOSER_DOCUMENT_ATTACHMENTS,
        maxImages: MAX_COMPOSER_IMAGE_ATTACHMENTS,
        maxDocuments: MAX_COMPOSER_DOCUMENT_ATTACHMENTS,
      });
      capacityRejected = mergePreview.rejected;
      capacityRejected.forEach((attachment) => forgetComposerAttachmentUrl(activeSessionId, attachment));
      attachmentSnapshotRef.current = { sessionId: activeSessionId, attachments: mergePreview.attachments };
      setSessionImageAttachments((current) => {
        return {
          ...current,
          [activeSessionId]: mergePreview.attachments,
        };
      });
    }
    const rejectedMessages = [
      rejected.length
        ? (lang === "zh" ? `格式或大小不支持：${rejected.join("、")}` : `type or size is unsupported: ${rejected.join(", ")}`)
        : "",
      unsupportedImageNames.length
        ? (lang === "zh" ? `当前模型不支持图片：${unsupportedImageNames.join("、")}` : `images are unsupported by this model: ${unsupportedImageNames.join(", ")}`)
        : "",
      capacityRejected.length
        ? (lang === "zh"
          ? `数量超出上限：${capacityRejected.map((attachment) => attachment.filename).join("、")}`
          : `attachment limit exceeded: ${capacityRejected.map((attachment) => attachment.filename).join(", ")}`)
        : "",
    ].filter(Boolean);
    setSessionComposerErrors((current) => ({
      ...current,
      [activeSessionId]: rejectedMessages.length
        ? (lang === "zh" ? `部分附件未添加（${rejectedMessages.join("；")}）` : `Some attachments were rejected (${rejectedMessages.join("; ")})`)
        : "",
    }));
  }, [
    activeAgentImageInputUnsupported,
    activeImageAttachments,
    activeSessionId,
    forgetComposerAttachmentUrl,
    lang,
    rememberComposerAttachmentUrls,
    sessionBusy,
    setSessionComposerErrors,
    setSessionImageAttachments,
  ]);

  const handleRemoveComposerAttachment = useCallback((attachmentId: string) => {
    if (!activeSessionId) {
      return;
    }
    const attachmentSnapshot = attachmentSnapshotRef.current.sessionId === activeSessionId
      ? attachmentSnapshotRef.current.attachments
      : activeImageAttachments;
    rememberComposerAttachmentUrls(activeSessionId, attachmentSnapshot);
    const nextAttachments = attachmentSnapshot.filter((attachment) => attachment.id !== attachmentId);
    if (nextAttachments.length === attachmentSnapshot.length) {
      return;
    }
    const removed = attachmentSnapshot.find((attachment) => attachment.id === attachmentId);
    if (removed) forgetComposerAttachmentUrl(activeSessionId, removed);
    attachmentSnapshotRef.current = { sessionId: activeSessionId, attachments: nextAttachments };
    setSessionImageAttachments((current) => ({
      ...current,
      [activeSessionId]: nextAttachments,
    }));
  }, [
    activeImageAttachments,
    activeSessionId,
    forgetComposerAttachmentUrl,
    rememberComposerAttachmentUrls,
    setSessionImageAttachments,
  ]);

  // Upload-repair entry for failed attachment chips: re-uploads only the
  // failed subset (or one chip), respects the same per-session in-flight guard
  // as submit, and never auto-sends — the restored draft waits for the user.
  const retryComposerAttachmentUploads = useCallback(async (sessionId: string, onlyAttachmentId?: string) => {
    if (!isMountedRef.current || !sessionId || imageUploadInFlightRef.current[sessionId]) {
      return;
    }
    const tray = activeImageAttachments;
    const targets = failedComposerAttachmentUploads(tray).filter(
      (attachment) => !onlyAttachmentId || attachment.id === onlyAttachmentId,
    );
    if (!targets.length) {
      return;
    }
    rememberComposerAttachmentUrls(sessionId, targets);
    imageUploadInFlightRef.current[sessionId] = true;
    setSessionImageUploadPending((current) => ({
      ...current,
      [sessionId]: true,
    }));
    setSessionImageAttachments((current) => ({
      ...current,
      [sessionId]: markComposerAttachmentsUploading(
        current[sessionId] ?? [],
        new Set(targets.map((attachment) => attachment.id)),
      ),
    }));
    postSubmitTelemetry(
      "browser.chat_submit.upload_retry_started",
      "Composer attachment upload retry started.",
      sessionId,
      { attachmentCount: targets.length },
    );
    try {
      const settledOutcomes = await uploadComposerAttachmentsSettled(sessionId, targets);
      if (!isMountedRef.current) {
        return;
      }
      const uploadSessionId = resolveComposerSessionId(sessionId);
      const outcomes = retainOwnedComposerUploadOutcomes(uploadSessionId, targets, settledOutcomes);
      setSessionImageAttachments((current) => ({
        ...current,
        [uploadSessionId]: applyComposerAttachmentUploadOutcomes(current[uploadSessionId] ?? [], outcomes),
      }));
      const failedOutcomes = outcomes.filter(isFailedUploadOutcome);
      const remainingFailedChips = failedComposerAttachmentUploads(
        applyComposerAttachmentUploadOutcomes(tray.filter((attachment) => (
          isComposerAttachmentOwned(uploadSessionId, attachment.id)
        )), outcomes),
      ).length;
      if (failedOutcomes.length) {
        postSubmitTelemetry(
          "browser.chat_submit.upload_retry_failed",
          "Composer attachment upload retry finished with failures.",
          uploadSessionId,
          {
            attachmentCount: targets.length,
            uploadedAttachmentCount: targets.length - failedOutcomes.length,
            error: failedOutcomes[0]?.error,
          },
          "error",
        );
        setSessionComposerErrors((current) => ({
          ...current,
          [uploadSessionId]: describeError(
            failedOutcomes[0]?.error,
            lang === "zh" ? "图片上传失败" : "Image upload failed",
          ),
        }));
      } else {
        postSubmitTelemetry(
          "browser.chat_submit.upload_retry_succeeded",
          "Composer attachment upload retry succeeded.",
          uploadSessionId,
          {
            attachmentCount: targets.length,
            uploadedAttachmentCount: targets.length,
          },
        );
        if (remainingFailedChips === 0) {
          // The upload-failure hint must not outlive its chips; unrelated
          // errors were already replaced by the submit failure branch.
          setSessionComposerErrors((current) => ({
            ...current,
            [uploadSessionId]: "",
          }));
        }
      }
    } finally {
      const finishedSessionId = resolveComposerSessionId(sessionId);
      imageUploadInFlightRef.current[finishedSessionId] = false;
      if (isMountedRef.current) {
        setSessionImageUploadPending((current) => ({
          ...current,
          [finishedSessionId]: false,
        }));
      }
    }
  }, [
    activeImageAttachments,
    describeError,
    imageUploadInFlightRef,
    isComposerAttachmentOwned,
    lang,
    rememberComposerAttachmentUrls,
    retainOwnedComposerUploadOutcomes,
    resolveComposerSessionId,
    setSessionComposerErrors,
    setSessionImageAttachments,
    setSessionImageUploadPending,
  ]);

  const handleRetryComposerAttachmentUploads = useCallback(() => {
    if (!activeSessionId) {
      return;
    }
    void retryComposerAttachmentUploads(activeSessionId);
  }, [activeSessionId, retryComposerAttachmentUploads]);

  const handleRetryComposerAttachmentUpload = useCallback((attachmentId: string) => {
    if (!activeSessionId) {
      return;
    }
    void retryComposerAttachmentUploads(activeSessionId, attachmentId);
  }, [activeSessionId, retryComposerAttachmentUploads]);

  return {
    handleAddComposerAttachments,
    handleRemoveComposerAttachment,
    retryComposerAttachmentUploads,
    handleRetryComposerAttachmentUploads,
    handleRetryComposerAttachmentUpload,
  };
}
