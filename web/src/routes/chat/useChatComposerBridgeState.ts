import { useMemo } from "react";

import type {
  AgentInstance,
  SessionDetail,
  SessionGuidanceMode,
  SessionReferenceAttachment,
} from "../../api/types";
import type { ComposerQueueItem } from "../../components/conversation/composerFollowupQueueModel";
import type { TranslationKey } from "../../i18n/dictionary";
import {
  latestUserMessageId as deriveLatestUserMessageId,
  resolveComposerDraftValue,
  resolveLatestEditTarget,
} from "../chatComposerState";
import type { ComposerImageAttachment } from "./chatComposerSubmitModel";
import {
  buildConversationComposerBridgeState,
  type ChatConversationComposerBridgeState,
} from "./ChatConversationComposerBridge";
import {
  isBusyPhase,
  isRunningPhase,
  isStoppingPhase,
  shouldSuppressComposerErrorForTurnError,
} from "./chatCodingRouteViewModel";
import {
  imageInputModelIdForAgent,
  modelImageInputSupport,
} from "./chatRoutePresentation";
import { latestVisibleTurnErrorMessage } from "./chatSessionDetailHelpers";

export interface UseChatComposerBridgeStateParams {
  activeSessionId: string | null;
  sessionDrafts: Record<string, string>;
  sessionFollowupQueues: Record<string, ComposerQueueItem[]>;
  sessionComposerErrors: Record<string, string>;
  sessionEditTargets: Record<string, { messageId: string; original: string }>;
  sessionImageAttachments: Record<string, ComposerImageAttachment[]>;
  sessionReferenceAttachments: Record<string, SessionReferenceAttachment[]>;
  sessionImageUploadPending: Record<string, boolean>;
  detail: SessionDetail | null | undefined;
  agents: AgentInstance[] | undefined;
  modelImageInputSupportById: Map<string, boolean | null>;
  lang: "zh" | "en";
  t: (key: TranslationKey) => string;
  submitTurnMutation: {
    isPending: boolean;
    variables?: { sessionId?: string };
  };
  editResubmitMutation: {
    isPending: boolean;
    variables?: { sessionId?: string };
  };
  stopTurnMutation: {
    isPending: boolean;
    variables?: { sessionId?: string };
  };
  sessionGuidanceMutation: {
    isPending: boolean;
    variables?: { sessionId?: string; mode?: SessionGuidanceMode };
  };
  activeTurnSettledByDetail: boolean;
}

export interface ChatComposerBridgeStateResult {
  activeDraft: string;
  activeFollowupQueue: ComposerQueueItem[];
  activeComposerError: string;
  activeEditTarget: { messageId: string; original: string } | null;
  resolvedEditTarget: { messageId: string; original: string } | null;
  activeDraftEffective: string;
  activeImageAttachments: ComposerImageAttachment[];
  activeReferenceAttachments: SessionReferenceAttachment[];
  activeImageUploadPending: boolean;
  activeSessionAgent: AgentInstance | undefined;
  activeImageInputModelId: string;
  latestUserMessageId: string;
  activeAgentImageInputSupported: boolean | null;
  activeAgentImageInputUnsupported: boolean;
  activeImageInputGuidance: string;
  submitPending: boolean;
  sessionRunning: boolean;
  sessionStopping: boolean;
  sessionBusy: boolean;
  composerDisabled: boolean;
  conversationComposer: ChatConversationComposerBridgeState;
}

export function useChatComposerBridgeState({
  activeSessionId,
  sessionDrafts,
  sessionFollowupQueues,
  sessionComposerErrors,
  sessionEditTargets,
  sessionImageAttachments,
  sessionReferenceAttachments,
  sessionImageUploadPending,
  detail,
  agents,
  modelImageInputSupportById,
  lang,
  t,
  submitTurnMutation,
  editResubmitMutation,
  stopTurnMutation,
  sessionGuidanceMutation,
  activeTurnSettledByDetail,
}: UseChatComposerBridgeStateParams): ChatComposerBridgeStateResult {
  const activeDraft = activeSessionId ? sessionDrafts[activeSessionId] ?? "" : "";
  const activeFollowupQueue = activeSessionId ? sessionFollowupQueues[activeSessionId] ?? [] : [];
  const activeComposerRawError = activeSessionId ? sessionComposerErrors[activeSessionId] ?? "" : "";
  const activeLatestTurnErrorMessage = useMemo(
    () => latestVisibleTurnErrorMessage(detail?.messages),
    [detail?.messages],
  );
  const activeComposerError = shouldSuppressComposerErrorForTurnError(
    activeComposerRawError,
    activeLatestTurnErrorMessage,
    detail?.lastTurnError,
  )
    ? ""
    : activeComposerRawError;
  const activeEditTarget = activeSessionId ? sessionEditTargets[activeSessionId] ?? null : null;
  const activeImageAttachments = activeSessionId ? sessionImageAttachments[activeSessionId] ?? [] : [];
  const activeReferenceAttachments = activeSessionId ? sessionReferenceAttachments[activeSessionId] ?? [] : [];
  const activeImageUploadPending = activeSessionId ? Boolean(sessionImageUploadPending[activeSessionId]) : false;
  const activeAgentId = detail?.agentId || "";
  const activeSessionAgent = activeAgentId ? (agents ?? []).find((agent) => agent.agentId === activeAgentId) : undefined;
  const activeImageInputModelId = imageInputModelIdForAgent(activeSessionAgent, detail?.dialogueModelId);
  const activeAgentImageInputSupported = modelImageInputSupport(modelImageInputSupportById, activeImageInputModelId);
  const activeAgentImageInputUnsupported = activeAgentImageInputSupported === false;
  const activeImageInputModelLabel = activeImageInputModelId || (lang === "zh" ? "当前模型" : "the current model");
  const activeImageInputGuidance = !activeImageAttachments.length
    ? ""
    : activeAgentImageInputSupported === true
      ? (lang === "zh"
        ? `图片将发送给已验证支持图像输入的 ${activeImageInputModelLabel}。`
        : `The image will be sent to ${activeImageInputModelLabel}, which has verified image-input support.`)
      : activeAgentImageInputSupported === false
        ? (lang === "zh"
          ? `${activeImageInputModelLabel} 明确不支持图像输入，无法发送图片。`
          : `${activeImageInputModelLabel} explicitly does not support image input, so the image cannot be sent.`)
        : (lang === "zh"
          ? `${activeImageInputModelLabel} 的图像输入能力尚未验证；将尝试发送，失败时会保留诊断。`
          : `${activeImageInputModelLabel}'s image-input capability is not verified yet. Vibelution will try the request and retain diagnostics if it fails.`);

  const latestUserMessageId = useMemo(() => deriveLatestUserMessageId(detail?.messages), [detail?.messages]);
  const resolvedEditTarget = resolveLatestEditTarget(activeEditTarget, latestUserMessageId);
  const activeDraftEffective = resolveComposerDraftValue(activeDraft, activeEditTarget, resolvedEditTarget);

  const submitMutationMatchesActiveSession =
    submitTurnMutation.variables?.sessionId === activeSessionId;
  const editResubmitMutationMatchesActiveSession =
    editResubmitMutation.variables?.sessionId === activeSessionId;
  const stopMutationMatchesActiveSession =
    stopTurnMutation.variables?.sessionId === activeSessionId;
  const guidanceMutationMatchesActiveSession =
    sessionGuidanceMutation.variables?.sessionId === activeSessionId;

  const submitPending =
    (submitTurnMutation.isPending && submitMutationMatchesActiveSession)
    || (editResubmitMutation.isPending && editResubmitMutationMatchesActiveSession)
    || activeImageUploadPending;
  const sessionRunning = isRunningPhase(detail?.currentPhase);
  const sessionStopping = isStoppingPhase(detail?.currentPhase) || Boolean(detail?.stopRequested);
  const lastTurnStatusNormalized = String(detail?.lastTurnStatus || "").trim().toLowerCase();
  const terminalReasonNormalized = String(detail?.terminalReason || "").trim().toLowerCase();
  const lastTurnTerminal = [
    "ready",
    "completed",
    "failed",
    "failed_runtime",
    "failed_provider",
    "needs_continue",
    "paused_limit",
    "stopped_by_user",
    "superseded",
    "cancelled",
    "success",
    "aborted",
  ].includes(lastTurnStatusNormalized)
    || [
      "success",
      "failed_runtime",
      "failed_provider",
      "needs_continue",
      "paused_limit",
      "stopped_by_user",
      "aborted",
      "superseded",
      "ready",
    ].includes(terminalReasonNormalized);
  const liveActiveTurnOpen = Boolean(detail?.activeTurnId)
    && !activeTurnSettledByDetail;
  const sessionBusy = isBusyPhase(detail?.currentPhase)
    && !(lastTurnTerminal && !liveActiveTurnOpen && !sessionStopping);
  const composerStopPending = (stopTurnMutation.isPending && stopMutationMatchesActiveSession) || sessionStopping;
  const composerSafeGuidancePending =
    sessionGuidanceMutation.isPending
    && guidanceMutationMatchesActiveSession
    && sessionGuidanceMutation.variables?.mode === "safe";
  const composerInterruptGuidancePending =
    sessionGuidanceMutation.isPending
    && guidanceMutationMatchesActiveSession
    && sessionGuidanceMutation.variables?.mode === "interrupt";

  const conversationComposer = useMemo(
    () => buildConversationComposerBridgeState({
      editTargetMessageId: resolvedEditTarget?.messageId,
      editTargetPreview: resolvedEditTarget?.original,
      error: activeComposerError,
      followupQueue: activeFollowupQueue,
      guidance: activeImageInputGuidance,
      imageAttachments: activeImageAttachments,
      imageInputUnsupported: activeAgentImageInputUnsupported,
      interruptGuidancePending: composerInterruptGuidancePending,
      labels: {
        editMessageModeNotice: t("editMessageModeNotice"),
        editMessagePlaceholder: t("editMessagePlaceholder"),
        loadingSession: t("loadingSession"),
        messageInputPlaceholder: t("messageInputPlaceholder"),
        saveAndRerunMessage: t("saveAndRerunMessage"),
      },
      references: activeReferenceAttachments,
      safeGuidancePending: composerSafeGuidancePending,
      sessionBusy,
      sessionId: activeSessionId,
      sessionStopping,
      stopPending: composerStopPending,
      submitPending,
      value: activeDraftEffective,
    }),
    [
      activeAgentImageInputUnsupported,
      activeComposerError,
      activeDraftEffective,
      activeFollowupQueue,
      activeImageAttachments,
      activeReferenceAttachments,
      activeSessionId,
      resolvedEditTarget?.original,
      resolvedEditTarget?.messageId,
      composerInterruptGuidancePending,
      composerSafeGuidancePending,
      composerStopPending,
      sessionBusy,
      sessionStopping,
      submitPending,
      t,
    ],
  );

  const composerDisabled = conversationComposer.disabled;

  return {
    activeDraft,
    activeFollowupQueue,
    activeComposerError,
    activeEditTarget,
    resolvedEditTarget,
    activeDraftEffective,
    activeImageAttachments,
    activeReferenceAttachments,
    activeImageUploadPending,
    activeSessionAgent,
    activeImageInputModelId,
    latestUserMessageId,
    activeAgentImageInputSupported,
    activeAgentImageInputUnsupported,
    activeImageInputGuidance,
    submitPending,
    sessionRunning,
    sessionStopping,
    sessionBusy,
    composerDisabled,
    conversationComposer,
  };
}
