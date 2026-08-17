import { useMutation, type QueryClient, type UseMutationResult } from "@tanstack/react-query";
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
  stopSessionTurn,
  submitSessionGuidance,
  submitSessionMessage,
} from "../../api/chat";
import { queryKeys } from "../../api/queryKeys";
import type {
  ConversationMessage,
  SessionDetail,
  SessionGuidanceMode,
  SessionReferenceAttachment,
  SessionTurnAcceptedResponse,
} from "../../api/types";
import type { TranslationKey } from "../../i18n/dictionary";
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
  createClientSubmissionId,
  markOptimisticUserMessageAccepted,
  markSessionDetailRunning,
  markSessionSummaryRunning,
  removeOptimisticUserMessage,
} from "../chatSessionState";
import { updateSessionSummaryCaches } from "../chatSessionIndexQuery";
import type { createChatWorkspaceCache } from "../chatWorkspaceCache";
import {
  chatStreamPerformanceNowMs,
  isBusyPhase,
} from "./chatCodingRouteViewModel";
import {
  MAX_COMPOSER_IMAGE_ATTACHMENTS,
  classifyComposerImageFiles,
  clearSessionDraftForSubmittedTurn,
  clearSessionImageAttachments,
  clearSessionReferenceAttachments,
  encodeUtf8Base64,
  mergeComposerImageAttachments,
  optimisticTurnIdForSubmission,
  removeSessionImageAttachment,
  resolveComposerSubmitGuard,
  restoreSubmittedDraftIfComposerStillEmpty,
  sessionReferenceId,
  uploadSessionImageAttachment,
  writeStoredMentalModelToggle,
  writeStoredRuntimeStatusToggle,
  type ComposerImageAttachment,
} from "./chatComposerSubmitModel";
import { loadTurnStatusTailConfig } from "./turnStatusTailModel";
import {
  appendComposerQueueItem,
  moveComposerQueueItem,
  removeComposerQueueItem,
  resolveComposerQueueEnter,
  updateComposerQueueItem,
  type ComposerQueueItem,
} from "../../components/conversation/composerFollowupQueueModel";
import { postSubmitTelemetry } from "./chatSubmitTelemetry";
import { startUserAction } from "../../app/userActionTelemetry";
import { resolveSessionStopTurnId, cancelCongestedQueriesForSessionStop } from "./chatStopTurnModel";

type ChatEditTarget = { messageId: string; original: string };
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
};

export type EditResubmitVariables = {
  sessionId: string;
  messageId: string;
  clientSubmissionId: string;
  content: string;
  mentalModelEnabled: boolean;
  runtimeStatusEnabled: boolean;
  turnStatusTail?: ReturnType<typeof loadTurnStatusTailConfig>;
  attachmentIds?: string[];
};

export type ChatComposerTurnMutations = {
  submitTurnMutation: UseMutationResult<SessionTurnAcceptedResponse, Error, SubmitTurnVariables, unknown>;
  editResubmitMutation: UseMutationResult<SessionDetail, Error, EditResubmitVariables, unknown>;
  stopTurnMutation: UseMutationResult<SessionDetail, Error, { sessionId: string; turnId: string }, unknown>;
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
}: UseChatComposerTurnMutationsOptions): ChatComposerTurnMutations {
  const submitTurnMutation = useMutation({
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
      return submitSessionMessage(sessionId, {
        content,
        clientSubmissionId,
        contentUtf8Base64: encodeUtf8Base64(content),
        attachmentIds: attachmentIds ?? [],
        references: references ?? [],
        mentalModelEnabled,
        runtimeStatusEnabled,
        turnStatusTail: resolvedTail,
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
      queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), (detailState) =>
        markSessionDetailRunning(appendOptimisticUserMessage(detailState, variables)),
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
        setActiveTurnLayerForSession(
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
      setActiveTurnLayersBySession((current) =>
        setActiveTurnLayerForSession(current, variables.sessionId, undefined)
      );
      setSessionDrafts((current) => restoreSubmittedDraftIfComposerStillEmpty(current, variables.sessionId, variables.content));
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("submitFailed")),
      }));
      void chatWorkspaceCache.afterDirectTurnFailed(variables.sessionId);
    },
  });

  const editResubmitMutation = useMutation({
    mutationFn: async (
      {
        sessionId,
        messageId,
        clientSubmissionId,
        content,
        mentalModelEnabled,
        runtimeStatusEnabled,
        turnStatusTail,
      }: EditResubmitVariables,
    ) =>
      editResubmitSessionMessage(sessionId, {
        messageId,
        clientSubmissionId,
        content,
        contentUtf8Base64: encodeUtf8Base64(content),
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
      // Immediate truncate + rewrite (ChatGPT/Claude edit UX); snapshot for rollback.
      queryClient.setQueryData<SessionDetail>(sessionKey, (detailState) =>
        applyOptimisticEditResubmit(detailState, {
          messageId: variables.messageId,
          content: variables.content,
          clientSubmissionId: variables.clientSubmissionId,
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
        [variables.sessionId]: describeError(error, t("editResubmitFailed")),
      }));
      void chatWorkspaceCache.afterDirectTurnFailed(variables.sessionId);
    },
  });

  const stopTurnMutation = useMutation({
    mutationFn: async ({ sessionId, turnId }: { sessionId: string; turnId: string }) =>
      stopSessionTurn(sessionId, turnId),
    onMutate: async (variables) => {
      const telemetry = startUserAction("session_turn_stop", {
        sessionId: variables.sessionId,
        turnId: variables.turnId,
      });
      await cancelCongestedQueriesForSessionStop(queryClient, variables.sessionId);
      return { telemetry };
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
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("stopFailed")),
      }));
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
  setSessionFollowupQueues: Dispatch<SetStateAction<Record<string, ComposerQueueItem[]>>>;
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
  handleEditUserMessage: (message: ConversationMessage) => void;
  handleCancelEditMessage: () => void;
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
  stopTurnMutation,
  sessionGuidanceMutation,
  setSessionDrafts,
  sessionFollowupQueues,
  setSessionFollowupQueues,
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
  latestUserMessageId,
  activeTurnId,
  detail,
  setMentalModelEnabledForNextTurn,
  setRuntimeStatusEnabledForNextTurn,
}: UseChatComposerSubmitActionsOptions): UseChatComposerSubmitActionsResult {
  const stoppedTurnAutoFlushRef = useRef<{ sessionId: string; turnId: string } | null>(null);
  const pendingStopAfterAcceptRef = useRef("");
  const previousBusyRef = useRef(sessionBusy);
  const previousSessionRef = useRef(activeSessionId);

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
    if (sessionBusy) {
      setSessionComposerErrors((current) => ({
        ...current,
        [activeSessionId]: lang === "zh"
          ? "运行中的排队消息暂不支持图片，请等待当前轮次结束后发送。"
          : "Queued follow-ups do not support images while a turn is running. Send it after the turn ends.",
      }));
      return;
    }
    if (activeAgentImageInputUnsupported) {
      setSessionComposerErrors((current) => ({
        ...current,
        [activeSessionId]: lang === "zh" ? "当前 Agent 模型不支持图片输入。" : "The current Agent model does not support image input.",
      }));
      return;
    }
    const { accepted, rejected } = classifyComposerImageFiles(files);
    if (!accepted.length && !rejected.length) {
      return;
    }
    if (accepted.length) {
      setSessionImageAttachments((current) => {
        const existing = current[activeSessionId] ?? [];
        return {
          ...current,
          [activeSessionId]: mergeComposerImageAttachments(existing, accepted, MAX_COMPOSER_IMAGE_ATTACHMENTS),
        };
      });
    }
    setSessionComposerErrors((current) => ({
      ...current,
      [activeSessionId]: rejected.length
        ? (lang === "zh" ? "部分图片格式或大小不支持。" : "Some images were rejected by type or size.")
        : "",
    }));
  }, [
    activeAgentImageInputUnsupported,
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
    setSessionImageAttachments((current) => removeSessionImageAttachment(current, activeSessionId, attachmentId));
  }, [activeSessionId, setSessionImageAttachments]);

  const handleAddComposerReference = useCallback((reference: SessionReferenceAttachment) => {
    if (!activeSessionId) {
      return;
    }
    if (sessionBusy) {
      setSessionComposerErrors((current) => ({
        ...current,
        [activeSessionId]: lang === "zh"
          ? "运行中的排队消息暂不支持会话引用，请等待当前轮次结束后发送。"
          : "Queued follow-ups do not support session references while a turn is running. Send it after the turn ends.",
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
    activeSessionId,
    lang,
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
    setSessionImageUploadPending((current) => ({
      ...current,
      [sessionId]: true,
    }));
    setSessionDrafts((current) => clearSessionDraftForSubmittedTurn(current, sessionId));
    setSessionComposerErrors((current) => ({
      ...current,
      [sessionId]: "",
    }));
    if (content || references.length) {
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
    } finally {
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
    setSessionComposerErrors,
    setSessionDrafts,
    setSessionImageUploadPending,
    submitTurnMutation,
  ]);

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
      if (sessionStopping) {
        return;
      }
      if (activeImageAttachments.length || activeReferenceAttachments.length) {
        setSessionComposerErrors((current) => ({
          ...current,
          [activeSessionId]: lang === "zh"
            ? "运行中的排队消息仅支持文本，请先移除图片和会话引用。"
            : "Queued follow-ups are text-only while a turn is running. Remove images and session references first.",
        }));
        return;
      }
      const queue = sessionFollowupQueues[activeSessionId] ?? [];
      const action = resolveComposerQueueEnter({
        sessionBusy: true,
        draft: activeDraftEffective,
        queue,
      });
      if (action.type === "enqueue") {
        setSessionFollowupQueues((current) => ({
          ...current,
          [activeSessionId]: appendComposerQueueItem(current[activeSessionId] ?? [], action.text),
        }));
        setSessionDrafts((current) => ({
          ...current,
          [activeSessionId]: "",
        }));
        return;
      }
      if (action.type === "immediate") {
        void (async () => {
          try {
            for (const item of action.items) {
              await sessionGuidanceMutation.mutateAsync({
                sessionId: activeSessionId,
                content: item.text,
                mode: "safe",
              });
              setSessionFollowupQueues((current) => ({
                ...current,
                [activeSessionId]: removeComposerQueueItem(current[activeSessionId] ?? [], item.id),
              }));
            }
          } catch {
            // Successful items were removed one by one. The failed item, later
            // snapshot items, and anything appended concurrently remain queued.
          }
        })();
        return;
      }
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
      editResubmitMutation.mutate({
        sessionId: activeSessionId,
        messageId: resolvedEditTarget.messageId,
        clientSubmissionId,
        content,
        mentalModelEnabled: mentalModelEnabledForNextTurn,
        runtimeStatusEnabled: runtimeStatusEnabledForNextTurn,
        turnStatusTail: loadTurnStatusTailConfig(activeSessionId),
      });
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
    editResubmitMutation,
    lang,
    mentalModelEnabledForNextTurn,
    runtimeStatusEnabledForNextTurn,
    resolvedEditTarget,
    sessionBusy,
    sessionFollowupQueues,
    sessionGuidanceMutation,
    sessionStopping,
    setSessionComposerErrors,
    setSessionDrafts,
    setSessionFollowupQueues,
    submitTurnWithAttachments,
  ]);

  const handleEditUserMessage = useCallback((message: ConversationMessage) => {
    if (message.role !== "user") {
      return;
    }
    if (!activeSessionId || sessionBusy) {
      return;
    }
    if (message.id !== latestUserMessageId) {
      return;
    }
    setSessionEditTargets((current) => ({
      ...current,
      [activeSessionId]: {
        messageId: message.id,
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
    latestUserMessageId,
    sessionBusy,
    setSessionComposerErrors,
    setSessionDrafts,
    setSessionEditTargets,
    setSessionImageAttachments,
    setSessionReferenceAttachments,
  ]);

  useEffect(() => {
    if (!activeSessionId || !detail || !activeEditTarget || activeEditTarget.messageId === latestUserMessageId) {
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
  }, [activeEditTarget, activeSessionId, detail, latestUserMessageId, setSessionDrafts, setSessionEditTargets]);

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

  const handleFollowupQueueUpdate = useCallback((id: string, text: string) => {
    if (!activeSessionId) {
      return;
    }
    setSessionFollowupQueues((current) => ({
      ...current,
      [activeSessionId]: updateComposerQueueItem(current[activeSessionId] ?? [], id, text),
    }));
  }, [activeSessionId, setSessionFollowupQueues]);

  const handleFollowupQueueRemove = useCallback((id: string) => {
    if (!activeSessionId) {
      return;
    }
    setSessionFollowupQueues((current) => ({
      ...current,
      [activeSessionId]: removeComposerQueueItem(current[activeSessionId] ?? [], id),
    }));
  }, [activeSessionId, setSessionFollowupQueues]);

  const handleFollowupQueueMove = useCallback((fromIndex: number, toIndex: number) => {
    if (!activeSessionId) {
      return;
    }
    setSessionFollowupQueues((current) => ({
      ...current,
      [activeSessionId]: moveComposerQueueItem(current[activeSessionId] ?? [], fromIndex, toIndex),
    }));
  }, [activeSessionId, setSessionFollowupQueues]);

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
      pendingStopAfterAcceptRef.current = activeSessionId;
      return;
    }
    pendingStopAfterAcceptRef.current = "";
    stoppedTurnAutoFlushRef.current = { sessionId: activeSessionId, turnId };
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

  useEffect(() => {
    const pendingSessionId = pendingStopAfterAcceptRef.current;
    if (!activeSessionId || pendingSessionId !== activeSessionId || sessionStopping) {
      return;
    }
    const turnId = resolveSessionStopTurnId(detail, activeTurnId);
    if (!turnId) {
      return;
    }
    pendingStopAfterAcceptRef.current = "";
    stoppedTurnAutoFlushRef.current = { sessionId: activeSessionId, turnId };
    stopTurnMutation.mutate({
      sessionId: activeSessionId,
      turnId,
    });
  }, [activeSessionId, activeTurnId, detail, sessionStopping, stopTurnMutation]);

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

  useEffect(() => {
    const wasBusy = previousBusyRef.current;
    const previousSession = previousSessionRef.current;
    previousBusyRef.current = sessionBusy;
    previousSessionRef.current = activeSessionId;
    if (previousSession !== activeSessionId) {
      pendingStopAfterAcceptRef.current = "";
    }
    const stoppedTurn = stoppedTurnAutoFlushRef.current;
    if (
      sessionBusy
      && stoppedTurn
      && stoppedTurn.sessionId === activeSessionId
      && activeTurnId
      && activeTurnId !== stoppedTurn.turnId
    ) {
      stoppedTurnAutoFlushRef.current = null;
    }
    if (!activeSessionId || previousSession !== activeSessionId) {
      return;
    }
    if (!(wasBusy && !sessionBusy)) {
      return;
    }
    if (stoppedTurn?.sessionId === activeSessionId) {
      stoppedTurnAutoFlushRef.current = null;
      if (!activeTurnId || activeTurnId === stoppedTurn.turnId) {
        return;
      }
    }
    if (sessionStopping) {
      return;
    }
    const first = (sessionFollowupQueues[activeSessionId] ?? [])[0];
    if (!first) {
      return;
    }
    setSessionFollowupQueues((current) => ({
      ...current,
      [activeSessionId]: removeComposerQueueItem(current[activeSessionId] ?? [], first.id),
    }));
    void submitTurnWithAttachments(
      activeSessionId,
      first.text,
      [],
      [],
      mentalModelEnabledForNextTurn,
      runtimeStatusEnabledForNextTurn,
      createClientSubmissionId(activeSessionId),
    );
  }, [
    activeSessionId,
    activeTurnId,
    mentalModelEnabledForNextTurn,
    runtimeStatusEnabledForNextTurn,
    sessionBusy,
    sessionFollowupQueues,
    sessionStopping,
    setSessionFollowupQueues,
    submitTurnWithAttachments,
  ]);

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
    handleEditUserMessage,
    handleCancelEditMessage,
  };
}
