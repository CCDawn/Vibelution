import {
  ArrowDown,
  BrainCircuit,
  CheckCircle2,
  CircleDot,
  Gauge,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { conversationStreamingFrameIdentity } from "./conversationStreamingMetrics";

import type {
  ConversationMessage,
  SessionMessageCurationAction,
} from "../../api/types";
import type {
  AgentMessage,
  AgentMentalPart,
} from "../../agent-thread/types";
import { fetchJson } from "../../api/client";
import { fetchConfigBootstrap } from "../../api/config";
import { fetchSessionMessageCuration, isFetchJsonHttpError, setSessionMessageCuration } from "../../api/chat";
import { queryKeys } from "../../api/queryKeys";
import { VStateSurface } from "../../components/vui";
import { useAppI18n } from "../../i18n/useAppI18n";
import type { ConversationImagePreviewRequest } from "./ConversationImagePreviewDialog";
import { ConversationForkSessionDialog } from "./ConversationForkSessionDialog";
import { ConversationTranscriptLoadingState } from "./ConversationTranscriptLoadingState";
import { ConversationTurnNavigator } from "./ConversationTurnNavigator";
import { useConversationTurnNav } from "./useConversationTurnNav";
import { buildConversationModelSwitchBoundaries } from "./conversationModelSwitch";
import { ConversationTurnAvatarContent } from "./ConversationTurnAvatarContent";
import { attachmentSizeLabel, isImageAttachment } from "./attachmentPresentation";
import { type OperationDetailLabels } from "./ConversationOperationDetails";

/** T1: dialog/context chrome load only when opened — keep transcript path leaner. */
const ConversationImagePreviewDialog = React.lazy(() =>
  import("./ConversationImagePreviewDialog").then((module) => ({
    default: module.ConversationImagePreviewDialog,
  })),
);
import { buildAgentMessageRenderState, type AgentMessageRenderState } from "./agentMessageRenderState";
import {
  assistantFinalAnswerText,
  assistantTurnIsInFlight,
  assistantTurnIsStreaming,
} from "../../routes/chatTurnProtocol";
import {
  applyOptimisticCuration,
  buildMessageCurationMap,
  resolveMessageCurationState,
  type MessageCurationDecision,
} from "./conversationMessageCuration";
import {
  compactStreamingStatusPlaceholder,
  isInternalStreamingStatusStage,
} from "./conversationInternalStatus";
import { ConversationActiveTurnStatusNote } from "./ConversationActiveTurnStatusNote";
import { ConversationRunningTasks } from "./ConversationRunningTasks";
import {
  buildAgentMessageOperationGroups,
  type AgentMessageOperationGroups,
  type AgentMessageOperationKind,
  type AgentMessageReActOperationGroup,
} from "./agentMessageOperations";
import {
  isLongLoopProgressOperation,
  operationStateLabel,
  operationStatusTone,
  isRetryOperation,
  shouldShowTimelineOperation,
  type OperationStateLabels,
} from "./conversationOperationState";
import {
  buildAgentMessageTimelineItems,
  type AgentMessageTimelineItem,
} from "./agentMessageTimeline";
import {
  buildCodexTranscriptCells,
  type CodexTranscriptCell,
} from "./codexTranscriptCells";
import {
  compactCodexTranscriptCellsIncrementally,
  type CodexTranscriptCompactionCache,
} from "./codexTranscriptCompactionCache";
import { resolveCodexTranscriptSurface, type CodexTranscriptSurface } from "./codexNativeTranscriptSurface";
import { ConversationToolActivityPills } from "./ConversationToolActivityPills";
import { type AgentMessageTimelineRowIdentity } from "./agentMessageTimelineRows";
import { useAgentThread } from "./useAgentThread";
import { projectAgentMessageTimelineMessages } from "./useAgentMessageTimelineProjection";
import { conversationLiveTailStartIndex } from "./conversationGuidanceSegments";
import { projectConversationDisplayMessages } from "./conversationDisplayMessages";
import {
  imageArtifactForMessage,
  isAgentInboxMessage,
  isSteerGuidanceMessage,
  isTurnErrorMessage,
} from "./conversationMessagePredicates";
import {
  addComparableConversationImageUrl,
  comparableConversationImageUrl,
  conversationImageDownloadName,
  conversationImagePreviewUrl,
  isLikelyConversationImageUrl,
} from "./conversationImagePreview";
import { formatConversationTimestamp } from "./conversationTimeFormat";
import {
  captureTimelineRowKeyAnchor,
  type TimelineScrollRowKeyAnchor,
} from "./timelineScrollAnchor";
import {
  buildStreamingTimelineScrollSignal,
  buildTimelineScrollSignal,
} from "./conversationTimelineScrollSignals";
import {
  CONVERSATION_VIRTUAL_ROW_ESTIMATE_PX,
  type TimelineUserScrollIntent,
} from "./conversationTimelineFollowState";
import { useConversationProcessExpansion } from "./useConversationProcessExpansion";
import { useConversationTimelineFollow } from "./useConversationTimelineFollow";
import {
  conversationPerformanceNowMs,
  transcriptCellSequenceMatches,
} from "./conversationTurnRowMemo";
import {
  buildTurnErrorDiagnosticRows,
  buildCurrentTurnErrorRows,
  summarizeCurrentTurnError,
  resolveIterationLimitNotice,
  resolveConversationTurnErrorType,
  resolveConversationTurnErrorRecoveryAction,
  resolveSessionTurnErrorRecoveryAction,
  resolveTurnErrorTypeLabelKey,
} from "./conversationTurnErrorPresentation";
import { buildConversationToolActivityDetailRows } from "./conversationToolActivityDetail";
import {
  resolveMessageTurnAvatar,
  userAvatarSymbol,
  type TurnAvatarResolution,
} from "./conversationTurnAvatar";
import type { ConversationViewProps } from "./conversationViewTypes";
import { compactConversationPreview } from "./conversationOperationPresentation";
import {
  completedToolPresentationSummary,
  conversationToolPresentationLabel,
  type CodexToolActivityPills,
} from "./conversationToolPresentation";
import {
  ThoughtDurationLabel,
  ThoughtScrollBody,
  ThoughtStreamingSummary,
} from "./conversationThoughtUnits";
import { ConversationFindBar } from "./ConversationFindBar";
import { createCodexTranscriptCellRenderers } from "./conversationCodexTranscriptCells";
import { createConversationAuxiliaryPanels } from "./conversationAuxiliaryPanels";
import { createConversationCodexSurface } from "./conversationCodexSurface";
import { createConversationCodexToolDetails } from "./conversationCodexToolDetails";
import { createConversationOperationGroups } from "./conversationOperationGroups";
import { createConversationOperationRows } from "./conversationOperationRows";
import { createConversationReActRows } from "./conversationReActRows";
import { createConversationResponseBlocks } from "./conversationResponseBlocks";
import { createConversationSpecialRows } from "./conversationSpecialRows";
import { createConversationTimelineItems } from "./conversationTimelineItems";
import { createConversationTimelineRows } from "./conversationTimelineRows";
import { useComputerUseResults } from "./useComputerUseResults";
import { useConversationComposer } from "./useConversationComposer";
import { useConversationFind } from "./useConversationFind";
import { useConversationForkSession } from "./useConversationForkSession";
import { useConversationSelectionQuote } from "./useConversationSelectionQuote";
import { VButton } from "../vui";
import styles from "./ConversationView.styles";



// Virtual timeline (react-virtual): rows rendered beyond the measured viewport
// per direction, vertical rhythm matching the timelineContent grid gap, the
// scroll container's top padding before the virtual host, and a
// generous SSR/first-paint rect so server-rendered windows stay deterministic.
const TIMELINE_VIRTUAL_OVERSCAN = 8;
const TIMELINE_NARROW_VIEWPORT_QUERY = "(max-width: 719px)";
const TIMELINE_VIRTUAL_ROW_GAP_PX = 28;
const TIMELINE_VIRTUAL_SCROLL_MARGIN_PX = 28;
const TIMELINE_NARROW_ROW_GAP_PX = 20;
const TIMELINE_NARROW_SCROLL_MARGIN_PX = 22;
const TIMELINE_VIRTUAL_INITIAL_RECT = { width: 1280, height: 900 };

async function copyTextToClipboard(text: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const textArea = document.createElement("textarea");
  textArea.value = text;
  textArea.setAttribute("readonly", "true");
  textArea.style.position = "absolute";
  textArea.style.opacity = "0";
  textArea.style.pointerEvents = "none";
  document.body.appendChild(textArea);
  textArea.select();
  const copied = document.execCommand("copy");
  document.body.removeChild(textArea);
  if (!copied) {
    throw new Error("copy failed");
  }
}

// Memo gate: with stable prop references from the route (memoized conversation
// model + composer bridge) unrelated parent re-renders stop here. Streaming
// frames still re-render this component because the active-turn message prop
// changes per committed frame.
export const ConversationView = React.memo(function ConversationView({
  sessionId,
  title,
  phase,
  messages,
  activeTurnMessage,
  transcriptPending = false,
  sessionWorkspacePath,
  className,
  density = "default",
  composerVariant = "compact",
  eyebrowLabel,
  assistantDisplayName,
  assistantAvatarImageUrl,
  assistantAvatarFallback,
  resolveTurnAvatar,
  userDisplayName,
  userAvatarPreset,
  userAvatarImageUrl,
  taskSummary,
  defaultFileContext,
  summaryItems,
  stats,
  headerActions,
  supplementalContent,
  showHeader = true,
  showSessionOverview = true,
  showMentalSnapshots = true,
  showComposer = true,
  processDisplayMode = "answer",
  companionMode = false,
  autoScrollToLatest = true,
  hasEarlierMessages = false,
  earlierMessagesLoading = false,
  onStreamingFramePaint,
  composerValue,
  composerPlaceholder,
  composerDisabled,
  promptSuggestionEnabled = false,
  composerFocusSignal = "",
  onComposerFocusRequestSettled,
  composerActionDisabled,
  composerActionMode,
  composerPending,
  composerSafeGuidancePending = false,
  composerInterruptGuidancePending = false,
  composerError,
  composerGuidance,
  followupQueue = [],
  composerAttachments = [],
  composerReferences = [],
  slashCommandSuggestions = [],
  slashSkillsCatalogState = "ready",
  composerReferenceOptions = [],
  composerAttachmentInputDisabled,
  composerLeadingControl,
  permissionControl,
  toolApproval = null,
  llmControl,
  turnModelControl,
  onOpenAgentModelConfig,
  composerContextRing = null,
  onOpenComposerContextDetail,
  onCreateSession,
  onOpenSideChat,
  onOpenRailFile,
  turnError,
  submitLabel,
  submitPendingLabel,
  stopLabel,
  stopPendingLabel,
  safeGuidanceLabel,
  safeGuidancePendingLabel,
  interruptGuidanceLabel,
  interruptGuidancePendingLabel,
  editingMessageId,
  editUserMessageLabel,
  editUserMessageDisabled,
  composerModeNotice,
  composerModeTargetPreview,
  cancelComposerModeLabel,
  onComposerChange,
  onAddComposerAttachments,
  onRemoveComposerAttachment,
  onRetryComposerAttachment,
  onRetryComposerAttachmentUploads,
  onAddComposerReference,
  onRemoveComposerReference,
  onEditUserMessage,
  onRegenerateAssistantMessage,
  onSwitchMessageVersion,
  branchVersionSwitchDisabled,
  onForkSessionFromNode,
  regenerableAssistantMessageId,
  regenerateDisabled,
  regeneratePending,
  onRetryTurn,
  retryTurnDisabled,
  retryTurnPending,
  onCancelComposerMode,
  onLoadEarlierMessages,
  onSubmit,
  onStop,
  onContinueTurn,
  onSafeGuidance,
  onInterruptGuidance,
  onFollowupQueueUpdate,
  onFollowupQueueRemove,
  onFollowupQueueMove,
  onFollowupQueueSteer,
  onFollowupQueueSendNow,
  followupQueueSteerLabel,
}: ConversationViewProps) {
  void interruptGuidanceLabel;
  void interruptGuidancePendingLabel;
  void onInterruptGuidance;
  void onSafeGuidance;
  const { lang, t, statusLabel } = useAppI18n({ domains: ["chat"] });
  // Model labels for the turn-envelope switch dividers. Uses the lightweight
  // configuration bootstrap summary (modelLabels id→label map) instead of the full
  // /api/config/workspace payload: this mount only needs labels, and the heavy
  // workspace endpoint landed in every boot volley. Shares the configPublic
  // cache key with the shell-wide summary consumers; absence of data degrades
  // to the raw model id.
  const configSummaryQuery = useQuery({
    queryKey: queryKeys.configPublic(),
    queryFn: ({ signal }) => fetchConfigBootstrap({ signal }),
    staleTime: 30_000,
  });
  const modelLabelByModelId = useMemo(
    () => new Map(Object.entries(configSummaryQuery.data?.modelLabels ?? {})),
    [configSummaryQuery.data?.modelLabels],
  );
  const conversationModelLabel = useCallback(
    (modelId: string) => modelLabelByModelId.get(modelId) ?? modelId,
    [modelLabelByModelId],
  );
  const timelineRef = useRef<HTMLDivElement | null>(null);
  const timelineContentRef = useRef<HTMLDivElement | null>(null);
  const readingViewportAnchorRef = useRef<TimelineScrollRowKeyAnchor | null>(null);
  // History rows are positioned by react-virtual, so they must use the same
  // viewport rhythm as the CSS grid that separates history from the live tail.
  const [narrowTimelineViewport, setNarrowTimelineViewport] = useState(() => (
    typeof window !== "undefined"
    && typeof window.matchMedia === "function"
    && window.matchMedia(TIMELINE_NARROW_VIEWPORT_QUERY).matches
  ));
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return undefined;
    const media = window.matchMedia(TIMELINE_NARROW_VIEWPORT_QUERY);
    const syncViewport = () => {
      if (readingViewportAnchorRef.current || !followLatestRef.current) {
        // The media event arrives after CSS has reflowed. Prefer the anchor
        // remembered while reading at the previous width.
        const anchor = readingViewportAnchorRef.current ?? captureTimelineRowKeyAnchor(timelineRef.current);
        if (anchor) {
          historyScrollAnchorRef.current = anchor;
          historyAnchorCorrectingRef.current = {
            anchor,
            startLength: 0, // Geometry reflow does not wait for message-count changes.
            attempts: 0,
            fallbackDone: false,
            geometryReflow: true,
          };
        }
      }
      setNarrowTimelineViewport(media.matches);
    };
    syncViewport();
    media.addEventListener("change", syncViewport);
    return () => media.removeEventListener("change", syncViewport);
  }, []);
  const historyScrollAnchorRef = useRef<TimelineScrollRowKeyAnchor | null>(null);
  /** Active prepend anchor while correction frames converge (see layout effect below). */
  const historyAnchorCorrectingRef = useRef<{
    anchor: TimelineScrollRowKeyAnchor;
    /** Message count at capture; correction starts once the prepend commits. */
    startLength: number;
    attempts: number;
    fallbackDone: boolean;
    /** A viewport rhythm change needs correction even without a prepend. */
    geometryReflow?: boolean;
  } | null>(null);
  /** Ensures a pending tool approval mounts under at most one tool activity per render. */
  const toolApprovalConsumedRef = useRef(false);
  toolApprovalConsumedRef.current = false;
  const composerInputRef = useRef<HTMLTextAreaElement | null>(null);
  // Composer auto-height (ZCode parity): the codex composer grows with the
  // draft and only scrolls internally once the CSS max-height clamp is hit —
  // same auto→scrollHeight trick as the inline edit editor. min/max stay in
  // the inputCodex style (48px/240px), the inline height never exceeds them.
  // Stays here, ahead of the virtualizer, so a draft resize lands before
  // timeline measurement in the same commit.
  useLayoutEffect(() => {
    if (composerVariant !== "codex") {
      return;
    }
    const el = composerInputRef.current;
    if (!el) {
      return;
    }
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [composerVariant, composerValue, composerDisabled]);
  const inlineEditInputRef = useRef<HTMLTextAreaElement | null>(null);
  const initializedSessionRef = useRef("");
  const pinnedLatestUserMessageIdRef = useRef("");
  const atBottomRef = useRef(true);
  const followLatestRef = useRef(true);
  const lastTimelineScrollTopRef = useRef(0);
  const userScrollIntentRef = useRef<TimelineUserScrollIntent>("none");
  const userScrollIntentAtRef = useRef(0);
  const ignoreNextProgrammaticFollowRef = useRef(false);
  const lastTimelineContentWidthRef = useRef(0);
  const contentWidthChangingUntilRef = useRef(0);
  const streamingScrollFrameRef = useRef<number | null>(null);
  // Find and the composer run above the follow hook and call this helper.
  // The hook fills the delegate during render, before any effect runs.
  const timelineFollowApiRef = useRef<{
    scrollTimelineToBottom: (
      timeline: HTMLDivElement,
      options?: { followLatest?: boolean; behavior?: ScrollBehavior },
    ) => void;
  } | null>(null);
  function scrollTimelineToBottom(
    timeline: HTMLDivElement,
    options: { followLatest?: boolean; behavior?: ScrollBehavior } = {},
  ) {
    timelineFollowApiRef.current?.scrollTimelineToBottom(timeline, options);
  }
  const autoScrollToLatestRef = useRef(autoScrollToLatest);
  autoScrollToLatestRef.current = autoScrollToLatest;
  const [isAtBottom, setIsAtBottom] = useState(true);
  const [previewImage, setPreviewImage] = useState<ConversationImagePreviewRequest | null>(null);
  const streamingPaintMetricsRef = useRef({
    streamingMessageCount: 0, renderedTextLength: 0, ...conversationStreamingFrameIdentity(undefined),
  });
  const [copiedAnswerMessageId, setCopiedAnswerMessageId] = useState("");
  const copyAnswerFeedbackTimerRef = useRef<number | null>(null);
  // In-chat SFT curation: server map + optimistic overlay for instant button
  // feedback; a failed POST rolls the overlay entry back (ZCode like/dislike
  // rollback pattern) and the 409 copy surfaces briefly on the button title.
  const queryClient = useQueryClient();
  const [curationOverrides, setCurationOverrides] = useState<Map<string, MessageCurationDecision>>(new Map());
  const [curationFeedback, setCurationFeedback] = useState<{
    messageId: string;
    action: SessionMessageCurationAction;
    message: string;
  } | null>(null);
  const curationFeedbackTimerRef = useRef<number | null>(null);
  const messageCurationQuery = useQuery({
    queryKey: queryKeys.sessionMessageCuration(sessionId),
    queryFn: () => fetchSessionMessageCuration(sessionId),
    // Curation decorates loaded messages; its queue scan must not compete with
    // the initial transcript request while there is nothing to annotate yet.
    enabled: Boolean(sessionId) && !companionMode && !transcriptPending,
  });
  const serverMessageCurationMap = useMemo(
    () => buildMessageCurationMap(messageCurationQuery.data?.items ?? []),
    [messageCurationQuery.data],
  );
  const messageCurationMap = useMemo(() => {
    if (curationOverrides.size === 0) {
      return serverMessageCurationMap;
    }
    return new Map([...serverMessageCurationMap, ...curationOverrides]);
  }, [curationOverrides, serverMessageCurationMap]);

  // A session switch must not inherit the previous session's optimistic writes.
  useEffect(() => {
    setCurationOverrides(new Map());
    setCurationFeedback(null);
  }, [sessionId]);
  const {
    forkDialogMessage,
    forkScope,
    forkPending,
    setForkScope,
    openForkDialog,
    closeForkDialog,
    confirmForkSession,
  } = useConversationForkSession({ onForkSessionFromNode });
  const { timelineAreaRef, menu: selectionQuoteMenu } = useConversationSelectionQuote({
    sessionId,
    lang,
    composerValue,
    timelineRef,
    composerInputRef,
    onComposerChange,
    onOpenSideChat,
    onAddComposerReference,
    copyText: copyTextToClipboard,
  });
  const assistantLabel = assistantDisplayName?.trim() || t("agent");
  const userLabel = userDisplayName?.trim() || t("operator");
  const userAvatarLabel = userAvatarSymbol(userAvatarPreset, userLabel);
  const answerOnlyProcessMode = processDisplayMode === "answer";
  const timestampFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat(lang === "zh" ? "zh-CN" : "en-US", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }),
    [lang],
  );


  const latestUserMessage = useMemo(() => {
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      const message = messages[index];
      if (message.role !== "user") {
        continue;
      }
      if (isAgentInboxMessage(message) || isSteerGuidanceMessage(message)) {
        continue;
      }
      return message.content;
    }
    return "";
  }, [messages]);
  const latestUserMessageId = useMemo(() => {
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      const message = messages[index];
      if (message.role !== "user") {
        continue;
      }
      if (isAgentInboxMessage(message) || isSteerGuidanceMessage(message)) {
        continue;
      }
      return message.id;
    }
    return "";
  }, [messages]);
  const lastMessageTimestamp = useMemo(
    () => [...messages].reverse().find((message) => message.timestamp)?.timestamp ?? "",
    [messages],
  );
  const formatTimestamp = (timestamp: string) => formatConversationTimestamp(timestamp, timestampFormatter);
  const operationDetailLabels: OperationDetailLabels = {
    rawName: lang === "zh" ? "原始名称" : "Raw name",
    fullStatus: lang === "zh" ? "完整状态" : "Full status",
    toolCallArguments: t("toolCallArguments"),
    thoughtProcess: t("thoughtProcess"),
    toolCallResult: t("toolCallResult"),
    toolCallError: t("toolCallError"),
    structuredResultFallback: lang === "zh" ? "返回结构化结果，可展开详情查看。" : "Structured result returned; expand details to inspect.",
  };

  const taskFocus = compactPreview(taskSummary || latestUserMessage || title);
  const fileContext = defaultFileContext || "workspace";
  const resolvedSummaryItems = summaryItems ?? [
    { label: t("taskFocus"), value: taskFocus },
    { label: t("fileContext"), value: fileContext },
    { label: t("status"), value: statusLabel(phase) },
    { label: t("lastUpdated"), value: lastMessageTimestamp ? formatTimestamp(lastMessageTimestamp) : "--" },
  ];
  const resolvedStats = stats ?? [];
  const displayMessages = useMemo(
    () => projectConversationDisplayMessages(messages),
    [messages],
  );
  const hasVisibleTurnErrorMessage = useMemo(
    () => displayMessages.some((message) => isTurnErrorMessage(message)),
    [displayMessages],
  );
  const iterationLimitNotice = resolveIterationLimitNotice(turnError, lang);
  // A persisted turnError can outlive the answer it belongs to (provider error
  // raised after the canonical final_answer was committed). Never duplicate the
  // failure banner under a turn that already rendered its final answer.
  const turnErrorSupersededByFinalAnswer = useMemo(() => {
    const errorTurnId = String(turnError?.turnId || "").trim();
    if (!errorTurnId) {
      return false;
    }
    return displayMessages.some((message) => (
      message.role === "assistant"
      && String(message.turnId || "").trim() === errorTurnId
      && Boolean(assistantFinalAnswerText(message).trim())
    ));
  }, [displayMessages, turnError]);
  // Full-history virtualization renders every local message; the old client
  // window (first 12 / +12 / soft cap 72) is gone, so there is no locally
  // hidden history left — only the server earlier-load signal below.
  const visibleMessageCount = displayMessages.length;
  const hiddenRenderedMessageCount = displayMessages.length - visibleMessageCount;
  const hiddenHistorySignalCount = hiddenRenderedMessageCount + (hasEarlierMessages ? 1 : 0);
  const timelineMessages = displayMessages;
  const activeAgentMessageTimelineProjection = useMemo(
    () => projectAgentMessageTimelineMessages({ timelineMessages, activeTurnMessage, companionMode }),
    [activeTurnMessage, companionMode, timelineMessages],
  );
  const activeTimelineMessages = activeAgentMessageTimelineProjection.messages;
  /**
   * Companion turns intentionally expose one chat-like affordance instead of
   * the native process transcript. Keep the latest assistant turn as the
   * source of truth so a historical running row cannot resurrect the status
   * after a newer terminal answer has committed.
   */
  const companionTypingMessage = useMemo<Extract<ConversationMessage, { role: "assistant" }> | undefined>(() => {
    if (!companionMode) {
      return undefined;
    }
    for (let index = activeTimelineMessages.length - 1; index >= 0; index -= 1) {
      const message = activeTimelineMessages[index];
      if (message.role !== "assistant") {
        continue;
      }
      if (!assistantTurnIsInFlight(message) || assistantFinalAnswerText(message).trim()) {
        return undefined;
      }
      return message;
    }
    return undefined;
  }, [activeTimelineMessages, companionMode]);
  const activeTimelineMessageOrder = useMemo(
    () => new Map(activeTimelineMessages.map((message, index) => [message.id, index])),
    [activeTimelineMessages],
  );
  const activeAgentMessages = activeAgentMessageTimelineProjection.agentMessages;
  const streamingTimelineMessages = activeAgentMessageTimelineProjection.streamingMessages;
  const activeTimelineRowIdentities = activeAgentMessageTimelineProjection.rowIdentities;
  const getTimelineScrollElement = useCallback(() => timelineRef.current, []);
  /**
   * Live-tail partition (zai-org/ZCode ConversationTimeline pattern,
   * Apache-2.0): the trailing run of in-flight turn rows renders OUTSIDE the
   * virtualized history window, so per-frame tail growth never reslices the
   * virtual range. A session executes one turn at a time, so this is normally
   * a single row.
   */
  const timelineLiveTailStartIndex = useMemo(() => {
    return conversationLiveTailStartIndex(activeTimelineMessages);
  }, [activeTimelineMessages]);
  const timelineHistoryMessages = useMemo(
    () => activeTimelineMessages.slice(0, timelineLiveTailStartIndex),
    [activeTimelineMessages, timelineLiveTailStartIndex],
  );
  const timelineLiveTailMessages = useMemo(
    () => activeTimelineMessages.slice(timelineLiveTailStartIndex),
    [activeTimelineMessages, timelineLiveTailStartIndex],
  );
  const timelineHistoryRowKeys = useMemo<string[]>(
    () => activeTimelineRowIdentities.map((identity) => identity.rowKey),
    [activeTimelineRowIdentities],
  );
  // Turn-envelope model-switch boundaries (ZCode parity): the user row that
  // opens a turn running on a different model than the previous turn-with-model
  // gets a hairline divider ("using X" / "switched from A to B"). Labels
  // resolve through conversationModelLabel with the raw id as fallback.
  const timelineModelSwitchBoundaries = useMemo(
    () => buildConversationModelSwitchBoundaries(activeTimelineMessages),
    [activeTimelineMessages],
  );
  // react-virtual keeps measured sizes in an item-size cache keyed by the
  // stable row keys from getItemKey, so measured heights survive index shifts
  // (prepend/load-earlier) without a hand-rolled cache.
  const timelineVirtualizer = useVirtualizer({
    count: timelineHistoryMessages.length,
    getScrollElement: getTimelineScrollElement,
    estimateSize: () => CONVERSATION_VIRTUAL_ROW_ESTIMATE_PX,
    getItemKey: (index) => timelineHistoryRowKeys[index] ?? `timeline-row-${index}`,
    overscan: TIMELINE_VIRTUAL_OVERSCAN,
    gap: narrowTimelineViewport ? TIMELINE_NARROW_ROW_GAP_PX : TIMELINE_VIRTUAL_ROW_GAP_PX,
    scrollMargin: narrowTimelineViewport ? TIMELINE_NARROW_SCROLL_MARGIN_PX : TIMELINE_VIRTUAL_SCROLL_MARGIN_PX,
    initialRect: { width: TIMELINE_VIRTUAL_INITIAL_RECT.width, height: TIMELINE_VIRTUAL_INITIAL_RECT.height },
    useAnimationFrameWithResizeObserver: true,
  });
  const measureTimelineVirtualRow = useCallback(
    (node: HTMLDivElement | null) => {
      if (node) {
        timelineVirtualizer.measureElement(node);
      }
    },
    [timelineVirtualizer],
  );
  // Find-in-transcript（对话内查找）：状态、索引、导航、高亮与跳转全部在
  // useConversationFind 内，不跨 route 边界。
  const {
    open: conversationFindOpen,
    query: conversationFindQuery,
    setQuery: setConversationFindQuery,
    activeIndex: conversationFindActiveIndex,
    matchCount: conversationFindMatchCount,
    inputRef: conversationFindInputRef,
    surfaceRef: conversationSurfaceRef,
    barLabels: conversationFindBarLabels,
    close: closeConversationFind,
    handlePrevious: handleConversationFindPrevious,
    handleNext: handleConversationFindNext,
  } = useConversationFind({
    sessionId,
    t,
    historyMessages: timelineHistoryMessages,
    liveTailStartIndex: timelineLiveTailStartIndex,
    timelineRef,
    timelineVirtualizer,
    previewImage,
    forkDialogMessage,
    scrollTimelineToBottom: (timeline) => scrollTimelineToBottom(timeline, { followLatest: false }),
  });
  /**
   * One render plan for both blocks: measured virtual rows inside the history
   * host (virtualStartPx set) plus the in-flight live-tail rows after it
   * (virtualStartPx null, static flow). The plan is rebuilt every render from
   * the virtualizer snapshot so scroll/measure notifications stay live.
   */
  const timelineRowPlan: Array<{ index: number; virtualStartPx: number | null }> = [];
  for (const virtualItem of timelineVirtualizer.getVirtualItems()) {
    timelineRowPlan.push({
      index: virtualItem.index,
      virtualStartPx: virtualItem.start - timelineVirtualizer.options.scrollMargin,
    });
  }
  for (let tailOffset = 0; tailOffset < timelineLiveTailMessages.length; tailOffset += 1) {
    timelineRowPlan.push({ index: timelineLiveTailStartIndex + tailOffset, virtualStartPx: null });
  }
  // Turn navigator directory and live current index, beside the row plan so
  // the minimap highlight reads the same virtualizer snapshot.
  const {
    timelineTurnNavEntries,
    timelineTurnNavCurrentIndex,
  } = useConversationTurnNav({
    lang,
    activeTimelineMessages,
    activeTimelineRowIdentities,
    historyRowCount: timelineLiveTailStartIndex,
    timelineVirtualizer,
  });

  const activeConversationMessagesById = useMemo(() => {
    const messagesById = new Map<string, ConversationMessage>();
    for (const message of activeTimelineMessages) {
      messagesById.set(message.id, message);
    }
    return messagesById;
  }, [activeTimelineMessages]);
  const agentThread = useAgentThread(sessionId, activeAgentMessages);
  const operationLabels = useMemo(
    () => ({
      thought: t("thoughtProcess"),
      mental: t("mentalProcess"),
      status: lang === "zh" ? "运行状态" : "Runtime status",
    }),
    [lang, t],
  );
  const agentMessagesByMessageId = useMemo(() => {
    const agentMessages = new Map<string, AgentMessage>();
    for (const agentMessage of agentThread.messages) {
      agentMessages.set(agentMessage.id, agentMessage);
    }
    return agentMessages;
  }, [agentThread]);
  const agentRenderStatesByMessageId = useMemo(() => {
    const renderStates = new Map<string, AgentMessageRenderState>();
    for (const agentMessage of agentThread.messages) {
      const agentRenderState = buildAgentMessageRenderState(agentMessage);
      renderStates.set(agentMessage.id, agentRenderState);
    }
    return renderStates;
  }, [agentThread]);
  const agentOperationGroupsByMessageId = useMemo(() => {
    const operationGroupsByMessageId = new Map<string, AgentMessageOperationGroups>();
    for (const agentMessage of agentThread.messages) {
      operationGroupsByMessageId.set(agentMessage.id, buildAgentMessageOperationGroups(agentMessage, operationLabels));
    }
    return operationGroupsByMessageId;
  }, [agentThread, operationLabels]);
  const agentTimelineItemsByMessageId = useMemo(() => {
    const itemsByMessageId = new Map<string, AgentMessageTimelineItem[]>();
    for (const agentMessage of agentThread.messages) {
      const operations = agentOperationGroupsByMessageId.get(agentMessage.id)?.timeline ?? [];
      itemsByMessageId.set(
        agentMessage.id,
        buildAgentMessageTimelineItems(
          agentMessage,
          operations,
          { lang, includeAssistantText: false },
        ),
      );
    }
    return itemsByMessageId;
  }, [agentOperationGroupsByMessageId, agentThread, lang]);
  // Cross-message compaction is one forward pass whose state resets at every
  // user row. Keeping its cache across frames is what limits a streaming frame
  // to the active turn segment instead of the whole transcript.
  const transcriptCompactionCacheRef = useRef<CodexTranscriptCompactionCache | null>(null);
  const agentCodexSurfacesByMessageId = useMemo(() => {
    const surfacesByMessageId = new Map<string, CodexTranscriptSurface>();
    for (const agentMessage of agentThread.messages) {
      const projectedCells = buildCodexTranscriptCells(agentMessage, {
        operations: agentOperationGroupsByMessageId.get(agentMessage.id)?.timeline,
        timelineItems: agentTimelineItemsByMessageId.get(agentMessage.id),
      });
      const sourceMessage = activeConversationMessagesById.get(agentMessage.source.id);
      if (!sourceMessage) {
        continue;
      }
      surfacesByMessageId.set(agentMessage.id, resolveCodexTranscriptSurface(sourceMessage, projectedCells));
    }
    transcriptCompactionCacheRef.current = compactCodexTranscriptCellsIncrementally(
      transcriptCompactionCacheRef.current,
      agentThread.messages.map((agentMessage) => ({
        messageId: agentMessage.id,
        cells: surfacesByMessageId.get(agentMessage.id)?.cells ?? [],
        barrier: agentMessage.role === "user",
      })),
    );
    const compactedCellsByMessageId = transcriptCompactionCacheRef.current.cellsByMessageId;
    for (const [messageId, surface] of surfacesByMessageId) {
      const compactedCells = compactedCellsByMessageId.get(messageId);
      if (!compactedCells || transcriptCellSequenceMatches(surface.cells, compactedCells)) {
        continue;
      }
      surfacesByMessageId.set(messageId, { ...surface, cells: compactedCells });
    }
    return surfacesByMessageId;
  }, [activeConversationMessagesById, agentOperationGroupsByMessageId, agentThread, agentTimelineItemsByMessageId]);
  const imageArtifactUrlsBeforeMessage = useMemo(() => {
    const urlsByMessageId = new Map<string, Set<string>>();
    const seenImageUrls = new Set<string>();
    for (const message of displayMessages) {
      urlsByMessageId.set(message.id, new Set(seenImageUrls));
      const artifact = imageArtifactForMessage(message);
      if (!artifact) {
        continue;
      }
      addComparableConversationImageUrl(seenImageUrls, artifact.imageUrl);
      addComparableConversationImageUrl(seenImageUrls, artifact.downloadUrl);
    }
    return urlsByMessageId;
  }, [displayMessages]);
  const latestToolCalls = useMemo(
    () => {
      for (const message of [...activeTimelineMessages].reverse()) {
        if (isTurnErrorMessage(message)) {
          continue;
        }
        const renderState = agentRenderStatesByMessageId.get(message.id);
        if (renderState?.toolCalls.length) {
          return renderState.toolCalls;
        }
      }
      return [];
    },
    [activeTimelineMessages, agentRenderStatesByMessageId],
  );
  const timelineScrollSignal = useMemo(
    () => buildTimelineScrollSignal(timelineMessages, agentRenderStatesByMessageId, {
      includeMentalSignals: showMentalSnapshots,
    }),
    [agentRenderStatesByMessageId, showMentalSnapshots, timelineMessages],
  );
  const streamingTimelineScrollSignal = useMemo(
    () => buildStreamingTimelineScrollSignal(streamingTimelineMessages, agentRenderStatesByMessageId, {
      includeMentalSignals: showMentalSnapshots,
    }),
    [agentRenderStatesByMessageId, showMentalSnapshots, streamingTimelineMessages],
  );
  streamingPaintMetricsRef.current = {
    ...conversationStreamingFrameIdentity(activeTurnMessage),
    streamingMessageCount: streamingTimelineMessages.length,
    renderedTextLength: streamingTimelineMessages.reduce(
      (total, message) => total + (agentRenderStatesByMessageId.get(message.id)?.renderedTextLength ?? 0),
      0,
    ),
  };
  const hasSessionMeta = resolvedStats.length > 0 || latestToolCalls.length > 0;
  const hasMetaSection = showSessionOverview && (hasSessionMeta || Boolean(supplementalContent));
  const operationStateLabels = useMemo<OperationStateLabels>(
    () => ({
      running: lang === "zh" ? "执行中" : "Running",
      failed: lang === "zh" ? "执行失败" : "Failed",
      degraded: lang === "zh" ? "降级运行" : "Process degraded",
      done: lang === "zh" ? "已完成" : "Done",
      pending: lang === "zh" ? "待处理" : "Pending",
      requesting: lang === "zh" ? "正在请求" : "Requesting",
      retrying: lang === "zh" ? "模型重试中" : "Retrying model",
      requestFailed: lang === "zh" ? "请求失败" : "Request failed",
      pendingRequest: lang === "zh" ? "等待请求" : "Pending request",
      thinking: lang === "zh" ? "正在思考中" : "Thinking",
      generating: lang === "zh" ? "生成中" : "Generating",
      processFailed: lang === "zh" ? "过程失败" : "Process failed",
      process: lang === "zh" ? "过程" : "Process",
      processPending: lang === "zh" ? "过程待处理" : "Process pending",
      thoughtProcess: t("thoughtProcess"),
      toolProcess: t("toolProcess"),
      mentalProcess: t("mentalProcess"),
      status: lang === "zh" ? "状态" : "Status",
    }),
    [lang, t],
  );
  function compactPreview(value: string, maxLength = 180) {
    return compactConversationPreview(value, maxLength);
  }

  // Stable identities: the markdown renderer is content-memoized, so a fresh
  // renderImage closure per render would force a full re-parse of every block.
  const openImagePreview = useCallback((image: ConversationImagePreviewRequest) => {
    setPreviewImage(image);
  }, []);

  const {
    computerUseSessionResults,
    computerUseSessionPending,
    renderComputerUseResult,
  } = useComputerUseResults({ lang, openImagePreview });

  const {
    composerSurface,
    composerStarters,
    handleStarterCardActivate,
    handleSendAndFollowLatest,
    resolvedSafeGuidanceLabel,
  } = useConversationComposer({
    sessionId,
    messages,
    transcriptPending,
    showComposer,
    composerVariant,
    composerValue,
    composerPlaceholder,
    composerDisabled,
    promptSuggestionEnabled,
    composerFocusSignal,
    onComposerFocusRequestSettled,
    composerActionDisabled,
    composerActionMode,
    composerPending,
    composerSafeGuidancePending,
    composerInterruptGuidancePending,
    composerError,
    composerGuidance,
    followupQueue,
    composerAttachments,
    composerReferences,
    slashCommandSuggestions,
    slashSkillsCatalogState,
    composerReferenceOptions,
    composerAttachmentInputDisabled,
    composerLeadingControl,
    permissionControl,
    llmControl,
    turnModelControl,
    onOpenAgentModelConfig,
    composerContextRing,
    onOpenComposerContextDetail,
    onCreateSession,
    onOpenSideChat,
    turnError,
    submitLabel,
    submitPendingLabel,
    stopLabel,
    stopPendingLabel,
    safeGuidanceLabel,
    safeGuidancePendingLabel,
    editingMessageId,
    composerModeNotice,
    composerModeTargetPreview,
    onComposerChange,
    onAddComposerAttachments,
    onRemoveComposerAttachment,
    onRetryComposerAttachment,
    onRetryComposerAttachmentUploads,
    onAddComposerReference,
    onRemoveComposerReference,
    onSubmit,
    onStop,
    onContinueTurn,
    onSafeGuidance,
    onFollowupQueueUpdate,
    onFollowupQueueRemove,
    onFollowupQueueMove,
    onFollowupQueueSteer,
    onFollowupQueueSendNow,
    followupQueueSteerLabel,
    composerInputRef,
    inlineEditInputRef,
    lang,
    t,
    timelineRef,
    followLatestRef,
    atBottomRef,
    userScrollIntentRef,
    userScrollIntentAtRef,
    setIsAtBottom,
    scrollTimelineToBottom,
    conversationFindOpen,
    closeConversationFind,
    openImagePreview,
  });


  function closeImagePreview() {
    setPreviewImage(null);
  }

  const {
    sectionExpansion,
    defaultExpandedResponseIds,
    preserveCurrentExpansionDefaults,
    resetSessionExpansion,
    getCachedResponseSegments,
    getExpansionState,
    toggleSection,
  } = useConversationProcessExpansion({
    sessionId,
    timelineMessages,
    activeTimelineMessages,
    agentRenderStatesByMessageId,
    agentTimelineItemsByMessageId,
    agentOperationGroupsByMessageId,
  });

  const {
    handleProcessDisclosureUserToggle,
    scrollToBottom,
    handleTurnNavigate,
  } = useConversationTimelineFollow({
    timelineFollowApiRef,
    sessionId,
    timelineRef,
    timelineContentRef,
    readingViewportAnchorRef,
    historyScrollAnchorRef,
    historyAnchorCorrectingRef,
    followLatestRef,
    atBottomRef,
    userScrollIntentRef,
    userScrollIntentAtRef,
    ignoreNextProgrammaticFollowRef,
    lastTimelineScrollTopRef,
    lastTimelineContentWidthRef,
    contentWidthChangingUntilRef,
    streamingScrollFrameRef,
    autoScrollToLatestRef,
    initializedSessionRef,
    pinnedLatestUserMessageIdRef,
    setIsAtBottom,
    autoScrollToLatest,
    latestUserMessageId,
    timelineScrollSignal,
    streamingTimelineScrollSignal,
    narrowTimelineViewport,
    activeTimelineMessages,
    displayMessages,
    earlierMessagesLoading,
    hasEarlierMessages,
    hiddenHistorySignalCount,
    onLoadEarlierMessages,
    visibleMessageCount,
    timelineLiveTailStartIndex,
    timelineVirtualizer,
    preserveCurrentExpansionDefaults,
  });



  useEffect(() => () => {
    if (copyAnswerFeedbackTimerRef.current !== null) {
      window.clearTimeout(copyAnswerFeedbackTimerRef.current);
    }
  }, []);

  useEffect(() => {
    if (!streamingTimelineScrollSignal || !onStreamingFramePaint) {
      return;
    }
    // Depend only on the scroll signal string — Map/array identity changes every
    // parent render and was re-firing paint telemetry (and layout work) with no content delta.
    const metrics = streamingPaintMetricsRef.current;
    onStreamingFramePaint({
      sessionId,
      turnId: metrics.turnId,
      ledgerSeq: metrics.ledgerSeq,
      assistantDeltaAppliedAtMs: metrics.assistantDeltaAppliedAtMs,
      paintedAtMs: conversationPerformanceNowMs(),
      streamingMessageCount: metrics.streamingMessageCount,
      renderedTextLength: metrics.renderedTextLength,
      scrollSignal: streamingTimelineScrollSignal,
    });
  }, [
    onStreamingFramePaint,
    sessionId,
    streamingTimelineScrollSignal,
  ]);

  useEffect(() => {
    if (!previewImage) {
      return undefined;
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setPreviewImage(null);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [previewImage]);


  useEffect(() => {
    readingViewportAnchorRef.current = null;
    historyScrollAnchorRef.current = null;
    historyAnchorCorrectingRef.current = null;
    resetSessionExpansion();
  }, [resetSessionExpansion, sessionId]);

  const {
    formatDuration,
    operationTone,
    operationStatusToneClassName,
    operationStatusIcon,
    operationStatusText,
    rolloutTraceEventLabel,
    operationLabel,
    operationGroupTitle,
    operationTimelineTitle,
    processSummaryIcon,
    hasOperationDetails,
    buildLegacyToolActivityPills,
  } = createConversationOperationRows({ lang, t, statusLabel, operationStateLabels });

  const {
    renderCodexThoughtScrollCell,
    renderCodexProgressCell,
    renderCodexReasoningSummaryCell,
    codexTranscriptVisibleSummary,
    codexTranscriptCellIcon,
    codexTranscriptCellTitle,
    codexTranscriptCellMeta,
  } = createCodexTranscriptCellRenderers({ lang, t, getExpansionState, toggleSection });

  const {
    codexTranscriptToolDetailRows,
    renderCodexTranscriptToolDetailContent,
    codexTranscriptToolDetailIsEmpty,
    renderRolloutTraceEvents,
  } = createConversationCodexToolDetails({
    lang,
    operationDetailLabels,
    rolloutTraceEventLabel,
    codexTranscriptCellTitle,
  });

  const {
    renderReActOperationContent,
    feedbackTimelineGroups,
    renderFeedbackTimelineDetails,
  } = createConversationReActRows({
    lang,
    t,
    getExpansionState,
    toggleSection,
    operationDetailLabels,
    renderComputerUseResult,
    formatDuration,
    buildLegacyToolActivityPills,
    operationLabel,
    operationStatusIcon,
    operationStatusText,
    operationStatusToneClassName,
    hasOperationDetails,
  });

  const {
    isCompactInternalStatusOperation,
    renderOperationTimeline,
    renderOperationGroup,
    renderFeedbackTimelineGroup,
  } = createConversationOperationGroups({
    lang,
    t,
    getExpansionState,
    toggleSection,
    operationStateLabels,
    operationDetailLabels,
    renderComputerUseResult,
    formatDuration,
    operationTone,
    operationStatusToneClassName,
    operationStatusIcon,
    operationStatusText,
    operationLabel,
    hasOperationDetails,
    operationGroupTitle,
    operationTimelineTitle,
    processSummaryIcon,
    feedbackTimelineGroups,
    renderFeedbackTimelineDetails,
  });

  function handleCopyAnswer(messageId: string, text: string) {
    const trimmed = text.trim();
    if (!trimmed) {
      return;
    }
    void copyTextToClipboard(trimmed).then(() => {
      setCopiedAnswerMessageId(messageId);
      if (copyAnswerFeedbackTimerRef.current !== null) {
        window.clearTimeout(copyAnswerFeedbackTimerRef.current);
      }
      copyAnswerFeedbackTimerRef.current = window.setTimeout(() => {
        copyAnswerFeedbackTimerRef.current = null;
        setCopiedAnswerMessageId((current) => (current === messageId ? "" : current));
      }, 1600);
    }).catch(() => undefined);
  }

  /** Bounded visible feedback for a rejected curation click (~3s on the title). */
  function showCurationFeedback(messageId: string, action: SessionMessageCurationAction, message: string) {
    setCurationFeedback({ messageId, action, message });
    if (curationFeedbackTimerRef.current !== null) {
      window.clearTimeout(curationFeedbackTimerRef.current);
    }
    curationFeedbackTimerRef.current = window.setTimeout(() => {
      curationFeedbackTimerRef.current = null;
      setCurationFeedback((current) => (current?.messageId === messageId ? null : current));
    }, 3000);
  }

  function handleCurateMessage(messageId: string, action: SessionMessageCurationAction) {
    if (!sessionId || resolveMessageCurationState(messageCurationMap, messageId) === action) {
      return;
    }
    // Optimistic flip; the query invalidation restores server authority on
    // success and the overlay entry is dropped again on failure (rollback).
    setCurationOverrides((current) => applyOptimisticCuration(current, messageId, action));
    void setSessionMessageCuration(sessionId, messageId, action)
      .then(() => {
        setCurationOverrides((current) => {
          if (!current.has(messageId)) {
            return current;
          }
          const next = new Map(current);
          next.delete(messageId);
          return next;
        });
        void queryClient.invalidateQueries({ queryKey: queryKeys.sessionMessageCuration(sessionId) });
      })
      .catch((error) => {
        setCurationOverrides((current) => {
          if (!current.has(messageId)) {
            return current;
          }
          const next = new Map(current);
          next.delete(messageId);
          return next;
        });
        showCurationFeedback(
          messageId,
          action,
          isFetchJsonHttpError(error) && error.message ? error.message : t("curationActionFailed"),
        );
      });
  }

  const renderMarkdownImage = useCallback((alt: string, url: string, duplicateImageUrls?: Set<string>) => {
    if (!isLikelyConversationImageUrl(url)) {
      return (
        <a className={styles.markdownImageLink} href={url}>
          {alt || url}
        </a>
      );
    }
    const previewUrl = conversationImagePreviewUrl(url);
    if (duplicateImageUrls?.has(comparableConversationImageUrl(url))) {
      return null;
    }
    const imageAlt = alt || (lang === "zh" ? "生成图片" : "Generated image");
    const previewLabel = lang === "zh" ? "预览图片" : "Preview image";
    return (
      <figure className={styles.markdownImageFigure}>
        <VButton
          type="button"
          className={styles.imagePreviewButton}
          onClick={() =>
            openImagePreview({
              src: previewUrl,
              alt: imageAlt,
              downloadUrl: url,
              downloadName: conversationImageDownloadName(url) || true,
            })
          }
          aria-label={previewLabel}
          title={previewLabel}
        >
          <img className={styles.markdownImage} src={previewUrl} alt={imageAlt} loading="lazy" />
        </VButton>
        <figcaption className={styles.markdownImageCaption}>
          {alt ? <span>{alt}</span> : null}
          <a
            className={styles.markdownImageLink}
            href={url}
            download={conversationImageDownloadName(url) || true}
          >
            {lang === "zh" ? "下载图片" : "Download image"}
          </a>
        </figcaption>
      </figure>
    );
  }, [lang, openImagePreview]);

  const {
    renderResponseSegment,
    renderResponseText,
    renderUserContentWithSlashEcho,
    renderAssistantTranscriptResponseText,
    renderAssistantFileReferenceChips,
  } = createConversationResponseBlocks({
    lang,
    t,
    sessionWorkspacePath,
    onOpenRailFile,
    renderMarkdownImage,
    slashCommandSuggestions,
  });

  const { renderAgentMessageTimeline } = createConversationTimelineItems({
    lang,
    t,
    getExpansionState,
    toggleSection,
    operationDetailLabels,
    renderComputerUseResult,
    imageArtifactUrlsBeforeMessage,
    getCachedResponseSegments,
    renderRolloutTraceEvents,
    isCompactInternalStatusOperation,
    renderResponseSegment,
    renderAssistantFileReferenceChips,
    formatDuration,
    operationStatusToneClassName,
    operationStatusIcon,
    operationStatusText,
    operationLabel,
    buildLegacyToolActivityPills,
    hasOperationDetails,
  });

  const { renderAgentMentalPanel } = createConversationAuxiliaryPanels({
    t,
    showMentalSnapshots,
    getExpansionState,
    toggleSection,
    formatTimestamp,
  });

  const { renderTimelineSpecialRow } = createConversationSpecialRows({
    lang,
    t,
    formatTimestamp,
  });

  const {
    turnWorkForceExpand,
    renderCodexTranscriptCells,
  } = createConversationCodexSurface({
    lang,
    phase,
    sessionId,
    toolApproval,
    toolApprovalConsumedRef,
    turnError,
    turnErrorSupersededByFinalAnswer,
    imageArtifactUrlsBeforeMessage,
    activeTimelineMessageOrder,
    handleProcessDisclosureUserToggle,
    showComposer,
    composerDisabled,
    composerValue,
    composerInputRef,
    onComposerChange,
    renderCodexProgressCell,
    renderCodexReasoningSummaryCell,
    codexTranscriptCellIcon,
    codexTranscriptCellTitle,
    codexTranscriptCellMeta,
    codexTranscriptVisibleSummary,
    renderCodexTranscriptToolDetailContent,
    codexTranscriptToolDetailIsEmpty,
    renderResponseText,
    renderAssistantTranscriptResponseText,
    renderAssistantFileReferenceChips,
  });

  const { renderTimelineRow } = createConversationTimelineRows({
    measureTimelineVirtualRow,
    activeTimelineMessages,
    activeTimelineRowIdentities,
    agentMessagesByMessageId,
    agentRenderStatesByMessageId,
    agentOperationGroupsByMessageId,
    agentCodexSurfacesByMessageId,
    defaultExpandedResponseIds,
    imageArtifactUrlsBeforeMessage,
    timelineModelSwitchBoundaries,
    messageCurationMap,
    sectionExpansion,
    computerUseSessionResults,
    computerUseSessionPending,
    companionTypingMessage,
    latestUserMessageId,
    editingMessageId,
    editUserMessageLabel,
    editUserMessageDisabled,
    composerPlaceholder,
    answerOnlyProcessMode,
    showMentalSnapshots,
    companionMode,
    lang,
    t,
    phase,
    assistantLabel,
    assistantAvatarImageUrl,
    assistantAvatarFallback,
    userLabel,
    userAvatarLabel,
    userAvatarImageUrl,
    operationLabels,
    resolveTurnAvatar,
    onEditUserMessage,
    onRegenerateAssistantMessage,
    onSwitchMessageVersion,
    branchVersionSwitchDisabled,
    regenerableAssistantMessageId,
    regenerateDisabled,
    regeneratePending,
    onForkSessionFromNode,
    onOpenComposerContextDetail,
    onCancelComposerMode,
    composerValue,
    onComposerChange,
    composerDisabled,
    composerError,
    submitLabel,
    cancelComposerModeLabel,
    inlineEditInputRef,
    copiedAnswerMessageId,
    curationFeedback,
    openForkDialog,
    formatTimestamp,
    compactPreview,
    conversationModelLabel,
    resolvedSafeGuidanceLabel,
    getCachedResponseSegments,
    getExpansionState,
    toggleSection,
    handleCopyAnswer,
    handleCurateMessage,
    handleSendAndFollowLatest,
    openImagePreview,
    renderTimelineSpecialRow,
    renderAgentMessageTimeline,
    renderOperationGroup,
    renderFeedbackTimelineGroup,
    renderFeedbackTimelineDetails,
    renderAgentMentalPanel,
    renderResponseText,
    renderUserContentWithSlashEcho,
    renderCodexTranscriptCells,
  });

  function isNonNullNode<T>(node: T | null): node is T {
    return node !== null;
  }


  return (
    <div
      ref={conversationSurfaceRef}
      className={[
        styles.surface,
        density === "compact" ? styles.surfaceCompact : "",
        className ?? "",
      ].filter(Boolean).join(" ")}
      data-agent-thread-id={agentThread.id}
      data-agent-thread-message-count={agentThread.messages.length}
      data-agent-thread-source-kind={agentThread.source.kind}
      data-agent-thread-status={agentThread.status}
    >
      {showHeader ? (
        <div className={styles.header}>
          <div>
            <p className={styles.eyebrow}>{eyebrowLabel ?? t("agentSession")}</p>
            <h2 className={styles.title}>{title}</h2>
          </div>
          <div className={styles.headerControls}>
            {headerActions}
            <span className={styles.phase}>{statusLabel(phase)}</span>
          </div>
        </div>
      ) : null}

      {showSessionOverview && resolvedSummaryItems.length > 0 ? (
        <div className={styles.summaryGrid}>
          {resolvedSummaryItems.map((item) => (
            <section key={item.label} className={styles.summaryCard}>
              <p className={styles.summaryLabel}>{item.label}</p>
              <p className={styles.summaryValue} title={item.value}>
                {item.value}
              </p>
            </section>
          ))}
        </div>
      ) : null}

      {hasMetaSection ? (
        <div className={styles.metaStack}>
          {hasSessionMeta ? (
            <div className={styles.sessionMeta}>
              {resolvedStats.length > 0 ? (
                <div className={styles.statRow}>
                  {resolvedStats.map((item) => (
                    <span key={item.label} className={styles.statPill}>
                      {item.label} {item.value}
                    </span>
                  ))}
                </div>
              ) : null}
              {latestToolCalls.length > 0 ? (
                <div className={styles.toolsBlock}>
                  <span className={styles.toolsLabel}>{t("activeToolsLabel")}</span>
                  <div className={styles.toolRow}>
                    {latestToolCalls.map((toolCall, index) => (
                      <span key={`${toolCall.name}-${index}`} className={styles.toolPill}>
                        {toolCall.name} · {statusLabel(toolCall.status)}
                      </span>
                    ))}
                  </div>
                </div>
              ) : null}
              {lastMessageTimestamp ? (
                <p className={styles.updateLine}>
                  {t("lastUpdated")} {formatTimestamp(lastMessageTimestamp)}
                </p>
              ) : null}
            </div>
          ) : null}

          {supplementalContent ? <div className={styles.supplemental}>{supplementalContent}</div> : null}
        </div>
      ) : null}

      <div ref={timelineAreaRef} className={styles.timelineArea}>
      <div
        ref={timelineRef}
        className={styles.timeline}
        data-conversation-following={followLatestRef.current ? "true" : "false"}
        data-conversation-reading-anchor={readingViewportAnchorRef.current?.rowKey ?? ""}
      >
        {displayMessages.length === 0 && !activeTurnMessage ? (
          transcriptPending ? (
            <ConversationTranscriptLoadingState label={t("sessionTranscriptLoading")} />
          ) : (
            <div className={styles.emptyStateHost}>
              <VStateSurface
                className={styles.emptyState}
                tone="empty"
                skeletonLines={false}
                title={t("sessionNoMessages")}
              />
              {messages.length === 0 && !composerDisabled && composerStarters.length > 0 ? (
                <div
                  className={styles.emptyStateStarters}
                  role="group"
                  aria-label={t("sessionStarterHeading")}
                  data-vui="conversation-starter-cards"
                >
                  <p className={styles.emptyStateStartersHeading}>
                    <Sparkles size={13} aria-hidden="true" />
                    <span>{t("sessionStarterHeading")}</span>
                  </p>
                  <div className={styles.emptyStateStarterGrid}>
                    {composerStarters.map((starter) => (
                      <VButton
                        key={starter.command}
                        type="button"
                        contentLayout="plain"
                        className={styles.emptyStateStarterCard}
                        data-vui="conversation-starter-card"
                        onPress={() => handleStarterCardActivate(starter)}
                      >
                        {starter.heading ? (
                          <span className={styles.emptyStateStarterCardHeading}>{starter.heading}</span>
                        ) : null}
                        <span className={styles.emptyStateStarterCardCommand}>{starter.command}</span>
                      </VButton>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          )
        ) : (
          <div ref={timelineContentRef} className={styles.timelineContent}>
            <div
              data-conversation-virtual-host="1"
              style={{
                height: timelineVirtualizer.getTotalSize(),
                position: "relative",
              }}
            >
            {timelineRowPlan
              .filter((row) => row.virtualStartPx !== null)
              .map((rowPlan) => renderTimelineRow(rowPlan))}
            </div>
            {timelineRowPlan
              .filter((row) => row.virtualStartPx === null)
              .map((rowPlan) => renderTimelineRow(rowPlan))}
            <ConversationRunningTasks sessionId={sessionId} />
            {companionTypingMessage ? (
              <div
                className={styles.companionTypingTurn}
                data-companion-typing-rail="assistant"
              >
                <div
                  className={styles.companionTypingAvatar}
                  data-companion-typing-avatar="true"
                  aria-hidden="true"
                >
                  <ConversationTurnAvatarContent
                    content={resolveMessageTurnAvatar(companionTypingMessage, {
                      resolveTurnAvatar,
                      assistantAvatarImageUrl,
                      assistantAvatarFallback,
                      assistantLabel,
                      userAvatarImageUrl,
                      userAvatarLabel,
                      agentInboxMessage: false,
                      groupTranscriptMessage: false,
                    })}
                  />
                </div>
                <div className={styles.companionTypingContent}>
                  <ConversationActiveTurnStatusNote
                    message={companionTypingMessage}
                    lang={lang}
                    phase={phase}
                    statusLabel={lang === "zh" ? "状态" : "Status"}
                    companionMode
                  />
                </div>
              </div>
            ) : null}
            {turnError?.message && !hasVisibleTurnErrorMessage && !turnErrorSupersededByFinalAnswer ? (
              <div className={styles.turnError} role="status" aria-live="polite">
                <div className={styles.turnErrorText}>
                  <span className={styles.turnErrorLabel}>{iterationLimitNotice ? (lang === "zh" ? "运行提示" : "Turn notice") : t("turnErrorLabel")}</span>
                  <span>{summarizeCurrentTurnError(turnError, lang)}</span>
                  <details className={styles.turnErrorDiagnostics}>
                    <summary className={styles.turnErrorDiagnosticsSummary}>
                      {lang === "zh" ? "诊断详情" : "Diagnostics"}
                    </summary>
                    <div className={styles.turnErrorDiagnosticsBody}>
                      {!iterationLimitNotice ? <span className={styles.turnErrorDetail}>{turnError.message}</span> : null}
                      {buildCurrentTurnErrorRows(turnError, lang).map((row) => (
                        <span key={`${row.label}-${row.value}`} className={styles.turnErrorDetail}>
                          {row.label}: {row.value}
                        </span>
                      ))}
                    </div>
                  </details>
                </div>
                <div className={styles.turnErrorActions}>
                  {turnError && resolveSessionTurnErrorRecoveryAction(turnError) === "compress_context" && onOpenComposerContextDetail ? (
                    <VButton
                      type="button"
                      contentLayout="plain"
                      className={styles.turnErrorRetryButton}
                      onClick={onOpenComposerContextDetail}
                      title={t("turnErrorActionCompressContextTitle")}
                      aria-label={t("turnErrorActionCompressContext")}
                    >
                      <Gauge size={12}/>
                      <span>{t("turnErrorActionCompressContext")}</span>
                    </VButton>
                  ) : null}
                  {onRetryTurn ? (
                    <VButton
                      type="button"
                      contentLayout="plain"
                      className={styles.turnErrorRetryButton}
                      onClick={onRetryTurn}
                      isDisabled={retryTurnDisabled}
                      isPending={retryTurnPending}
                      title={lang === "zh" ? "重试这一轮" : "Retry this turn"}
                      aria-label={lang === "zh" ? "重试这一轮" : "Retry this turn"}
                    >
                      <RefreshCw size={12}/>
                      <span>{lang === "zh" ? "重试" : "Retry"}</span>
                    </VButton>
                  ) : null}
                  {(() => {
                    const turnErrorTypeLabelKey = turnError && !iterationLimitNotice ? resolveTurnErrorTypeLabelKey(turnError.errorType) : "";
                    return turnErrorTypeLabelKey ? (
                      <span className={styles.turnErrorType} title={turnError?.errorType}>{t(turnErrorTypeLabelKey)}</span>
                    ) : null;
                  })()}
                </div>
              </div>
            ) : null}
          </div>
        )}
      </div>

{selectionQuoteMenu}

{!isAtBottom ? (
        <VButton
          type="button"
          contentLayout="plain"
          className={styles.backToBottomButton}
          onClick={scrollToBottom}
          title={t("backToBottom")}
          aria-label={t("backToBottom")}
        >
          <ArrowDown size={16} />
        </VButton>
      ) : null}

      {conversationFindOpen ? (
        <ConversationFindBar
          labels={conversationFindBarLabels}
          inputRef={conversationFindInputRef}
          value={conversationFindQuery}
          onValueChange={setConversationFindQuery}
          matchCount={conversationFindMatchCount}
          activeIndex={conversationFindActiveIndex}
          onPrevious={handleConversationFindPrevious}
          onNext={handleConversationFindNext}
          onClose={closeConversationFind}
        />
      ) : null}

      <ConversationTurnNavigator
        entries={timelineTurnNavEntries}
        currentIndex={timelineTurnNavCurrentIndex}
        ariaLabel={lang === "zh" ? "会话轮次导航" : "Turn navigation"}
        onNavigate={handleTurnNavigate}
        runningAssistantPreview={t("turnNavigatorRunningAssistant")}
      />
      </div>

      {toolApproval && !toolApprovalConsumedRef.current ? (
        <div className={styles.toolApprovalFallback} data-codex-tool-approval-fallback="true">
          {toolApproval.content}
        </div>
      ) : null}

      {composerSurface}
      {previewImage ? (
        <React.Suspense fallback={null}>
          <ConversationImagePreviewDialog image={previewImage} lang={lang} onClose={closeImagePreview} />
        </React.Suspense>
      ) : null}
      <ConversationForkSessionDialog
        open={Boolean(forkDialogMessage)}
        scope={forkScope}
        pending={forkPending}
        labels={{
          title: t("forkSessionDialogTitle"),
          description: t("forkSessionDialogDescription"),
          scopeLabel: t("forkSessionScopeLabel"),
          scopeVisiblePath: t("forkSessionScopeVisiblePath"),
          scopeWithBranches: t("forkSessionScopeWithBranches"),
          confirm: t("forkSessionConfirm"),
          pending: t("forkSessionPending"),
          cancel: t("forkSessionCancel"),
        }}
        onScopeChange={setForkScope}
        onConfirm={confirmForkSession}
        onCancel={closeForkDialog}
      />
    </div>
  );
});
