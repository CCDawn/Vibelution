import { useMutation, type QueryClient, type UseMutationResult } from "@tanstack/react-query";
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
  editResubmitSessionMessage,
  listSessionQueuedTurns,
  regenerateSessionMessage,
  removeSessionQueuedTurn,
  stopSessionTurn,
  submitSessionGuidance,
  submitSessionMessage,
  switchSessionHead,
  updateSessionQueuedTurn,
} from "../../api/chat";
import { submitVirtualHumanConversationMessage } from "../../api/virtualHumanLife";
import { queryKeys } from "../../api/queryKeys";
import type {
  ConversationMessage,
  SessionDetail,
  SessionGuidanceMode,
  SessionQueuedTurn,
  SessionReferenceAttachment,
  SessionTurnAcceptedResponse,
} from "../../api/types";
import type { RuntimeSummary } from "../../api/types/runtime";
import type { TranslationKey } from "../../i18n/dictionary";
import { removeChatTurnFromRuntimeSummary } from "./chatActiveWorkCache";
import {
  createOptimisticActiveTurnLayer,
  latestUserTurnId,
  setActiveTurnLayerForSession,
  type ActiveTurnLayerState,
} from "../chatActiveTurnLayer";
import { isTempSessionId } from "../sessionOptimisticIds";
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
  removeOptimisticUserMessage,
} from "../chatSessionState";
import { updateSessionSummaryCaches } from "../chatSessionIndexQuery";
import type { ChatEditTarget } from "../chatComposerState";
import type { createChatWorkspaceCache } from "../chatWorkspaceCache";
import {
  chatStreamPerformanceNowMs,
  describeChatSubmitError,
  isBusyPhase,
} from "./chatCodingRouteViewModel";
import {
  MAX_COMPOSER_DOCUMENT_ATTACHMENTS,
  MAX_COMPOSER_IMAGE_ATTACHMENTS,
  classifyComposerFiles,
  clearSessionDraftForSubmittedTurn,
  clearSessionImageAttachments,
  clearSessionReferenceAttachments,
  encodeUtf8Base64,
  mergeComposerAttachmentsWithRejections,
  optimisticTurnIdForSubmission,
  resolveComposerSubmitGuard,
  restoreSubmittedDraftIfComposerStillEmpty,
  sessionReferenceId,
  uploadSessionImageAttachment,
  writeStoredMentalModelToggle,
  writeStoredRuntimeStatusToggle,
  type ComposerImageAttachment,
} from "./chatComposerSubmitModel";
import { loadTurnStatusTailConfig } from "./turnStatusTailModel";
import { type ComposerQueueItem } from "../../components/conversation/composerFollowupQueueModel";
import { postSubmitTelemetry } from "./chatSubmitTelemetry";
import { startUserAction, type UserActionTracker } from "../../app/userActionTelemetry";
import {
  resolveSessionStopTurnId,
  resolveStopOptimisticTarget,
  cancelCongestedQueriesForSessionStop,
  type DeferredStopIntent,
  type StopTurnOptimisticContext,
} from "./chatStopTurnModel";

type ChatWorkspaceCache = ReturnType<typeof createChatWorkspaceCache>;

export type SubmitTurnVariables = {
  sessionId: string;
  clientSubmissionId: string;
  content: string;
  mentalModelEnabled: boolean;
  runtimeStatusEnabled: boolean;
  turnStatusTail?: ReturnType<typeof loadTurnStatusTailConfig>;
  attachmentIds?: string[];
  references?: SessionReferenceAttachment[];
  requestStartedAtMs: number;
  queuedBehindActiveTurn?: boolean;
};

type ChatSubmitAcceptedResponse = SessionTurnAcceptedResponse & {
  queued?: boolean;
  queueSequence?: number;
};

type ChatSubmitMutationContext = {
  telemetry: UserActionTracker;
};

export type EditResubmitVariables = {
  sessionId: string;
  messageId: string;
  baseMessageId?: string;
  clientSubmissionId: string;
  content: string;
  mentalModelEnabled: boolean;
  runtimeStatusEnabled: boolean;
  turnStatusTail?: ReturnType<typeof loadTurnStatusTailConfig>;
  attachmentIds?: string[];
};

export type RegenerateVariables = {
  sessionId: string;
  messageId: string;
  baseMessageId?: string;
  clientSubmissionId: string;
  content: string;
  mentalModelEnabled: boolean;
  runtimeStatusEnabled: boolean;
  turnStatusTail?: ReturnType<typeof loadTurnStatusTailConfig>;
};

export type SwitchHeadVariables = {
  sessionId: string;
  nodeId: string;
};

export type StopTurnVariables = {
  sessionId: string;
  turnId: string;
  deferredStop?: StopTurnOptimisticContext;
};

export type ChatComposerTurnMutations = {
  submitTurnMutation: UseMutationResult<ChatSubmitAcceptedResponse, Error, SubmitTurnVariables, unknown>;
  editResubmitMutation: UseMutationResult<SessionDetail, Error, EditResubmitVariables, unknown>;
  regenerateMutation: UseMutationResult<SessionDetail, Error, RegenerateVariables, unknown>;
  switchHeadMutation: UseMutationResult<SessionDetail, Error, SwitchHeadVariables, unknown>;
  stopTurnMutation: UseMutationResult<SessionDetail, Error, StopTurnVariables, unknown>;
  sessionGuidanceMutation: UseMutationResult<
    SessionDetail,
    Error,
    { sessionId: string; content: string; mode: SessionGuidanceMode },
    unknown
  >;
};

export type UseChatComposerTurnMutationsOptions = {
  queryClient: QueryClient;
  chatWorkspaceCache: ChatWorkspaceCache;
  t: (key: TranslationKey) => string;
  describeError: (error: unknown, fallback: string) => string;
  syncSessionDetail: (detail: SessionDetail) => void;
  setActiveTurnLayersBySession: Dispatch<SetStateAction<Record<string, ActiveTurnLayerState>>>;
  setSessionDrafts: Dispatch<SetStateAction<Record<string, string>>>;
  setSessionComposerErrors: Dispatch<SetStateAction<Record<string, string>>>;
  setSessionImageAttachments: Dispatch<SetStateAction<Record<string, ComposerImageAttachment[]>>>;
  setSessionReferenceAttachments: Dispatch<SetStateAction<Record<string, SessionReferenceAttachment[]>>>;
  setSessionEditTargets: Dispatch<SetStateAction<Record<string, ChatEditTarget>>>;
  companionAgentId?: string;
};

/**
 * Direct-session turn mutations only (submit / edit-resubmit / stop / guidance).
 * Call early in ChatCodingRoute; does not open session streams.
 */
export function useChatComposerTurnMutations({
  queryClient,
  chatWorkspaceCache,
  t,
  describeError,
  syncSessionDetail,
  setActiveTurnLayersBySession,
  setSessionDrafts,
  setSessionComposerErrors,
  setSessionImageAttachments,
  setSessionReferenceAttachments,
  setSessionEditTargets,
  companionAgentId,
}: UseChatComposerTurnMutationsOptions): ChatComposerTurnMutations {
  const submitTurnMutation = useMutation<
    ChatSubmitAcceptedResponse,
    Error,
    SubmitTurnVariables,
    ChatSubmitMutationContext
  >({
    mutationFn: async (
      {
        sessionId,
        clientSubmissionId,
        content,
        mentalModelEnabled,
        runtimeStatusEnabled,
        turnStatusTail,
        attachmentIds,
        references,
        queuedBehindActiveTurn,
      }: SubmitTurnVariables,
    ) => {
      const resolvedTail = turnStatusTail ?? loadTurnStatusTailConfig(sessionId);
      postSubmitTelemetry(
        "browser.chat_submit.request_started",
        "Direct chat submit request started.",
        sessionId,
        {
          content,
          attachmentCount: attachmentIds?.length ?? 0,
          referenceCount: references?.length ?? 0,
          mentalModelEnabled,
          runtimeStatusEnabled,
          clientSubmissionId,
        },
      );
      const payload = {
        content,
        clientSubmissionId,
        contentUtf8Base64: encodeUtf8Base64(content),
        attachmentIds: attachmentIds ?? [],
        references: references ?? [],
        mentalModelEnabled,
        runtimeStatusEnabled,
        turnStatusTail: resolvedTail,
      };
      if (companionAgentId) {
        return submitVirtualHumanConversationMessage(companionAgentId, sessionId, payload);
      }
      return submitSessionMessage(sessionId, {
        ...payload,
        queueIfBusy: Boolean(queuedBehindActiveTurn),
      });
    },
    onMutate: async (variables) => {
      const telemetry = startUserAction("session_message_submit", {
        sessionId: variables.sessionId,
        clientSubmissionId: variables.clientSubmissionId,
        attachmentCount: variables.attachmentIds?.length ?? 0,
        referenceCount: variables.references?.length ?? 0,
      });
      postSubmitTelemetry(
        "browser.chat_submit.mutate_called",
        "Direct chat submit mutation started.",
        variables.sessionId,
        {
          content: variables.content,
          attachmentCount: variables.attachmentIds?.length ?? 0,
          referenceCount: variables.references?.length ?? 0,
          mentalModelEnabled: variables.mentalModelEnabled,
          runtimeStatusEnabled: variables.runtimeStatusEnabled,
          clientSubmissionId: variables.clientSubmissionId,
        },
      );
      const createdAt = new Date().toISOString();
      if (!companionAgentId && !variables.queuedBehindActiveTurn) {
        setActiveTurnLayersBySession((current) =>
          setActiveTurnLayerForSession(
            current,
            variables.sessionId,
            createOptimisticActiveTurnLayer({
              sessionId: variables.sessionId,
              turnId: optimisticTurnIdForSubmission("submit", variables.sessionId, createdAt),
              clientSubmissionId: variables.clientSubmissionId,
              updatedAt: createdAt,
            }),
          )
        );
      }
      queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), (detailState) =>
        variables.queuedBehindActiveTurn
          ? detailState
          : markSessionDetailRunning(appendOptimisticUserMessage(detailState, variables)),
      );
      updateSessionSummaryCaches(queryClient, (sessions) =>
        markSessionSummaryRunning(sessions, variables.sessionId),
      );
      if (typeof window !== "undefined" && typeof window.requestAnimationFrame === "function") {
        window.requestAnimationFrame(() => {
          postSubmitTelemetry(
            "browser.chat_submit.optimistic_painted",
            "Optimistic user and Agent rows reached the next browser paint.",
            variables.sessionId,
            {
              clientSubmissionId: variables.clientSubmissionId,
              submitToOptimisticPaintMs: Math.max(
                0,
                Math.round(chatStreamPerformanceNowMs() - variables.requestStartedAtMs),
              ),
              activeStatusSource: "optimistic_submit",
            },
          );
        });
      }
      return { telemetry };
    },
    onSuccess: (acceptedTurn, variables, context) => {
      context?.telemetry?.succeeded({
        sessionId: variables.sessionId,
        clientSubmissionId: variables.clientSubmissionId,
        turnId: acceptedTurn.turnId,
        durationMs: Math.max(0, Math.round(chatStreamPerformanceNowMs() - variables.requestStartedAtMs)),
      });
      postSubmitTelemetry(
        "browser.chat_submit.accepted",
        "Direct chat submit was accepted by the backend.",
        variables.sessionId,
        {
          content: variables.content,
          attachmentCount: variables.attachmentIds?.length ?? 0,
          referenceCount: variables.references?.length ?? 0,
          mentalModelEnabled: variables.mentalModelEnabled,
          clientSubmissionId: variables.clientSubmissionId,
          turnId: acceptedTurn.turnId,
          acceptedAt: acceptedTurn.acceptedAt,
          durationMs: Math.max(0, chatStreamPerformanceNowMs() - variables.requestStartedAtMs),
        },
      );
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      setSessionImageAttachments((current) => clearSessionImageAttachments(current, variables.sessionId));
      setSessionReferenceAttachments((current) => clearSessionReferenceAttachments(current, variables.sessionId));
      const acceptedTurnId = String(acceptedTurn.turnId || "").trim();
      queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), (detailState) => {
        const acceptedDetail = markSessionDetailRunning(
          markOptimisticUserMessageAccepted(detailState, variables, acceptedTurn.turnId),
        );
        return acceptedTurnId && acceptedDetail
          ? { ...acceptedDetail, activeTurnId: acceptedTurnId }
          : acceptedDetail;
      });
      setActiveTurnLayersBySession((current) =>
        acceptedTurn.queued || variables.queuedBehindActiveTurn
          ? current
          : setActiveTurnLayerForSession(
          current,
          variables.sessionId,
          acceptedTurnId
            ? createOptimisticActiveTurnLayer({
              sessionId: variables.sessionId,
              turnId: acceptedTurn.turnId,
              clientSubmissionId: variables.clientSubmissionId,
              updatedAt: acceptedTurn.acceptedAt,
            })
            : undefined,
          )
      );
      // The optimistic detail/index updates above already expose the accepted turn.
      // SSE owns authoritative reconciliation when available; the existing polling
      // fallback does the same without competing with the first model request.
      if (acceptedTurn.queuedTurnId) {
        void listSessionQueuedTurns(variables.sessionId)
          .then((rows) => {
            queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), (detailState) =>
              detailState ? { ...detailState, queuedTurns: rows } : detailState,
            );
          })
          .catch(() => undefined);
      }
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, {
        sessionId: variables.sessionId,
        clientSubmissionId: variables.clientSubmissionId,
        durationMs: Math.max(0, Math.round(chatStreamPerformanceNowMs() - variables.requestStartedAtMs)),
      });
      postSubmitTelemetry(
        "browser.chat_submit.request_failed",
        "Direct chat submit request failed before the backend accepted the turn.",
        variables.sessionId,
        {
          content: variables.content,
          attachmentCount: variables.attachmentIds?.length ?? 0,
          referenceCount: variables.references?.length ?? 0,
          mentalModelEnabled: variables.mentalModelEnabled,
          clientSubmissionId: variables.clientSubmissionId,
          durationMs: Math.max(0, chatStreamPerformanceNowMs() - variables.requestStartedAtMs),
          error,
        },
        "error",
      );
      queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), (detailState) =>
        removeOptimisticUserMessage(detailState, variables),
      );
      if (!variables.queuedBehindActiveTurn) {
        setActiveTurnLayersBySession((current) =>
          setActiveTurnLayerForSession(current, variables.sessionId, undefined)
        );
      }
      setSessionDrafts((current) => restoreSubmittedDraftIfComposerStillEmpty(current, variables.sessionId, variables.content));
      setSessionComposerErrors((current) => ({
        ...current,
        // Classified human copy (e.g. 409 -> "a turn is already generating");
        // the raw error is reported through telemetry above, not the composer.
        [variables.sessionId]: describeChatSubmitError(error, t, t("submitFailed")),
      }));
      void chatWorkspaceCache.afterDirectTurnFailed(variables.sessionId);
    },
  });

  const editResubmitMutation = useMutation({
    mutationFn: async (
      {
        sessionId,
        messageId,
        baseMessageId,
        clientSubmissionId,
        content,
        mentalModelEnabled,
        runtimeStatusEnabled,
        turnStatusTail,
        attachmentIds,
      }: EditResubmitVariables,
    ) =>
      editResubmitSessionMessage(sessionId, {
        messageId,
        ...(baseMessageId ? { baseMessageId } : {}),
        clientSubmissionId,
        content,
        contentUtf8Base64: encodeUtf8Base64(content),
        attachmentIds: attachmentIds ?? [],
        mentalModelEnabled,
        runtimeStatusEnabled,
        turnStatusTail: turnStatusTail ?? loadTurnStatusTailConfig(sessionId),
      }),
    onMutate: async (variables) => {
      const telemetry = startUserAction("session_edit_resubmit", {
        sessionId: variables.sessionId,
        messageId: variables.messageId,
        clientSubmissionId: variables.clientSubmissionId,
        contentLength: variables.content.length,
      });
      const sessionKey = queryKeys.session(variables.sessionId);
      await queryClient.cancelQueries({ queryKey: sessionKey, exact: true });
      const previousDetail = queryClient.getQueryData<SessionDetail>(sessionKey);
      const createdAt = new Date().toISOString();
      const targetIndex = previousDetail?.messages?.findIndex((message) => message.id === variables.messageId) ?? -1;
      const supersededMessage = targetIndex >= 0
        ? [...(previousDetail?.messages ?? [])]
          .slice(targetIndex)
          .find((message) => message.role === "assistant" && String(message.metadata?.turnId || "").trim())
        : undefined;
      const supersededTurnId = String(supersededMessage?.metadata?.turnId || "").trim() || undefined;
      setActiveTurnLayersBySession((current) =>
        setActiveTurnLayerForSession(
          current,
          variables.sessionId,
          createOptimisticActiveTurnLayer({
            sessionId: variables.sessionId,
            turnId: optimisticTurnIdForSubmission("edit", variables.sessionId, createdAt),
            clientSubmissionId: variables.clientSubmissionId,
            updatedAt: createdAt,
          }),
        )
      );
      // Immediately hide the superseded tail; the edit marker blocks stale
      // detail/SSE/paint merges until the authoritative branch arrives.
      queryClient.setQueryData<SessionDetail>(sessionKey, (detailState) =>
        applyOptimisticEditResubmit(detailState, {
          messageId: variables.messageId,
          content: variables.content,
          clientSubmissionId: variables.clientSubmissionId,
          supersededTurnId,
        }),
      );
      updateSessionSummaryCaches(queryClient, (sessions) =>
        markSessionSummaryRunning(sessions, variables.sessionId),
      );
      return { previousDetail, telemetry };
    },
    onSuccess: (nextDetail, variables, context) => {
      context?.telemetry?.succeeded({
        sessionId: variables.sessionId,
        messageId: variables.messageId,
        turnId: latestUserTurnId(nextDetail),
      });
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      setSessionDrafts((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      setSessionImageAttachments((current) => clearSessionImageAttachments(current, variables.sessionId));
      setSessionReferenceAttachments((current) => clearSessionReferenceAttachments(current, variables.sessionId));
      setSessionEditTargets((current) => {
        const { [variables.sessionId]: _removed, ...remaining } = current;
        return remaining;
      });
      syncSessionDetail(nextDetail);
      const acceptedTurnId = latestUserTurnId(nextDetail);
      setActiveTurnLayersBySession((current) => {
        if (!acceptedTurnId || !isBusyPhase(nextDetail.currentPhase || nextDetail.status)) {
          return setActiveTurnLayerForSession(current, variables.sessionId, undefined);
        }
        return setActiveTurnLayerForSession(
          current,
          variables.sessionId,
          createOptimisticActiveTurnLayer({
            sessionId: variables.sessionId,
            turnId: acceptedTurnId,
            clientSubmissionId: variables.clientSubmissionId,
            updatedAt: nextDetail.updatedAt,
          }),
        );
      });
      void chatWorkspaceCache.afterSessionChanged();
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, {
        sessionId: variables.sessionId,
        messageId: variables.messageId,
      });
      const previousDetail = context && typeof context === "object" && "previousDetail" in context
        ? (context as { previousDetail?: SessionDetail }).previousDetail
        : undefined;
      const currentDetail = queryClient.getQueryData<SessionDetail>(queryKeys.session(variables.sessionId));
      const ownsPendingEdit = currentDetail?.editResubmitProtection?.clientSubmissionId === variables.clientSubmissionId;
      if (previousDetail && ownsPendingEdit) {
        queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), {
          ...previousDetail,
          editResubmitProtection: null,
        });
      } else if (!currentDetail || ownsPendingEdit) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.session(variables.sessionId), exact: true });
      }
      setActiveTurnLayersBySession((current) =>
        setActiveTurnLayerForSession(current, variables.sessionId, undefined)
      );
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("editResubmitFailed")),
      }));
      void chatWorkspaceCache.afterDirectTurnFailed(variables.sessionId);
    },
  });

  const regenerateMutation = useMutation({
    mutationFn: async (
      {
        sessionId,
        messageId,
        baseMessageId,
        clientSubmissionId,
        mentalModelEnabled,
        runtimeStatusEnabled,
        turnStatusTail,
      }: RegenerateVariables,
    ) =>
      regenerateSessionMessage(sessionId, {
        messageId,
        ...(baseMessageId ? { baseMessageId } : {}),
        clientSubmissionId,
        mentalModelEnabled,
        runtimeStatusEnabled,
        turnStatusTail: turnStatusTail ?? loadTurnStatusTailConfig(sessionId),
      }),
    onMutate: async (variables) => {
      const telemetry = startUserAction("session_regenerate", {
        sessionId: variables.sessionId,
        messageId: variables.messageId,
        clientSubmissionId: variables.clientSubmissionId,
      });
      const sessionKey = queryKeys.session(variables.sessionId);
      await queryClient.cancelQueries({ queryKey: sessionKey, exact: true });
      const previousDetail = queryClient.getQueryData<SessionDetail>(sessionKey);
      const createdAt = new Date().toISOString();
      setActiveTurnLayersBySession((current) =>
        setActiveTurnLayerForSession(
          current,
          variables.sessionId,
          createOptimisticActiveTurnLayer({
            sessionId: variables.sessionId,
            turnId: optimisticTurnIdForSubmission("edit", variables.sessionId, createdAt),
            clientSubmissionId: variables.clientSubmissionId,
            updatedAt: createdAt,
          }),
        )
      );
      // Drop the stale assistant output immediately; snapshot for rollback.
      queryClient.setQueryData<SessionDetail>(sessionKey, (detailState) =>
        applyOptimisticRegenerate(detailState, { messageId: variables.messageId }),
      );
      updateSessionSummaryCaches(queryClient, (sessions) =>
        markSessionSummaryRunning(sessions, variables.sessionId),
      );
      return { previousDetail, telemetry };
    },
    onSuccess: (nextDetail, variables, context) => {
      context?.telemetry?.succeeded({
        sessionId: variables.sessionId,
        messageId: variables.messageId,
        turnId: latestUserTurnId(nextDetail),
      });
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      syncSessionDetail(nextDetail);
      const acceptedTurnId = latestUserTurnId(nextDetail);
      setActiveTurnLayersBySession((current) => {
        if (!acceptedTurnId || !isBusyPhase(nextDetail.currentPhase || nextDetail.status)) {
          return setActiveTurnLayerForSession(current, variables.sessionId, undefined);
        }
        return setActiveTurnLayerForSession(
          current,
          variables.sessionId,
          createOptimisticActiveTurnLayer({
            sessionId: variables.sessionId,
            turnId: acceptedTurnId,
            clientSubmissionId: variables.clientSubmissionId,
            updatedAt: nextDetail.updatedAt,
          }),
        );
      });
      void chatWorkspaceCache.afterSessionChanged();
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, {
        sessionId: variables.sessionId,
        messageId: variables.messageId,
      });
      const previousDetail = context && typeof context === "object" && "previousDetail" in context
        ? (context as { previousDetail?: SessionDetail }).previousDetail
        : undefined;
      if (previousDetail) {
        queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), previousDetail);
      } else {
        void queryClient.invalidateQueries({ queryKey: queryKeys.session(variables.sessionId), exact: true });
      }
      setActiveTurnLayersBySession((current) =>
        setActiveTurnLayerForSession(current, variables.sessionId, undefined)
      );
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("regenerateFailed")),
      }));
      void chatWorkspaceCache.afterDirectTurnFailed(variables.sessionId);
    },
  });

  const switchHeadMutation = useMutation({
    mutationFn: async ({ sessionId, nodeId }: SwitchHeadVariables) =>
      switchSessionHead(sessionId, { nodeId }),
    onMutate: async (variables) => {
      const telemetry = startUserAction("session_switch_head", {
        sessionId: variables.sessionId,
        nodeId: variables.nodeId,
      });
      const sessionKey = queryKeys.session(variables.sessionId);
      await queryClient.cancelQueries({ queryKey: sessionKey, exact: true });
      const previousDetail = queryClient.getQueryData<SessionDetail>(sessionKey);
      return { previousDetail, telemetry };
    },
    onSuccess: (nextDetail, variables, context) => {
      context?.telemetry?.succeeded({
        sessionId: variables.sessionId,
        nodeId: variables.nodeId,
      });
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      syncSessionDetail(nextDetail);
      void chatWorkspaceCache.afterSessionChanged();
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, {
        sessionId: variables.sessionId,
        nodeId: variables.nodeId,
      });
      const previousDetail = context && typeof context === "object" && "previousDetail" in context
        ? (context as { previousDetail?: SessionDetail }).previousDetail
        : undefined;
      if (previousDetail) {
        queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), previousDetail);
      } else {
        void queryClient.invalidateQueries({ queryKey: queryKeys.session(variables.sessionId), exact: true });
      }
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("switchBranchFailed")),
      }));
    },
  });

  const stopTurnMutation = useMutation({
    mutationFn: async ({ sessionId, turnId }: StopTurnVariables) =>
      stopSessionTurn(sessionId, turnId),
    onMutate: async (variables: StopTurnVariables) => {
      const telemetry = startUserAction("session_turn_stop", {
        sessionId: variables.sessionId,
        turnId: variables.turnId,
      });
      // Abort congested in-flight queries without waiting for them: the stop
      // POST must not queue behind a slow detail/list fetch.
      void cancelCongestedQueriesForSessionStop(queryClient, variables.sessionId);
      // Enter the stopping phase immediately; the POST only acknowledges the
      // request and the worker publishes the authoritative stopped snapshot.
      // A deferred stop already patched the UI at click time, so it re-applies
      // the same intent while restoring the real pre-stop detail on failure.
      const target = resolveStopOptimisticTarget(
        variables.deferredStop,
        queryClient.getQueryData<SessionDetail>(queryKeys.session(variables.sessionId)),
        new Date().toISOString(),
      );
      const previousDetail = target.previousDetail;
      const stoppingAt = target.stoppingAt;
      const optimisticDetail = markSessionDetailStopping(previousDetail, { requestedAt: stoppingAt });
      if (optimisticDetail) {
        queryClient.setQueryData(queryKeys.session(variables.sessionId), optimisticDetail);
      }
      // The shell active-work indicator is driven by the runtime summary poll;
      // patch it now so a stopped turn leaves the list at click time.
      const runtimeKey = queryKeys.runtimeSummary();
      const previousRuntime = queryClient.getQueryData<RuntimeSummary>(runtimeKey);
      if (previousRuntime) {
        const nextRuntime = removeChatTurnFromRuntimeSummary(previousRuntime, {
          sessionId: variables.sessionId,
          turnId: variables.turnId,
        });
        if (nextRuntime && nextRuntime !== previousRuntime) {
          queryClient.setQueryData(runtimeKey, nextRuntime);
        }
      }
      return { telemetry, previousDetail, stoppingAt, previousRuntime };
    },
    onSuccess: (nextDetail, variables, context) => {
      context?.telemetry?.succeeded({
        sessionId: variables.sessionId,
        turnId: variables.turnId,
      });
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      syncSessionDetail(nextDetail);
      void chatWorkspaceCache.afterSessionChanged();
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, {
        sessionId: variables.sessionId,
        turnId: variables.turnId,
      });
      // Clear the optimistic stopping patch only when nothing newer replaced it.
      if (context?.stoppingAt) {
        queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), (current) => {
          if (!current) {
            return current;
          }
          return clearSessionDetailStopping(current, {
            requestedAt: context.stoppingAt,
            previous: context.previousDetail,
          });
        });
      }
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("stopFailed")),
      }));
      if (context?.previousRuntime) {
        queryClient.setQueryData(queryKeys.runtimeSummary(), context.previousRuntime);
      }
      void chatWorkspaceCache.afterDirectTurnFailed(variables.sessionId);
    },
  });

  const sessionGuidanceMutation = useMutation({
    mutationFn: async (
      {
        sessionId,
        content,
        mode,
      }: {
        sessionId: string;
        content: string;
        mode: SessionGuidanceMode;
      },
    ) =>
      submitSessionGuidance(sessionId, { content, mode }),
    onMutate: (variables) => ({
      telemetry: startUserAction("session_guidance_submit", {
        sessionId: variables.sessionId,
        mode: variables.mode,
        contentLength: variables.content.length,
      }),
    }),
    onSuccess: (nextDetail, variables, context) => {
      context?.telemetry?.succeeded({
        sessionId: variables.sessionId,
        mode: variables.mode,
      });
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      setSessionDrafts((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      syncSessionDetail(nextDetail);
      void chatWorkspaceCache.afterSessionChanged({ sessionId: variables.sessionId });
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, {
        sessionId: variables.sessionId,
        mode: variables.mode,
      });
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("guidanceFailed")),
      }));
      void chatWorkspaceCache.refreshSessionRuntime(variables.sessionId);
    },
  });

  return {
    submitTurnMutation,
    editResubmitMutation,
    regenerateMutation,
    switchHeadMutation,
    stopTurnMutation,
    sessionGuidanceMutation,
  };
}

export type UseChatComposerSubmitActionsOptions = ChatComposerTurnMutations & {
  queryClient: QueryClient;
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
};

export type UseChatComposerSubmitActionsResult = {
  handleComposerChange: (value: string) => void;
  handleMentalModelEnabledChange: (enabled: boolean) => void;
  handleRuntimeStatusEnabledChange: (enabled: boolean) => void;
  handleAddComposerAttachments: (files: FileList | File[]) => void;
  handleRemoveComposerAttachment: (attachmentId: string) => void;
  handleAddComposerReference: (reference: SessionReferenceAttachment) => void;
  handleRemoveComposerReference: (referenceId: string) => void;
  handleSubmitTurn: () => void;
  handleStopTurn: () => void;
  handleSubmitGuidance: (mode: SessionGuidanceMode) => void;
  handleFollowupQueueUpdate: (id: string, text: string) => void;
  handleFollowupQueueRemove: (id: string) => void;
  handleFollowupQueueMove: (fromIndex: number, toIndex: number) => void;
  handleFollowupQueueSteer: (id: string) => void;
  handleEditUserMessage: (message: ConversationMessage) => void;
  handleCancelEditMessage: () => void;
  handleRegenerateAssistantMessage: (message: ConversationMessage) => void;
  handleRetryFailedTurn: () => void;
  handleSwitchMessageVersion: (message: ConversationMessage, targetNodeId: string) => void;
};

/**
 * Composer submit/stop/guidance/edit handlers. Call after composerDisabled is derived.
 */
export function useChatComposerSubmitActions({
  queryClient,
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
}: UseChatComposerSubmitActionsOptions): UseChatComposerSubmitActionsResult {
  const pendingStopAfterAcceptRef = useRef<Map<string, DeferredStopIntent>>(new Map());
  // Uploading attachments happens before React Query creates the submit/edit
  // mutation. Keep the same submission identity visible to Stop during that
  // gap so a stop requested before upload completion can still match the late
  // mutation acceptance, even after switching sessions.
  const pendingUploadSubmissionRef = useRef<Map<string, string>>(new Map());
  const restorePendingStopAfterUploadFailure = useCallback((sessionId: string) => {
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
  }, [queryClient]);
  const attachmentSnapshotRef = useRef<{ sessionId: string | null | undefined; attachments: ComposerImageAttachment[] }>({
    sessionId: activeSessionId,
    attachments: activeImageAttachments,
  });
  const lastAttachmentInputRef = useRef(activeImageAttachments);
  if (attachmentSnapshotRef.current.sessionId !== activeSessionId || lastAttachmentInputRef.current !== activeImageAttachments) {
    lastAttachmentInputRef.current = activeImageAttachments;
    attachmentSnapshotRef.current = { sessionId: activeSessionId, attachments: activeImageAttachments };
  }

  const handleComposerChange = useCallback((value: string) => {
    if (!activeSessionId) {
      return;
    }
    setSessionDrafts((current) => ({
      ...current,
      [activeSessionId]: value,
    }));
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

  const handleAddComposerAttachments = useCallback((files: FileList | File[]) => {
    if (!activeSessionId) {
      return;
    }
    const { accepted: classifiedAccepted, rejected } = classifyComposerFiles(files);
    if (!classifiedAccepted.length && !rejected.length) {
      return;
    }
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
        .forEach((attachment) => URL.revokeObjectURL(attachment.previewUrl));
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
      capacityRejected.forEach((attachment) => URL.revokeObjectURL(attachment.previewUrl));
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
    lang,
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
    const nextAttachments = attachmentSnapshot.filter((attachment) => attachment.id !== attachmentId);
    if (nextAttachments.length === attachmentSnapshot.length) {
      return;
    }
    const removed = attachmentSnapshot.find((attachment) => attachment.id === attachmentId);
    if (removed) {
      URL.revokeObjectURL(removed.previewUrl);
    }
    attachmentSnapshotRef.current = { sessionId: activeSessionId, attachments: nextAttachments };
    setSessionImageAttachments((current) => ({
      ...current,
      [activeSessionId]: nextAttachments,
    }));
  }, [activeImageAttachments, activeSessionId, setSessionImageAttachments]);

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
  ) => {
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
    imageUploadInFlightRef.current[sessionId] = true;
    pendingUploadSubmissionRef.current.set(sessionId, clientSubmissionId);
    setSessionImageUploadPending((current) => ({
      ...current,
      [sessionId]: true,
    }));
    setSessionDrafts((current) => clearSessionDraftForSubmittedTurn(current, sessionId));
    setSessionComposerErrors((current) => ({
      ...current,
      [sessionId]: "",
    }));
    if (!queuedBehindActiveTurn && (content || references.length)) {
      queryClient.setQueryData<SessionDetail>(queryKeys.session(sessionId), (detailState) =>
        markSessionDetailRunning(appendOptimisticUserMessage(detailState, { sessionId, content, references, clientSubmissionId })),
      );
    }
    try {
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
      const uploaded = await Promise.all(attachments.map((attachment) => uploadSessionImageAttachment(sessionId, attachment)));
      if (attachments.length) {
        postSubmitTelemetry(
          "browser.chat_submit.upload_succeeded",
          "Direct chat submit image upload succeeded.",
          sessionId,
          {
            content,
            attachmentCount: attachments.length,
            uploadedAttachmentCount: uploaded.length,
            referenceCount: references.length,
            mentalModelEnabled,
            clientSubmissionId,
          },
        );
      }
      postSubmitTelemetry(
        "browser.chat_submit.submit_mutate_requested",
        "Direct chat submit mutation was requested.",
        sessionId,
        {
          content,
          attachmentCount: attachments.length,
          uploadedAttachmentCount: uploaded.length,
          referenceCount: references.length,
          mentalModelEnabled,
          clientSubmissionId,
        },
      );
      submitTurnMutation.mutate({
        sessionId,
        clientSubmissionId,
        content,
        mentalModelEnabled,
        runtimeStatusEnabled,
        turnStatusTail: loadTurnStatusTailConfig(sessionId),
        attachmentIds: uploaded.map((attachment) => attachment.artifactId).filter(Boolean),
        references,
        requestStartedAtMs: chatStreamPerformanceNowMs(),
        queuedBehindActiveTurn,
      });
    } catch (error) {
      postSubmitTelemetry(
        "browser.chat_submit.upload_failed",
        "Direct chat submit image upload failed before message POST.",
        sessionId,
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
        [sessionId]: describeError(error, lang === "zh" ? "图片上传失败" : "Image upload failed"),
      }));
      if (content || references.length) {
        queryClient.setQueryData<SessionDetail>(queryKeys.session(sessionId), (detailState) =>
          removeOptimisticUserMessage(detailState, { sessionId, content, references, clientSubmissionId }),
        );
        setSessionDrafts((current) => restoreSubmittedDraftIfComposerStillEmpty(current, sessionId, content));
      }
      restorePendingStopAfterUploadFailure(sessionId);
    } finally {
      if (pendingUploadSubmissionRef.current.get(sessionId) === clientSubmissionId) {
        pendingUploadSubmissionRef.current.delete(sessionId);
      }
      imageUploadInFlightRef.current[sessionId] = false;
      setSessionImageUploadPending((current) => ({
        ...current,
        [sessionId]: false,
      }));
    }
  }, [
    describeError,
    imageUploadInFlightRef,
    lang,
    queryClient,
    restorePendingStopAfterUploadFailure,
    setSessionComposerErrors,
    setSessionDrafts,
    setSessionImageUploadPending,
    submitTurnMutation,
  ]);

  const syncQueuedTurnsIntoDetail = useCallback((sessionId: string, rows: SessionQueuedTurn[]) => {
    queryClient.setQueryData<SessionDetail>(queryKeys.session(sessionId), (detailState) =>
      detailState ? { ...detailState, queuedTurns: rows } : detailState,
    );
  }, [queryClient]);

  const reportQueuedTurnError = useCallback((sessionId: string, error: unknown, fallback: string) => {
    setSessionComposerErrors((current) => ({
      ...current,
      [sessionId]: describeError(error, fallback),
    }));
  }, [describeError, setSessionComposerErrors]);

  const handleFollowupQueueUpdate = useCallback((id: string, text: string) => {
    const sessionId = activeSessionId;
    const content = text.trim();
    if (!sessionId || !content) {
      return;
    }
    void updateSessionQueuedTurn(sessionId, id, { content })
      .then((rows) => syncQueuedTurnsIntoDetail(sessionId, rows))
      .catch((error) => reportQueuedTurnError(
        sessionId,
        error,
        lang === "zh" ? "修改排队消息失败" : "Failed to update the queued message",
      ));
  }, [activeSessionId, lang, reportQueuedTurnError, syncQueuedTurnsIntoDetail]);

  const handleFollowupQueueRemove = useCallback((id: string) => {
    const sessionId = activeSessionId;
    if (!sessionId) {
      return;
    }
    void removeSessionQueuedTurn(sessionId, id)
      .then((rows) => syncQueuedTurnsIntoDetail(sessionId, rows))
      .catch((error) => reportQueuedTurnError(
        sessionId,
        error,
        lang === "zh" ? "撤回排队消息失败" : "Failed to withdraw the queued message",
      ));
  }, [activeSessionId, lang, reportQueuedTurnError, syncQueuedTurnsIntoDetail]);

  // Steering sends one queued item into the running turn as safe guidance and
  // then withdraws it from the server queue; items carrying attachments or
  // references stay queued because guidance cannot carry them.
  const handleFollowupQueueSteer = useCallback((id: string) => {
    const sessionId = activeSessionId;
    if (!sessionId) {
      return;
    }
    const item = (sessionFollowupQueues[sessionId] ?? []).find((entry) => entry.id === id);
    if (!item) {
      return;
    }
    if (item.canSteer === false) {
      setSessionComposerErrors((current) => ({
        ...current,
        [sessionId]: lang === "zh"
          ? "这条排队消息带图片或会话引用，无法立即引导；本轮结束后会自动发送。"
          : "This queued message carries images or session references, so it cannot steer the running turn. It sends automatically after the turn ends.",
      }));
      return;
    }
    void (async () => {
      try {
        await sessionGuidanceMutation.mutateAsync({ sessionId, content: item.text, mode: "safe" });
        const rows = await removeSessionQueuedTurn(sessionId, id);
        syncQueuedTurnsIntoDetail(sessionId, rows);
      } catch {
        // The item stays queued; the guidance mutation already surfaced its error.
      }
    })();
  }, [
    activeSessionId,
    lang,
    sessionFollowupQueues,
    sessionGuidanceMutation,
    setSessionComposerErrors,
    syncQueuedTurnsIntoDetail,
  ]);

  const handleFollowupQueueMove = useCallback((fromIndex: number, toIndex: number) => {
    const sessionId = activeSessionId;
    const rows = detail?.queuedTurns ?? [];
    const from = rows[fromIndex];
    const target = rows[toIndex];
    if (!sessionId || fromIndex === toIndex || !from || !target) {
      return;
    }
    void updateSessionQueuedTurn(sessionId, from.id, { position: target.position })
      .then((next) => syncQueuedTurnsIntoDetail(sessionId, next))
      .catch((error) => reportQueuedTurnError(
        sessionId,
        error,
        lang === "zh" ? "调整排队顺序失败" : "Failed to reorder the queue",
      ));
  }, [activeSessionId, detail?.queuedTurns, lang, reportQueuedTurnError, syncQueuedTurnsIntoDetail]);

  const handleSubmitTurn = useCallback(() => {
    if (!activeSessionId) {
      return;
    }
    // Optimistic create shells are local-only until the server id is rebased.
    if (isTempSessionId(activeSessionId)) {
      setSessionComposerErrors((current) => ({
        ...current,
        [activeSessionId]: lang === "zh"
          ? "新会话正在创建，请稍候再发送。"
          : "The new session is still being created. Please wait a moment before sending.",
      }));
      return;
    }
    if (sessionBusy && !resolvedEditTarget) {
      const content = activeDraftEffective.trim();
      if (!content) {
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
    if (activeImageAttachments.length && activeAgentImageInputUnsupported) {
      startUserAction("session_message_submit", {
        sessionId: activeSessionId,
        clientSubmissionId,
        attachmentCount: activeImageAttachments.length,
      }).blocked("image_input_unsupported", {
        imageInputModelId: activeImageInputModelId,
      });
      postSubmitTelemetry(
        "browser.chat_submit.blocked",
        "Direct chat submit image upload was blocked because the active Agent model does not support image input.",
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
      void (async () => {
        if (editAttachments.length && imageUploadInFlightRef.current[activeSessionId]) {
          return;
        }
        let attachmentIds: string[] = [];
        if (editAttachments.length) {
          imageUploadInFlightRef.current[activeSessionId] = true;
          pendingUploadSubmissionRef.current.set(activeSessionId, clientSubmissionId);
          setSessionImageUploadPending((current) => ({
            ...current,
            [activeSessionId]: true,
          }));
          try {
            const uploaded = await Promise.all(
              editAttachments.map((attachment) => uploadSessionImageAttachment(activeSessionId, attachment)),
            );
            attachmentIds = uploaded.map((attachment) => attachment.artifactId).filter(Boolean);
          } catch (error) {
            setSessionComposerErrors((current) => ({
              ...current,
              [activeSessionId]: describeError(error, lang === "zh" ? "图片上传失败" : "Image upload failed"),
            }));
            restorePendingStopAfterUploadFailure(activeSessionId);
            return;
          } finally {
            if (pendingUploadSubmissionRef.current.get(activeSessionId) === clientSubmissionId) {
              pendingUploadSubmissionRef.current.delete(activeSessionId);
            }
            imageUploadInFlightRef.current[activeSessionId] = false;
            setSessionImageUploadPending((current) => ({
              ...current,
              [activeSessionId]: false,
            }));
          }
        }
        editResubmitMutation.mutate({
          sessionId: activeSessionId,
          messageId: editTarget.messageId,
          ...(editTarget.nodeId ? { baseMessageId: editTarget.nodeId } : {}),
          clientSubmissionId,
          content,
          attachmentIds,
          mentalModelEnabled: mentalModelEnabledForNextTurn,
          runtimeStatusEnabled: runtimeStatusEnabledForNextTurn,
          turnStatusTail: loadTurnStatusTailConfig(activeSessionId),
        });
      })();
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
    );
  }, [
    activeAgentImageInputUnsupported,
    activeDraftEffective,
    activeImageAttachments,
    activeImageInputModelId,
    activePhase,
    activeReferenceAttachments,
    activeSessionId,
    composerDisabled,
    companionAgentId,
    describeError,
    editResubmitMutation,
    imageUploadInFlightRef,
    lang,
    mentalModelEnabledForNextTurn,
    runtimeStatusEnabledForNextTurn,
    restorePendingStopAfterUploadFailure,
    resolvedEditTarget,
    sessionBusy,
    sessionFollowupQueues,
    sessionGuidanceMutation,
    sessionStopping,
    setSessionComposerErrors,
    setSessionDrafts,
    setSessionImageUploadPending,
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
    setSessionImageAttachments((current) => clearSessionImageAttachments(current, activeSessionId));
    setSessionReferenceAttachments((current) => clearSessionReferenceAttachments(current, activeSessionId));
  }, [
    activeSessionId,
    setSessionDrafts,
    setSessionEditTargets,
    setSessionImageAttachments,
    setSessionReferenceAttachments,
  ]);

  const handleRegenerateAssistantMessage = useCallback((message: ConversationMessage) => {
    if (message.role !== "assistant" || !activeSessionId || sessionBusy) {
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
      if (messages[index].role === "user") {
        userMessage = messages[index];
        break;
      }
    }
    if (!userMessage || userMessage.role !== "user") {
      return;
    }
    // Branch from the clicked assistant answer when it carries a node id;
    // otherwise fall back to the legacy latest-only regenerate.
    const baseMessageId = String(message.nodeId || userMessage.nodeId || "").trim();
    regenerateMutation.mutate({
      sessionId: activeSessionId,
      messageId: userMessage.id,
      ...(baseMessageId ? { baseMessageId } : {}),
      clientSubmissionId: createClientSubmissionId(activeSessionId),
      content: String(userMessage.content || ""),
      mentalModelEnabled: mentalModelEnabledForNextTurn,
      runtimeStatusEnabled: runtimeStatusEnabledForNextTurn,
      turnStatusTail: loadTurnStatusTailConfig(activeSessionId),
    });
  }, [
    activeSessionId,
    detail,
    mentalModelEnabledForNextTurn,
    regenerateMutation,
    runtimeStatusEnabledForNextTurn,
    sessionBusy,
  ]);

  // A failed turn has no assistant answer to branch from: retry reruns the
  // latest user message through the same regenerate pipeline as the retry trail.
  const handleRetryFailedTurn = useCallback(() => {
    if (!activeSessionId || sessionBusy) {
      return;
    }
    const messages = detail?.messages ?? [];
    let userMessage: ConversationMessage | undefined;
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      if (messages[index].role === "user") {
        userMessage = messages[index];
        break;
      }
    }
    if (!userMessage || userMessage.role !== "user") {
      return;
    }
    const baseMessageId = String(userMessage.nodeId || "").trim();
    regenerateMutation.mutate({
      sessionId: activeSessionId,
      messageId: userMessage.id,
      ...(baseMessageId ? { baseMessageId } : {}),
      clientSubmissionId: createClientSubmissionId(activeSessionId),
      content: String(userMessage.content || ""),
      mentalModelEnabled: mentalModelEnabledForNextTurn,
      runtimeStatusEnabled: runtimeStatusEnabledForNextTurn,
      turnStatusTail: loadTurnStatusTailConfig(activeSessionId),
    });
  }, [
    activeSessionId,
    detail,
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
    queryClient,
    sessionBusy,
    sessionStopping,
    stopTurnMutation,
    submitTurnMutation.isPending,
    submitTurnMutation.variables?.sessionId,
  ]);

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
      } | undefined;
      const sessionId = typeof variables?.sessionId === "string" ? variables.sessionId : "";
      const clientSubmissionId = typeof variables?.clientSubmissionId === "string"
        ? variables.clientSubmissionId
        : "";
      if (!sessionId || !clientSubmissionId) return;
      const pendingStop = pendingStopAfterAcceptRef.current.get(sessionId);
      if (!pendingStop || pendingStop.clientSubmissionId !== clientSubmissionId) return;

      if (mutation.state.status === "error") {
        pendingStopAfterAcceptRef.current.delete(sessionId);
        return;
      }
      if (mutation.state.status !== "success") return;

      const data = mutation.state.data as {
        sessionId?: unknown;
        turnId?: unknown;
      } | SessionDetail | undefined;
      const acceptedTurnId = variables?.messageId
        ? resolveSessionStopTurnId(data as SessionDetail | undefined, "")
        : data && typeof data === "object" && "turnId" in data
          ? String(data.turnId || "").trim()
          : "";
      if (!acceptedTurnId) return;

      if (stopTurnMutation.isPending) {
        pendingStop.acceptedTurnId = acceptedTurnId;
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
    });
    return unsubscribe;
  }, [queryClient, stopTurnMutation]);

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
      const acceptedTurnId = pendingStop.acceptedTurnId || (submitMatches
        ? String(acceptedSubmit?.turnId || "").trim()
        : editMatches
          ? resolveSessionStopTurnId(acceptedEdit, "")
          : "");
      if (acceptedTurnId && !stopTurnMutation.isPending) {
        pendingStopAfterAcceptRef.current.delete(sessionId);
        stopTurnMutation.mutate({
          sessionId,
          turnId: acceptedTurnId,
          deferredStop: {
            previousDetail: pendingStop.previousDetail,
            stoppingAt: pendingStop.stoppingAt,
          },
        });
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
        pendingStopAfterAcceptRef.current.delete(sessionId);
      }
    }

    if (!activeSessionId) return;
    const pendingStop = pendingStopAfterAcceptRef.current.get(activeSessionId);
    if (!pendingStop || pendingStop.clientSubmissionId) return;
    const submitPending = Boolean(
      (submitTurnMutation.isPending && submitTurnMutation.variables?.sessionId === activeSessionId)
      || (editResubmitMutation.isPending && editResubmitMutation.variables?.sessionId === activeSessionId)
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
    sessionBusy,
    stopTurnMutation,
    submitTurnMutation.isPending,
    submitTurnMutation.data,
    submitTurnMutation.error,
    submitTurnMutation.variables,
    editResubmitMutation.data,
    editResubmitMutation.error,
    editResubmitMutation.variables,
    submitTurnMutation.variables?.sessionId,
  ]);

  const handleSubmitGuidance = useCallback((mode: SessionGuidanceMode) => {
    if (!activeSessionId || !sessionBusy || sessionStopping) {
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
  }, [activeDraftEffective, activeSessionId, sessionBusy, sessionGuidanceMutation, sessionStopping]);

  // Deferred stop intents remain keyed by session while the user moves between
  // sessions. A late submit acceptance is matched by submission identity and
  // stopped immediately, without being applied to a newer turn.

  return {
    handleComposerChange,
    handleMentalModelEnabledChange,
    handleRuntimeStatusEnabledChange,
    handleAddComposerAttachments,
    handleRemoveComposerAttachment,
    handleAddComposerReference,
    handleRemoveComposerReference,
    handleSubmitTurn,
    handleStopTurn,
    handleSubmitGuidance,
    handleFollowupQueueUpdate,
    handleFollowupQueueRemove,
    handleFollowupQueueMove,
    handleFollowupQueueSteer,
    handleEditUserMessage,
    handleCancelEditMessage,
    handleRegenerateAssistantMessage,
    handleRetryFailedTurn,
    handleSwitchMessageVersion,
  };
}
