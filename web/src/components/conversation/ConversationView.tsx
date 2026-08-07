import {
  ArrowDown,
  ArrowUp,
  BrainCircuit,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleDot,
  ExternalLink,
  ImagePlus,
  Link2,
  LoaderCircle,
  Pencil,
  RefreshCw,
  Square,
  X,
  Search,
  Sparkles,
  TerminalSquare,
  Wrench,
} from "lucide-react";
import React, { DragEvent, ReactNode, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import type { ConversationMessage, SkillLibraryItem } from "../../api/types";
import type {
  AgentMessage,
  AgentMentalPart,
} from "../../agent-thread/types";
import { fetchJson } from "../../api/client";
import { VStateSurface } from "../../components/vui";
import { useAppI18n } from "../../i18n/useAppI18n";
import { ConversationImageArtifactView } from "./ConversationImageArtifactView";
import type { ConversationImagePreviewRequest } from "./ConversationImagePreviewDialog";
import { ConversationStreamingResponseContent } from "./ConversationStreamingResponseContent";
import { ConversationTranscriptLoadingState } from "./ConversationTranscriptLoadingState";
import { ConversationTurnAvatarContent } from "./ConversationTurnAvatarContent";
import {
  buildOperationDetailRows,
  DeferredOperationDetails,
  operationDetailsKind,
  readableOperationResult,
  type OperationDetailLabels,
  type OperationDetailRow,
} from "./ConversationOperationDetails";
import {
  buildMentalBodyRows,
  buildMentalMetaRows,
  latestAgentMentalPart,
  mentalSnapshotPreview,
  type MentalStateFormatters,
  type MentalStateLabels,
} from "./conversationMentalState";
import { AgentMessageTurnView } from "./AgentMessageTurnView";
import { AgentResponseSectionView } from "./AgentResponseSectionView";
import { AgentUserContentSectionView } from "./AgentUserContentSectionView";

/** T1: dialog/context chrome load only when opened — keep transcript path leaner. */
const ConversationImagePreviewDialog = React.lazy(() =>
  import("./ConversationImagePreviewDialog").then((module) => ({
    default: module.ConversationImagePreviewDialog,
  })),
);
const AgentContextSectionsView = React.lazy(() =>
  import("./AgentContextSectionsView").then((module) => ({
    default: module.AgentContextSectionsView,
  })),
);
import { shouldSubmitComposerOnKeydown } from "./composerShortcuts";
import {
  filterSlashCommandSuggestions,
  insertSlashCommandSuggestion,
} from "./conversationSlashCommandSuggestions";
import { buildAgentMessageRenderState, type AgentMessageRenderState } from "./agentMessageRenderState";
import {
  filterServerTimelineItemsForDisplayPlan,
  resolveAssistantDisplayPlan,
} from "./assistantDisplayPlan";
import {
  compactStreamingStatusPlaceholder,
  isInternalStreamingStatusStage,
  isNoFinalAnswerStatusContent,
  isStreamingStatusPlaceholderContent,
} from "./conversationInternalStatus";
import { ConversationActiveTurnStatusNote } from "./ConversationActiveTurnStatusNote";
import {
  operationGroupsWithFeedbackStatusPlaceholder,
} from "./conversationFeedbackStatusPresentation";
import { isInternalRuntimeStatus } from "./conversationDisplayProtocol";
import {
  buildAgentMessageOperationGroups,
  buildAgentMessageReActOperationGroups,
  type AgentMessageOperation,
  type AgentMessageOperationGroups,
  type AgentMessageOperationKind,
  type AgentMessageReActOperationGroup,
} from "./agentMessageOperations";
import {
  compactInternalProcessStateLabel,
  compactVisibleTimelineOperations,
  isLongLoopProgressOperation,
  isRunningOperationStatus,
  operationCollectionTone,
  operationDisplayLabel,
  operationStateLabel,
  operationStatusTone,
  processSummaryMeta,
  processSummaryPreview,
  processSummaryTitle,
  shouldShowTimelineOperation,
  type OperationStateLabels,
} from "./conversationOperationState";
import {
  reActActionOperations,
  reActResultItems,
  reActThoughtItems,
  shouldExpandReActGroupByDefault,
} from "./conversationReActOperationItems";
import {
  buildAgentMessageTimelineItems,
  type AgentMessageTimelineItem,
} from "./agentMessageTimeline";
import {
  buildCodexTranscriptCells,
  compactCodexTranscriptCellsAcrossMessages,
  settleCodexTranscriptActiveStatuses,
  type CodexTranscriptCell,
} from "./codexTranscriptCells";
import { resolveCodexTranscriptSurface, type CodexTranscriptSurface } from "./codexNativeTranscriptSurface";
import {
  buildCodexTranscriptTimelineNodes,
  codexTranscriptToolDurationSeconds,
  codexTranscriptToolRawName,
  createCodexTranscriptToolActivity,
  formatCodexTranscriptDuration,
  shouldAttachToolApprovalToActivity,
} from "./conversationToolActivityModel";
import { ConversationProcessDisclosure } from "./ConversationProcessDisclosure";
import {
  captureConversationProcessScrollAnchor,
  restoreConversationProcessScrollAnchor,
} from "./conversationProcessScrollAnchor";
import { ConversationToolActivity } from "./ConversationToolActivity";
import {
  ConversationToolActivityPills,
  toolActivityAriaTitle,
} from "./ConversationToolActivityPills";
import {
  buildConversationTerminalToolDetail,
  ConversationTerminalToolDetail,
} from "./ConversationTerminalToolDetail";
import { buildCodexRolloutTraceEvents, type CodexRolloutTraceEvent } from "./codexRolloutTrace";
import {
  preserveConversationExpansionDefaults,
  shouldRefreshConversationExpansionDefault,
} from "./conversationExpansionDefaults";
import { activeAgentMessageTimelineItemId } from "./agentMessageTimelineActiveItem";
import {
  agentMessageTimelineItemRowKey,
  type AgentMessageTimelineRowIdentity,
} from "./agentMessageTimelineRows";
import { useAgentThread } from "./useAgentThread";
import { projectAgentMessageTimelineMessages } from "./useAgentMessageTimelineProjection";
import { projectConversationDisplayMessages } from "./conversationDisplayMessages";
import {
  imageArtifactForMessage,
  isAgentInboxMessage,
  isCliAgentLifecycleMessage,
  isGroupRoomTranscriptMessage,
  isTurnErrorMessage,
  researchOrgMessageChips,
} from "./conversationMessagePredicates";
import {
  type AgentMessageSectionState,
} from "./agentMessageSections";
import {
  INITIAL_VISIBLE_MESSAGE_COUNT,
  nextVisibleMessageLimit,
  resolveVisibleMessageCount,
  shouldLoadEarlierConversationMessages,
  shouldPreferServerEarlierLoad,
  TIMELINE_HISTORY_LOAD_THRESHOLD_PX,
} from "./conversationHistoryWindow";
import { parseResponseSegments, ResponseSegment } from "./messageResponseSegments";
import { LazyConversationMarkdownRenderer } from "./LazyConversationMarkdownRenderer";
import { ConversationInferenceControl } from "./ConversationInferenceControl";
import {
  addComparableConversationImageUrl,
  comparableConversationImageUrl,
  conversationImageDownloadName,
  conversationImagePreviewUrl,
} from "./conversationImagePreview";
import { shouldShowNextStateSignalInConversation } from "./conversationNextStateSignal";
import {
  formatConversationDuration,
  formatConversationTimestamp,
} from "./conversationTimeFormat";
import {
  captureTimelineRowKeyAnchor,
  restoreTimelineRowKeyAnchor,
  type TimelineScrollRowKeyAnchor,
} from "./timelineScrollAnchor";
import {
  buildStreamingTimelineScrollSignal,
  buildTimelineScrollSignal,
} from "./conversationTimelineScrollSignals";
import {
  isTimelineNearBottom,
  recordConversationRowHeight,
  resolveConversationVirtualRange,
  resolveTimelineFollowState,
  shouldKeepFollowingLatestOnProcessToggle,
  shouldStickTimelineToBottomOnContentResize,
} from "./conversationTimelineFollowState";
import {
  peekSessionTimelineScroll,
  rememberSessionTimelineScroll,
  restoreSessionTimelineScroll,
} from "./conversationSessionScrollMemory";
import {
  conversationPerformanceNowMs,
  conversationTurnRowPropsAreEqual,
  transcriptCellSequenceMatches,
  type ConversationTurnRowProps,
} from "./conversationTurnRowMemo";
import {
  extractComposerImageDropFiles,
  extractComposerSessionReferenceDrop,
  hasComposerImageDragPayload,
  hasComposerSessionReferenceDragPayload,
} from "./conversationComposerDropPayload";
import {
  buildConversationTurnErrorReasonRows,
  buildTurnErrorDiagnosticRows,
  buildCurrentTurnErrorRows,
  summarizeCurrentTurnError,
  resolveConversationTurnErrorType,
} from "./conversationTurnErrorPresentation";
import {
  agentInboxSourceLabel,
  agentInboxSummary,
  cliAgentLifecycleDetail,
  cliAgentLifecycleLabel,
  groupRoomTranscriptLabel,
} from "./conversationSpecialMessagePresentation";
import { projectedConversationMessageIds } from "./conversationMessageIdentity";
import { shouldCompactConversationTurnHeader } from "./conversationTurnHeaderCompaction";
import {
  resolveMessageTurnAvatar,
  userAvatarSymbol,
  type TurnAvatarResolution,
} from "./conversationTurnAvatar";
import type { ConversationViewProps } from "./conversationViewTypes";
import { AgentPermissionPresetControl } from "../vui/product/agent-management";
import {
  buildComputerUseStateForMessage,
  computerUseResultForOperation,
  COMPUTER_USE_TOOL_NAME,
  type ComputerUseResult,
} from "./conversationComputerUseState";
import { formattedCodeBlockContent } from "./conversationFormattedCodeBlock";
import {
  isResponseSegmentCodeLike,
  responseSegmentLabel as resolveResponseSegmentLabel,
  shouldShowAgentResponseBlock as resolveShouldShowAgentResponseBlock,
} from "./conversationResponseSegmentPresentation";
import {
  compactConversationPreview,
  operationGroupTitle as resolveOperationGroupTitle,
  hasOperationDetails as resolveHasOperationDetails,
  operationStatusFallbackText,
  operationStatusIconKind,
  operationStatusToneClassNameFromTone,
  operationTimelineTitle as resolveOperationTimelineTitle,
  operationVisualTone,
  processSummaryIconKind,
  rolloutTraceEventLabel as resolveRolloutTraceEventLabel,
  shouldRenderCompactActiveTurnPlaceholder as resolveShouldRenderCompactActiveTurnPlaceholder,
} from "./conversationOperationPresentation";
import {
  resolveComposerActionDisabled,
  resolveComposerActionLabels,
  resolveComposerActionMode,
  resolveComposerEditMode,
  resolveComposerGuidanceUi,
  resolveComposerPrimaryActionFlags,
} from "./conversationComposerActionModel";
import { conversationOperationIconKind } from "./conversationOperationIconModel";
import { getCachedResponseSegments as getCachedResponseSegmentsFromCache } from "./conversationResponseSegmentCache";
import {
  buildCodexToolActivityPills,
  completedToolPresentationSummary,
  conversationToolDetailPresentation,
  conversationToolPresentationLabel,
  extractToolDisplayCommand,
  type CodexToolActivityPills,
} from "./conversationToolPresentation";
import { humanizeReasoningPreview } from "./conversationReasoningPreview";
import { VButton, VNativeInput, VNativeTextarea } from "../vui";
import styles from "./ConversationView.styles";

const DEFAULT_EXPANDED_RESPONSE_TAIL_COUNT = 3;
const INITIAL_VISIBLE_FEEDBACK_OPERATION_COUNT = 36;
const RESPONSE_PARSE_CACHE_LIMIT = 80;
const RESPONSE_PREWARM_MESSAGE_LIMIT = 8;
const EMPTY_SECTION_EXPANSION: Record<string, boolean> = {};

const ConversationTurnRow = React.memo(function ConversationTurnRow({
  renderTurn,
}: ConversationTurnRowProps) {
  return <>{renderTurn()}</>;
}, conversationTurnRowPropsAreEqual);

export function ConversationView({
  sessionId,
  title,
  phase,
  messages,
  activeTurnMessage,
  transcriptPending = false,
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
  changedFiles = [],
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
  autoScrollToLatest = true,
  hasEarlierMessages = false,
  earlierMessagesLoading = false,
  onStreamingFramePaint,
  composerValue,
  composerPlaceholder,
  composerDisabled,
  composerActionDisabled,
  composerActionMode,
  composerPending,
  composerSafeGuidancePending = false,
  composerInterruptGuidancePending = false,
  composerError,
  composerGuidance,
  composerAttachments = [],
  composerReferences = [],
  slashCommandSuggestions = [],
  composerAttachmentInputDisabled,
  permissionControl,
  toolApproval = null,
  llmControl,
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
  onAddComposerReference,
  onRemoveComposerReference,
  onEditUserMessage,
  onCancelComposerMode,
  onLoadEarlierMessages,
  onSubmit,
  onStop,
  onSafeGuidance,
  onInterruptGuidance,
}: ConversationViewProps) {
  void interruptGuidanceLabel;
  void interruptGuidancePendingLabel;
  void onInterruptGuidance;
  const { lang, t, statusLabel } = useAppI18n({ domains: ["chat"] });
  const timelineRef = useRef<HTMLDivElement | null>(null);
  const timelineContentRef = useRef<HTMLDivElement | null>(null);
  const historyScrollAnchorRef = useRef<TimelineScrollRowKeyAnchor | null>(null);
  /** Ensures a pending tool approval mounts under at most one tool activity per render. */
  const toolApprovalConsumedRef = useRef(false);
  toolApprovalConsumedRef.current = false;
  const composerInputRef = useRef<HTMLTextAreaElement | null>(null);
  const attachmentInputRef = useRef<HTMLInputElement | null>(null);
  const initializedSessionRef = useRef("");
  const pinnedLatestUserMessageIdRef = useRef("");
  const atBottomRef = useRef(true);
  const followLatestRef = useRef(true);
  const lastTimelineScrollTopRef = useRef(0);
  const streamingScrollFrameRef = useRef<number | null>(null);
  const autoScrollToLatestRef = useRef(autoScrollToLatest);
  autoScrollToLatestRef.current = autoScrollToLatest;
  const lastComposerFocusSignalRef = useRef("");
  const defaultExpansionRef = useRef<Record<string, Record<string, boolean>>>({});
  const responseSegmentCacheRef = useRef<Map<string, ResponseSegment[]>>(new Map());
  const [sectionExpansion, setSectionExpansion] = useState<Record<string, Record<string, boolean>>>({});
  const [isAtBottom, setIsAtBottom] = useState(true);
  const [previewImage, setPreviewImage] = useState<ConversationImagePreviewRequest | null>(null);
  const [composerDragActive, setComposerDragActive] = useState(false);
  const [visibleMessageLimit, setVisibleMessageLimit] = useState(INITIAL_VISIBLE_MESSAGE_COUNT);
  const [timelineVirtualMetrics, setTimelineVirtualMetrics] = useState({
    scrollTop: 0,
    viewportHeight: 720,
  });
  /** D2+: measured row heights by conversation row key. */
  const timelineRowHeightCacheRef = useRef<Map<string, number>>(new Map());
  const timelineRowResizeObserversRef = useRef<Map<string, ResizeObserver>>(new Map());
  const timelineRowNodesRef = useRef<Map<string, HTMLDivElement>>(new Map());
  /** Stable per-row ref callbacks so React does not null→node thrash ResizeObservers each render. */
  const timelineVirtualRowRefCallbacksRef = useRef<Map<string, (node: HTMLDivElement | null) => void>>(new Map());
  const timelineHeightBumpFrameRef = useRef<number | null>(null);
  const streamingPaintMetricsRef = useRef({ streamingMessageCount: 0, renderedTextLength: 0 });
  const [timelineRowHeightVersion, setTimelineRowHeightVersion] = useState(0);
  const [computerUseSessionResults, setComputerUseSessionResults] = useState<Record<string, ComputerUseResult>>({});
  const [computerUseSessionPending, setComputerUseSessionPending] = useState<Record<string, "confirm" | "cancel" | undefined>>({});
  const resolvedActionMode = resolveComposerActionMode(composerActionMode);
  const hasComposerAttachments = composerAttachments.length > 0;
  const hasComposerReferences = composerReferences.length > 0;
  const attachmentInputDisabled = composerAttachmentInputDisabled ?? composerDisabled;
  const resolvedActionDisabled = resolveComposerActionDisabled({
    actionMode: resolvedActionMode,
    composerActionDisabled,
    composerDisabled,
    composerValue,
    hasAttachments: hasComposerAttachments,
    hasReferences: hasComposerReferences,
  });
  const { actionLabel: resolvedActionLabel, pendingLabel: resolvedPendingLabel } = resolveComposerActionLabels({
    actionMode: resolvedActionMode,
    stopLabel,
    submitLabel,
    stopPendingLabel,
    submitPendingLabel,
    fallbackStop: t("stop"),
    fallbackSend: t("send"),
    fallbackStopPending: t("stopPending"),
    fallbackSendPending: t("sendPending"),
  });
  const assistantLabel = assistantDisplayName?.trim() || t("agent");
  const userLabel = userDisplayName?.trim() || t("operator");
  const userAvatarLabel = userAvatarSymbol(userAvatarPreset, userLabel);
  const {
    editModeActive: composerEditModeActive,
    failureNote: composerEditFailureNote,
  } = resolveComposerEditMode({
    modeNotice: composerModeNotice,
    modeTargetPreview: composerModeTargetPreview,
    turnErrorMessage: turnError?.message,
    compactPreview: compactConversationPreview,
    failureNotice: t("editMessageFailureRerunNotice"),
  });
  const { primaryActionIsEditSubmit, runningGuidanceActionsEnabled } = resolveComposerPrimaryActionFlags({
    actionMode: resolvedActionMode,
    editModeActive: composerEditModeActive,
  });
  // Edit/rerun is a labeled primary pill. Do not mix in round icon-only geometry
  // (composerRoundButtonPrimary forces fixed square size + icon-only slots).
  const primaryActionClassName = primaryActionIsEditSubmit
    ? styles.composerEditSubmitButton
    : `${styles.sendButton} ${styles.composerRoundButton} ${styles.composerRoundButtonPrimary}`;
  const {
    guidanceDraftReady,
    guidanceActionDisabled,
    showSafeGuidanceAction,
  } = resolveComposerGuidanceUi({
    runningGuidanceActionsEnabled,
    composerValue,
    composerDisabled,
    safeGuidancePending: composerSafeGuidancePending,
    interruptGuidancePending: composerInterruptGuidancePending,
  });
  const composerCanAcceptImageDrop = Boolean(onAddComposerAttachments) && !attachmentInputDisabled;
  const composerCanAcceptReferenceDrop = Boolean(onAddComposerReference) && !composerDisabled;
  const slashSuggestions = useMemo(
    () => filterSlashCommandSuggestions(slashCommandSuggestions, composerValue),
    [slashCommandSuggestions, composerValue],
  );
  const showSlashSuggestions = !composerDisabled && slashSuggestions.length > 0;
  const slashSuggestionListId = `conversation-${sessionId}-slash-suggestions`;
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

  useEffect(() => {
    if (!composerCanAcceptImageDrop && !composerCanAcceptReferenceDrop && composerDragActive) {
      setComposerDragActive(false);
    }
  }, [composerCanAcceptImageDrop, composerCanAcceptReferenceDrop, composerDragActive]);

  function handleSlashCommandSuggestion(skill: SkillLibraryItem) {
    onComposerChange(insertSlashCommandSuggestion(composerValue, skill.command));
    requestAnimationFrame(() => composerInputRef.current?.focus());
  }

  function handleComposerDragEnter(event: DragEvent<HTMLDivElement>) {
    const acceptsImage = composerCanAcceptImageDrop && hasComposerImageDragPayload(event.dataTransfer);
    const acceptsReference = composerCanAcceptReferenceDrop && hasComposerSessionReferenceDragPayload(event.dataTransfer);
    if (!acceptsImage && !acceptsReference) {
      return;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    setComposerDragActive(true);
  }

  function handleComposerDragOver(event: DragEvent<HTMLDivElement>) {
    const acceptsImage = composerCanAcceptImageDrop && hasComposerImageDragPayload(event.dataTransfer);
    const acceptsReference = composerCanAcceptReferenceDrop && hasComposerSessionReferenceDragPayload(event.dataTransfer);
    if (!acceptsImage && !acceptsReference) {
      return;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    setComposerDragActive(true);
  }

  function handleComposerDragLeave(event: DragEvent<HTMLDivElement>) {
    if (event.currentTarget.contains(event.relatedTarget as Node | null)) {
      return;
    }
    setComposerDragActive(false);
  }

  function handleComposerDrop(event: DragEvent<HTMLDivElement>) {
    const reference = composerCanAcceptReferenceDrop ? extractComposerSessionReferenceDrop(event.dataTransfer) : null;
    if (reference && onAddComposerReference) {
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
      setComposerDragActive(false);
      onAddComposerReference(reference);
      return;
    }
    if (!composerCanAcceptImageDrop || !onAddComposerAttachments) {
      setComposerDragActive(false);
      return;
    }
    const files = extractComposerImageDropFiles(event.dataTransfer);
    if (!files.length) {
      setComposerDragActive(false);
      return;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    setComposerDragActive(false);
    onAddComposerAttachments(files);
  }

  const latestUserMessage = useMemo(
    () =>
      [...messages]
        .reverse()
        .find((message) => message.role === "user")?.content ?? "",
    [messages],
  );
  const latestUserMessageId = useMemo(
    () =>
      [...messages]
        .reverse()
        .find((message) => message.role === "user")?.id ?? "",
    [messages],
  );
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
  const visibleMessageCount = resolveVisibleMessageCount({
    displayMessageCount: displayMessages.length,
    visibleLimit: visibleMessageLimit,
  });
  const hiddenRenderedMessageCount = displayMessages.length - visibleMessageCount;
  const hiddenHistorySignalCount = hiddenRenderedMessageCount + (hasEarlierMessages ? 1 : 0);
  const timelineMessages = useMemo(
    () => displayMessages.slice(displayMessages.length - visibleMessageCount),
    [displayMessages, visibleMessageCount],
  );
  const activeAgentMessageTimelineProjection = useMemo(
    () => projectAgentMessageTimelineMessages({ timelineMessages, activeTurnMessage }),
    [activeTurnMessage, timelineMessages],
  );
  const activeTimelineMessages = activeAgentMessageTimelineProjection.messages;
  const activeTimelineMessageOrder = useMemo(
    () => new Map(activeTimelineMessages.map((message, index) => [message.id, index])),
    [activeTimelineMessages],
  );
  const activeAgentMessages = activeAgentMessageTimelineProjection.agentMessages;
  const streamingTimelineMessages = activeAgentMessageTimelineProjection.streamingMessages;
  const activeTimelineRowIdentities = activeAgentMessageTimelineProjection.rowIdentities;
  const timelineMeasuredHeights = useMemo(() => {
    return activeTimelineRowIdentities.map((identity) => {
      const measured = timelineRowHeightCacheRef.current.get(identity.rowKey);
      return measured && measured > 0 ? measured : 0;
    });
  }, [activeTimelineRowIdentities, timelineRowHeightVersion]);
  const timelineVirtualRange = useMemo(
    () => resolveConversationVirtualRange({
      itemCount: activeTimelineMessages.length,
      scrollTop: timelineVirtualMetrics.scrollTop,
      viewportHeight: timelineVirtualMetrics.viewportHeight,
      followingLatest: followLatestRef.current,
      heights: timelineMeasuredHeights,
    }),
    [
      activeTimelineMessages.length,
      timelineVirtualMetrics.scrollTop,
      timelineVirtualMetrics.viewportHeight,
      isAtBottom,
      timelineMeasuredHeights,
    ],
  );
  const virtualTimelineMessages = useMemo(
    () => activeTimelineMessages.slice(timelineVirtualRange.start, timelineVirtualRange.end),
    [activeTimelineMessages, timelineVirtualRange.end, timelineVirtualRange.start],
  );
  const virtualTimelineRowIdentities = useMemo(
    () => activeTimelineRowIdentities.slice(timelineVirtualRange.start, timelineVirtualRange.end),
    [activeTimelineRowIdentities, timelineVirtualRange.end, timelineVirtualRange.start],
  );
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
      const sourceMessage = activeConversationMessagesById.get(agentMessage.source.id);
      const serverTimelineItems = sourceMessage?.timelineItems;
      const timelineHasAssistantText = (serverTimelineItems ?? []).some((item) => item.kind === "assistant_text");
      itemsByMessageId.set(
        agentMessage.id,
        buildAgentMessageTimelineItems(
          agentMessage,
          operations,
          { lang, includeAssistantText: timelineHasAssistantText },
          serverTimelineItems,
        ),
      );
    }
    return itemsByMessageId;
  }, [activeConversationMessagesById, agentOperationGroupsByMessageId, agentThread, lang]);
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
    const compactedCellsByMessageId = compactCodexTranscriptCellsAcrossMessages(
      agentThread.messages.map((agentMessage) => ({
        messageId: agentMessage.id,
        cells: surfacesByMessageId.get(agentMessage.id)?.cells ?? [],
        barrier: agentMessage.role === "user",
      })),
    );
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
  const defaultExpandedResponseIds = useMemo(() => {
    const ids = new Set<string>();
    let expandedResponseCount = 0;
    for (let index = activeTimelineMessages.length - 1; index >= 0; index -= 1) {
      const message = activeTimelineMessages[index];
      const agentRenderState = agentRenderStatesByMessageId.get(message.id);
      if (!agentRenderState?.sectionState.hasResponseBlock) {
        continue;
      }
      expandedResponseCount += 1;
      ids.add(message.id);
      for (const projectedId of projectedConversationMessageIds(message)) {
        ids.add(projectedId);
      }
      if (expandedResponseCount >= DEFAULT_EXPANDED_RESPONSE_TAIL_COUNT) {
        break;
      }
    }
    return ids;
  }, [activeTimelineMessages, agentRenderStatesByMessageId]);
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

  function openImagePreview(image: ConversationImagePreviewRequest) {
    setPreviewImage(image);
  }

  function closeImagePreview() {
    setPreviewImage(null);
  }

  function scrollTimelineToBottom(
    timeline: HTMLDivElement,
    options: { followLatest?: boolean; behavior?: ScrollBehavior } = {},
  ) {
    const wasAtBottom = atBottomRef.current;
    if (options.behavior) {
      timeline.scrollTo({ top: timeline.scrollHeight, behavior: options.behavior });
    } else {
      timeline.scrollTop = timeline.scrollHeight;
    }
    atBottomRef.current = true;
    if (options.followLatest) {
      followLatestRef.current = true;
    }
    lastTimelineScrollTopRef.current = timeline.scrollTop;
    if (!wasAtBottom) {
      setIsAtBottom(true);
    }
  }

  function scheduleTimelineScrollToBottom() {
    if (streamingScrollFrameRef.current !== null) {
      return;
    }
    streamingScrollFrameRef.current = window.requestAnimationFrame(() => {
      streamingScrollFrameRef.current = null;
      const timeline = timelineRef.current;
      if (!timeline || !followLatestRef.current) {
        return;
      }
      scrollTimelineToBottom(timeline);
    });
  }

  /**
   * ChatGPT/Claude: sending always re-pins the viewport to the latest turn.
   * Do this before onSubmit so optimistic user + active-turn paint under followLatest.
   */
  function pinFollowLatestForSubmit() {
    followLatestRef.current = true;
    atBottomRef.current = true;
    setIsAtBottom(true);
    const timeline = timelineRef.current;
    if (timeline) {
      scrollTimelineToBottom(timeline, { followLatest: true });
    }
    // Optimistic message height lands after React commit + virtual range rebuild.
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        if (!followLatestRef.current) {
          return;
        }
        const nextTimeline = timelineRef.current;
        if (nextTimeline) {
          scrollTimelineToBottom(nextTimeline, { followLatest: true });
        }
      });
    });
  }

  function handleSendAndFollowLatest() {
    pinFollowLatestForSubmit();
    onSubmit();
  }

  const handlePrimaryAction = resolvedActionMode === "stop"
    ? (onStop ?? onSubmit)
    : handleSendAndFollowLatest;

  const handleProcessDisclosureUserToggle = useCallback((summary: HTMLElement, _nextExpanded: boolean) => {
    const timeline = timelineRef.current;
    if (!timeline) {
      return undefined;
    }
    const keepFollowing = shouldKeepFollowingLatestOnProcessToggle({
      autoScrollToLatest: autoScrollToLatestRef.current,
      followingLatest: followLatestRef.current,
      scrollHeight: timeline.scrollHeight,
      clientHeight: timeline.clientHeight,
      scrollTop: timeline.scrollTop,
    });
    if (keepFollowing) {
      // Expanding near the tail: stay stuck to bottom so growth follows downward.
      followLatestRef.current = true;
      atBottomRef.current = true;
      setIsAtBottom(true);
      return () => {
        if (followLatestRef.current) {
          scrollTimelineToBottom(timeline);
        }
        lastTimelineScrollTopRef.current = timeline.scrollTop;
        setTimelineVirtualMetrics((current) => ({
          scrollTop: timeline.scrollTop,
          viewportHeight: timeline.clientHeight || current.viewportHeight,
        }));
      };
    }
    // Reading history: pin the summary so expand/collapse does not yank the viewport.
    const anchor = captureConversationProcessScrollAnchor(summary);
    atBottomRef.current = false;
    followLatestRef.current = false;
    lastTimelineScrollTopRef.current = timeline.scrollTop;
    setIsAtBottom(false);

    return () => {
      restoreConversationProcessScrollAnchor(timeline, summary, anchor);
      lastTimelineScrollTopRef.current = timeline.scrollTop;
      setTimelineVirtualMetrics((current) => ({
        scrollTop: timeline.scrollTop,
        viewportHeight: timeline.clientHeight || current.viewportHeight,
      }));
    };
  }, []);

  // Stick-to-bottom: re-pin when timeline viewport or content height changes while following.
  // Observe the inner content host — the scroll container's border box often stays fixed while
  // scrollHeight grows, so observing only `timeline` misses streaming / expand growth.
  useEffect(() => {
    const timeline = timelineRef.current;
    if (!timeline || typeof ResizeObserver === "undefined") {
      return undefined;
    }
    const observer = new ResizeObserver(() => {
      if (shouldStickTimelineToBottomOnContentResize({
        autoScrollToLatest: autoScrollToLatestRef.current,
        followingLatest: followLatestRef.current,
      })) {
        scheduleTimelineScrollToBottom();
      }
      setTimelineVirtualMetrics((current) => {
        const next = {
          scrollTop: timeline.scrollTop,
          viewportHeight: timeline.clientHeight || current.viewportHeight,
        };
        if (next.scrollTop === current.scrollTop && next.viewportHeight === current.viewportHeight) {
          return current;
        }
        return next;
      });
    });
    observer.observe(timeline);
    const content = timelineContentRef.current;
    if (content) {
      observer.observe(content);
    }
    return () => observer.disconnect();
  }, [sessionId, activeTimelineMessages.length > 0]);

  useEffect(() => {
    timelineRowHeightCacheRef.current.clear();
    for (const observer of timelineRowResizeObserversRef.current.values()) {
      observer.disconnect();
    }
    timelineRowResizeObserversRef.current.clear();
    timelineRowNodesRef.current.clear();
    timelineVirtualRowRefCallbacksRef.current.clear();
    setTimelineRowHeightVersion((version) => version + 1);
  }, [sessionId]);

  const scheduleTimelineHeightVersionBump = useCallback(() => {
    if (timelineHeightBumpFrameRef.current !== null) {
      return;
    }
    timelineHeightBumpFrameRef.current = window.requestAnimationFrame(() => {
      timelineHeightBumpFrameRef.current = null;
      setTimelineRowHeightVersion((version) => version + 1);
      // Row measure can change scrollHeight without resizing the scroll container box.
      // While following latest, re-pin so expand/stream growth stays on the tail.
      if (shouldStickTimelineToBottomOnContentResize({
        autoScrollToLatest: autoScrollToLatestRef.current,
        followingLatest: followLatestRef.current,
      })) {
        scheduleTimelineScrollToBottom();
      }
    });
  }, []);

  const bindTimelineVirtualRow = useCallback((rowKey: string, node: HTMLDivElement | null) => {
    const key = String(rowKey || "").trim();
    if (!key) {
      return;
    }
    if (!node) {
      const previous = timelineRowResizeObserversRef.current.get(key);
      if (previous) {
        previous.disconnect();
        timelineRowResizeObserversRef.current.delete(key);
      }
      timelineRowNodesRef.current.delete(key);
      return;
    }
    // Inline ref callbacks change identity every render; React then does null→node.
    // Skip rebind when we already observe this exact node to avoid measure thrash.
    if (
      timelineRowNodesRef.current.get(key) === node
      && timelineRowResizeObserversRef.current.has(key)
    ) {
      return;
    }
    const previous = timelineRowResizeObserversRef.current.get(key);
    if (previous) {
      previous.disconnect();
      timelineRowResizeObserversRef.current.delete(key);
    }
    if (typeof ResizeObserver === "undefined") {
      timelineRowNodesRef.current.set(key, node);
      return;
    }
    const publish = (height: number) => {
      // Following latest: spinner / subpixel reflow often jitters 2–6px; ignore that noise.
      const minDeltaPx = followLatestRef.current ? 8 : 2;
      if (recordConversationRowHeight(timelineRowHeightCacheRef.current, key, height, { minDeltaPx })) {
        scheduleTimelineHeightVersionBump();
      }
    };
    publish(node.getBoundingClientRect().height);
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      const height = entry?.borderBoxSize?.[0]?.blockSize
        ?? entry?.contentRect?.height
        ?? node.getBoundingClientRect().height;
      publish(height);
    });
    observer.observe(node);
    timelineRowResizeObserversRef.current.set(key, observer);
    timelineRowNodesRef.current.set(key, node);
  }, [scheduleTimelineHeightVersionBump]);
  const bindTimelineVirtualRowLatestRef = useRef(bindTimelineVirtualRow);
  bindTimelineVirtualRowLatestRef.current = bindTimelineVirtualRow;

  const timelineVirtualRowRef = useCallback((rowKey: string) => {
    const key = String(rowKey || "").trim();
    if (!key) {
      return (_node: HTMLDivElement | null) => undefined;
    }
    const existing = timelineVirtualRowRefCallbacksRef.current.get(key);
    if (existing) {
      return existing;
    }
    const callback = (node: HTMLDivElement | null) => {
      bindTimelineVirtualRowLatestRef.current(key, node);
    };
    timelineVirtualRowRefCallbacksRef.current.set(key, callback);
    return callback;
  }, []);

  useLayoutEffect(() => {
    const anchor = historyScrollAnchorRef.current;
    if (!anchor) {
      return;
    }
    historyScrollAnchorRef.current = null;
    if (restoreTimelineRowKeyAnchor(timelineRef.current, anchor)) {
      atBottomRef.current = false;
      followLatestRef.current = false;
      lastTimelineScrollTopRef.current = timelineRef.current?.scrollTop ?? 0;
      setIsAtBottom(false);
    }
  }, [activeTimelineMessages.length, visibleMessageLimit]);

  useLayoutEffect(() => {
    const timeline = timelineRef.current;
    if (!timeline) {
      return;
    }
    if (initializedSessionRef.current !== sessionId) {
      initializedSessionRef.current = sessionId;
      pinnedLatestUserMessageIdRef.current = latestUserMessageId;
      // Codex resume: restore mid-history viewport when revisiting a thread.
      const saved = peekSessionTimelineScroll(sessionId);
      const restored = restoreSessionTimelineScroll(timeline, saved);
      if (restored.restored) {
        followLatestRef.current = false;
        atBottomRef.current = false;
        setIsAtBottom(false);
        lastTimelineScrollTopRef.current = restored.scrollTop;
        setTimelineVirtualMetrics({
          scrollTop: restored.scrollTop,
          viewportHeight: timeline.clientHeight || 720,
        });
        // Sticky→full hydrate and virtual row measure can grow height after first paint.
        window.requestAnimationFrame(() => {
          const nextTimeline = timelineRef.current;
          if (!nextTimeline || followLatestRef.current) {
            return;
          }
          const again = restoreSessionTimelineScroll(nextTimeline, saved);
          lastTimelineScrollTopRef.current = again.scrollTop;
        });
        return;
      }
      scrollTimelineToBottom(timeline, { followLatest: true });
      return;
    }
    // New outbound user turn (send / edit-resubmit that keeps identity still updates
    // content via timelineScrollSignal; a brand-new latest user id always rejoins the tail).
    const latestUserChanged = Boolean(latestUserMessageId)
      && latestUserMessageId !== pinnedLatestUserMessageIdRef.current;
    if (latestUserChanged) {
      pinnedLatestUserMessageIdRef.current = latestUserMessageId;
      if (autoScrollToLatest) {
        scrollTimelineToBottom(timeline, { followLatest: true });
        return;
      }
    }
    if (!autoScrollToLatest) {
      return;
    }
    // Content growth while still near the bottom re-enables follow even if a prior
    // expand briefly suspended it.
    if (
      !followLatestRef.current
      && isTimelineNearBottom({
        scrollHeight: timeline.scrollHeight,
        clientHeight: timeline.clientHeight,
        scrollTop: timeline.scrollTop,
      })
    ) {
      followLatestRef.current = true;
      atBottomRef.current = true;
      setIsAtBottom(true);
    }
    if (followLatestRef.current) {
      scheduleTimelineScrollToBottom();
    }
  }, [autoScrollToLatest, latestUserMessageId, sessionId, timelineScrollSignal]);

  useEffect(() => {
    if (!streamingTimelineScrollSignal || !autoScrollToLatest || !followLatestRef.current) {
      return undefined;
    }
    scheduleTimelineScrollToBottom();
    return undefined;
  }, [autoScrollToLatest, sessionId, streamingTimelineScrollSignal]);

  useEffect(() => () => {
    if (streamingScrollFrameRef.current !== null) {
      window.cancelAnimationFrame(streamingScrollFrameRef.current);
      streamingScrollFrameRef.current = null;
    }
    // Capture leave-viewport scroll even when scroll listener already detached.
    rememberSessionTimelineScroll(sessionId, {
      scrollTop: lastTimelineScrollTopRef.current,
      followingLatest: followLatestRef.current,
    });
  }, [sessionId]);

  useEffect(() => {
    if (!streamingTimelineScrollSignal || !onStreamingFramePaint) {
      return;
    }
    // Depend only on the scroll signal string — Map/array identity changes every
    // parent render and was re-firing paint telemetry (and layout work) with no content delta.
    const metrics = streamingPaintMetricsRef.current;
    onStreamingFramePaint({
      sessionId,
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
    const timeline = timelineRef.current;
    if (!timeline) {
      return;
    }
    const handleScroll = () => {
      const previousScrollTop = lastTimelineScrollTopRef.current;
      if (shouldLoadEarlierConversationMessages({
        clientHeight: timeline.clientHeight,
        hiddenMessageCount: hiddenHistorySignalCount,
        previousScrollTop,
        scrollHeight: timeline.scrollHeight,
        scrollTop: timeline.scrollTop,
        thresholdPx: TIMELINE_HISTORY_LOAD_THRESHOLD_PX,
      })) {
        revealEarlierTimelineMessages();
      }
      const nextState = resolveTimelineFollowState({
        scrollHeight: timeline.scrollHeight,
        clientHeight: timeline.clientHeight,
        scrollTop: timeline.scrollTop,
        previousScrollTop,
        wasFollowingLatest: followLatestRef.current,
      });
      lastTimelineScrollTopRef.current = timeline.scrollTop;
      atBottomRef.current = nextState.isAtBottom;
      followLatestRef.current = nextState.shouldFollowLatest;
      setIsAtBottom(nextState.isAtBottom);
      setTimelineVirtualMetrics({
        scrollTop: timeline.scrollTop,
        viewportHeight: timeline.clientHeight || 720,
      });
      rememberSessionTimelineScroll(sessionId, {
        scrollTop: timeline.scrollTop,
        followingLatest: nextState.shouldFollowLatest,
      });
    };
    handleScroll();
    timeline.addEventListener("scroll", handleScroll);
    return () => {
      timeline.removeEventListener("scroll", handleScroll);
      rememberSessionTimelineScroll(sessionId, {
        scrollTop: lastTimelineScrollTopRef.current,
        followingLatest: followLatestRef.current,
      });
    };
  }, [
    displayMessages.length,
    earlierMessagesLoading,
    hasEarlierMessages,
    hiddenHistorySignalCount,
    onLoadEarlierMessages,
    sessionId,
    visibleMessageCount,
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
    const focusSignal = String(editingMessageId || "").trim();
    if (!focusSignal || focusSignal === lastComposerFocusSignalRef.current || composerDisabled) {
      return;
    }
    lastComposerFocusSignalRef.current = focusSignal;
    const input = composerInputRef.current;
    if (!input) {
      return;
    }
    input.focus();
    const cursorPosition = input.value.length;
    input.setSelectionRange(cursorPosition, cursorPosition);
  }, [composerDisabled, editingMessageId]);

  useEffect(() => {
    setVisibleMessageLimit(INITIAL_VISIBLE_MESSAGE_COUNT);
    historyScrollAnchorRef.current = null;
    defaultExpansionRef.current = {};
    responseSegmentCacheRef.current.clear();
    setSectionExpansion({});
  }, [sessionId]);

  useEffect(() => {
    const prewarmMessages = timelineMessages
      .filter(
        (message) => {
          const agentRenderState = agentRenderStatesByMessageId.get(message.id);
          return message.role === "assistant"
            && !message.streaming
            && Boolean(agentRenderState?.sectionState.hasResponseBlock);
        },
      )
      .slice(-RESPONSE_PREWARM_MESSAGE_LIMIT);
    if (!prewarmMessages.length) {
      return undefined;
    }
    let cancelled = false;
    let timeoutId: number | undefined;
    let index = 0;
    const prewarmNext = () => {
      if (cancelled) {
        return;
      }
      const message = prewarmMessages[index];
      if (message) {
        getCachedResponseSegments(message.content);
      }
      index += 1;
      if (index < prewarmMessages.length) {
        timeoutId = window.setTimeout(prewarmNext, 24);
      }
    };
    timeoutId = window.setTimeout(prewarmNext, 48);
    return () => {
      cancelled = true;
      if (timeoutId !== undefined) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [agentRenderStatesByMessageId, sessionId, timelineMessages]);

  function getCachedResponseSegments(content: string) {
    return getCachedResponseSegmentsFromCache(
      responseSegmentCacheRef.current,
      content,
      RESPONSE_PARSE_CACHE_LIMIT,
    );
  }

  function getExpansionState(messageId: string, section: string, defaultExpanded: boolean) {
    const explicit = sectionExpansion[messageId]?.[section];
    if (explicit !== undefined) {
      return explicit;
    }
    const messageDefaults = defaultExpansionRef.current[messageId] ?? {};
    if (messageDefaults[section] === undefined) {
      defaultExpansionRef.current = {
        ...defaultExpansionRef.current,
        [messageId]: {
          ...messageDefaults,
          [section]: defaultExpanded,
        },
      };
      return defaultExpanded;
    }
    if (shouldRefreshConversationExpansionDefault(section, messageDefaults[section], defaultExpanded)) {
      defaultExpansionRef.current = {
        ...defaultExpansionRef.current,
        [messageId]: {
          ...messageDefaults,
          [section]: defaultExpanded,
        },
      };
      return defaultExpanded;
    }
    return messageDefaults[section];
  }

  function resolveExpansionState(
    expansion: Record<string, Record<string, boolean>>,
    messageId: string,
    section: string,
    defaultExpanded: boolean,
  ) {
    const explicit = expansion[messageId]?.[section];
    if (explicit !== undefined) {
      return explicit;
    }
    const messageDefaults = defaultExpansionRef.current[messageId] ?? {};
    if (messageDefaults[section] !== undefined) {
      return messageDefaults[section];
    }
    return defaultExpanded;
  }

  function toggleSection(messageId: string, section: string, defaultExpanded: boolean) {
    setSectionExpansion((current) => {
      const currentlyExpanded = resolveExpansionState(current, messageId, section, defaultExpanded);
      return {
        ...current,
        [messageId]: {
          ...(current[messageId] ?? {}),
          [section]: !currentlyExpanded,
        },
      };
    });
  }

  function reasoningExpansionSectionId(cell: Pick<CodexTranscriptCell, "id" | "sourceItemId">) {
    // Prefer sourceItemId so stream updates that rewrite cell.id keep the same open/closed choice.
    const stable = String(cell.sourceItemId || cell.id || "").trim();
    return `reasoning:${stable || "active"}`;
  }

  function scrollToBottom() {
    const timeline = timelineRef.current;
    if (!timeline) {
      return;
    }
    scrollTimelineToBottom(timeline, { followLatest: true, behavior: "smooth" });
  }

  function revealEarlierTimelineMessages() {
    const preferServerEarlier = shouldPreferServerEarlierLoad({
      visibleMessageCount,
      displayMessageCount: displayMessages.length,
      hasEarlierMessages: Boolean(hasEarlierMessages),
      earlierMessagesLoading: Boolean(earlierMessagesLoading),
    });
    if (preferServerEarlier && onLoadEarlierMessages) {
      // U5: once the local window is large, prefer server pages over only growing DOM.
      preserveCurrentExpansionDefaults();
      historyScrollAnchorRef.current = captureTimelineRowKeyAnchor(timelineRef.current);
      atBottomRef.current = false;
      followLatestRef.current = false;
      setIsAtBottom(false);
      setVisibleMessageLimit((current) => nextVisibleMessageLimit({
        currentLimit: current,
        displayMessageCount: Math.max(displayMessages.length, current + 1),
      }));
      onLoadEarlierMessages();
      return;
    }
    if (visibleMessageCount >= displayMessages.length) {
      return;
    }
    preserveCurrentExpansionDefaults();
    historyScrollAnchorRef.current = captureTimelineRowKeyAnchor(timelineRef.current);
    atBottomRef.current = false;
    followLatestRef.current = false;
    setIsAtBottom(false);
    setVisibleMessageLimit((current) => nextVisibleMessageLimit({
      currentLimit: current,
      displayMessageCount: displayMessages.length,
    }));
  }

  function preserveCurrentExpansionDefaults() {
    defaultExpansionRef.current = preserveConversationExpansionDefaults({
      currentDefaults: defaultExpansionRef.current,
      sectionExpansion,
      messages: activeTimelineMessages,
      renderStatesByMessageId: agentRenderStatesByMessageId,
      timelineItemsByMessageId: agentTimelineItemsByMessageId,
      operationGroupsByMessageId: agentOperationGroupsByMessageId,
      defaultExpandedResponseIds,
    });
  }

  const formatDuration = formatConversationDuration;

  function operationIcon(kind: AgentMessageOperationKind, label: string) {
    switch (conversationOperationIconKind(kind, label)) {
      case "thought":
        return <Sparkles size={17} />;
      case "mental":
        return <BrainCircuit size={17} />;
      case "search":
        return <Search size={17} />;
      case "link":
        return <ExternalLink size={17} />;
      case "terminal":
        return <TerminalSquare size={17} />;
      case "tool":
      default:
        return <Wrench size={17} />;
    }
  }

  function operationTone(operation: AgentMessageOperation) {
    return operationVisualTone(operation);
  }

  function operationStatusToneClassName(operation: AgentMessageOperation) {
    return operationStatusToneClassNameFromTone(operationStatusTone(operation));
  }

  function operationStatusIcon(operation: AgentMessageOperation, animateRunning = true) {
    const status = operation.status.trim().toLowerCase();
    switch (operationStatusIconKind(status, isRunningOperationStatus(status), animateRunning)) {
      case "done":
        return <CheckCircle2 size={14} />;
      case "running":
        return <LoaderCircle className={styles.statusSpinner} size={14} />;
      case "running_static":
      case "idle":
      default:
        return <CircleDot size={14} />;
    }
  }

  function operationStatusText(status: string) {
    return operationStatusFallbackText(status, lang, statusLabel);
  }

  function rolloutTraceEventLabel(kind: CodexRolloutTraceEvent["kind"]) {
    return resolveRolloutTraceEventLabel(kind, lang);
  }

  function renderRolloutTraceEvents(operation: AgentMessageOperation) {
    if (operation.kind !== "tool") {
      return null;
    }
    if (operationStatusTone(operation) === "done") {
      return null;
    }
    const events = buildCodexRolloutTraceEvents(operation);
    if (events.length === 0) {
      return null;
    }
    return (
      <ol className={styles.rolloutTraceList} aria-label={lang === "zh" ? "工具生命周期" : "Tool lifecycle"}>
        {events.map((event) => {
          const eventClassName = [
            styles.rolloutTraceItem,
            styles[`rolloutTraceItem_${event.status}`],
          ].filter(Boolean).join(" ");
          const detailText = [
            event.error,
            event.exitCode !== undefined && event.exitCode !== null ? `exit ${event.exitCode}` : "",
            event.timedOut ? (lang === "zh" ? "已超时" : "timed out") : "",
          ].filter(Boolean).join(" · ");
          return (
            <li
              key={event.id}
              className={eventClassName}
              data-rollout-trace-kind={event.kind}
              data-rollout-trace-status={event.status}
              data-rollout-tool-call-id={event.toolCallId}
              data-rollout-terminal-operation-id={event.terminalOperationId}
              data-rollout-terminal-id={event.terminalId}
            >
              <span className={styles.rolloutTraceDot} aria-hidden="true" />
              <span className={styles.rolloutTraceText}>
                <span className={styles.rolloutTraceTitle}>{rolloutTraceEventLabel(event.kind)}</span>
                {detailText ? <span className={styles.rolloutTraceMeta}>{detailText}</span> : null}
              </span>
            </li>
          );
        })}
      </ol>
    );
  }

  function operationLabel(operation: AgentMessageOperation) {
    return operationDisplayLabel(operation, operationStateLabels);
  }

  function operationGroupTitle(kind: AgentMessageOperationKind, count: number) {
    return resolveOperationGroupTitle(kind, count, {
      thoughtProcess: t("thoughtProcess"),
      mentalProcess: t("mentalProcess"),
      toolProcess: t("toolProcess"),
    });
  }

  function operationTimelineTitle(operations: AgentMessageOperation[]) {
    return resolveOperationTimelineTitle(operations, lang, {
      thoughtProcess: t("thoughtProcess"),
      mentalProcess: t("mentalProcess"),
      toolProcess: t("toolProcess"),
    });
  }

  function processSummaryIcon(tone: string) {
    switch (processSummaryIconKind(tone)) {
      case "failed":
        return <TerminalSquare size={14} />;
      case "done":
        return <CheckCircle2 size={14} />;
      case "running":
      case "degraded":
      case "default":
      default:
        return <CircleDot size={14} />;
    }
  }

  function hasOperationDetails(operation: AgentMessageOperation) {
    return resolveHasOperationDetails(operation);
  }

  function renderComputerUseResult(operation: AgentMessageOperation) {
    const result = computerUseResultForOperation(operation, computerUseSessionResults);
    if (!result) {
      return null;
    }
    const previewLabel = lang === "zh" ? "预览沙盒截图" : "Preview sandbox screenshot";
    const confirmLabel = lang === "zh" ? "确认继续" : "Confirm";
    const cancelLabel = lang === "zh" ? "停止任务" : "Stop";
    const pendingAction = computerUseSessionPending[result.sessionId];
    const imageAlt = result.summary || (lang === "zh" ? "Computer Use 沙盒截图" : "Computer Use sandbox screenshot");
    const confirmSession = () => {
      setComputerUseSessionPending((current) => ({ ...current, [result.sessionId]: "confirm" }));
      void fetchJson<ComputerUseResult>(`/api/computer-use/sessions/${encodeURIComponent(result.sessionId)}/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirmation: "approved_from_chat" }),
      })
        .then((payload) => {
          setComputerUseSessionResults((current) => ({ ...current, [result.sessionId]: payload }));
        })
        .catch((error) => {
          setComputerUseSessionResults((current) => ({
            ...current,
            [result.sessionId]: {
              ...result,
              error: error instanceof Error ? error.message : String(error),
            },
          }));
        })
        .finally(() => {
          setComputerUseSessionPending((current) => ({ ...current, [result.sessionId]: undefined }));
        });
    };
    const cancelSession = () => {
      setComputerUseSessionPending((current) => ({ ...current, [result.sessionId]: "cancel" }));
      void fetchJson<ComputerUseResult>(`/api/computer-use/sessions/${encodeURIComponent(result.sessionId)}/cancel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: "cancelled_from_chat" }),
      })
        .then((payload) => {
          setComputerUseSessionResults((current) => ({ ...current, [result.sessionId]: payload }));
        })
        .catch((error) => {
          setComputerUseSessionResults((current) => ({
            ...current,
            [result.sessionId]: {
              ...result,
              error: error instanceof Error ? error.message : String(error),
            },
          }));
        })
        .finally(() => {
          setComputerUseSessionPending((current) => ({ ...current, [result.sessionId]: undefined }));
        });
    };
    return (
      <section className={styles.computerUsePanel}>
        <div className={styles.computerUseHeader}>
          <span>{result.status || "computer_use"}</span>
          <code>{result.sessionId}</code>
        </div>
        {result.summary ? <p className={styles.computerUseSummary}>{result.summary}</p> : null}
        {result.screenshotUrl ? (
          <VButton
            type="button"
            className={`${styles.imageArtifactFrame} ${styles.imagePreviewButton}`}
            onClick={() =>
              openImagePreview({
                src: result.screenshotUrl,
                alt: imageAlt,
                downloadUrl: result.screenshotUrl,
                downloadName: true,
              })
            }
            aria-label={previewLabel}
            title={previewLabel}
          >
            <img className={styles.computerUseScreenshot} src={result.screenshotUrl} alt={imageAlt} loading="lazy" />
          </VButton>
        ) : null}
        {result.steps.length > 0 ? (
          <ol className={styles.computerUseSteps}>
            {result.steps.slice(0, 6).map((step, index) => (
              <li key={`${result.sessionId}-${step.index ?? index}`}>
                <span>{step.action || step.status || `${index + 1}`}</span>
                <p>{step.summary || step.status || ""}</p>
              </li>
            ))}
          </ol>
        ) : null}
        {result.error ? <p className={styles.computerUseError}>{result.error}</p> : null}
        {result.needsConfirmation || result.status === "running" ? (
          <div className={styles.computerUseActions}>
            {result.needsConfirmation ? (
              <VButton type="button" onClick={confirmSession} isDisabled={Boolean(pendingAction)}>
                {pendingAction === "confirm" ? (lang === "zh" ? "确认中" : "Confirming") : confirmLabel}
              </VButton>
            ) : null}
            <VButton type="button" onClick={cancelSession} isDisabled={Boolean(pendingAction)}>
              {pendingAction === "cancel" ? (lang === "zh" ? "停止中" : "Stopping") : cancelLabel}
            </VButton>
          </div>
        ) : null}
      </section>
    );
  }

  function renderOperationTimeline(operations: AgentMessageOperation[], options: { limitInitialRows?: boolean } = {}) {
    const shouldLimitRows = options.limitInitialRows && operations.length > INITIAL_VISIBLE_FEEDBACK_OPERATION_COUNT;
    const hiddenOperationCount = shouldLimitRows ? operations.length - INITIAL_VISIBLE_FEEDBACK_OPERATION_COUNT : 0;
    const visibleOperations = shouldLimitRows
      ? operations.slice(-INITIAL_VISIBLE_FEEDBACK_OPERATION_COUNT)
      : operations;
    return (
      <div className={styles.operationTimeline}>
        {hiddenOperationCount > 0 ? (
          <div className={styles.operationTimelineTrimmed}>
            {lang === "zh"
              ? `已折叠更早 ${hiddenOperationCount} 步执行记录`
              : `${hiddenOperationCount} earlier execution steps collapsed`}
          </div>
        ) : null}
        {visibleOperations.map((operation) => {
          const duration = formatDuration(operation.durationSeconds);
          const detailsId = `operation-detail-${operation.id}`;
          const detailsExpanded = getExpansionState(operation.id, "details", false);
          const canExpandDetails = hasOperationDetails(operation);
          const computerUseResult = renderComputerUseResult(operation);
          const detailToggleTitle = operation.kind === "thought"
            ? detailsExpanded ? t("thoughtProcessVisible") : t("thoughtProcessHidden")
            : operation.kind === "status"
              ? detailsExpanded ? t("executionDetailsVisible") : t("executionDetailsHidden")
            : detailsExpanded ? t("toolCallDetailsVisible") : t("toolCallDetailsHidden");
          const statusTone = operationStatusToneClassName(operation);
          const operationClassName = [
            styles.operationItem,
            styles[`operationItem_${operationTone(operation)}`],
            styles[`operationItem_${statusTone}`],
            isRunningOperationStatus(operation.status) ? styles.operationItemActive : "",
          ].filter(Boolean).join(" ");
          return (
            <div key={operation.id} className={styles.operationItemWrap}>
              <div className={operationClassName}>
                <span
                  className={`${styles.operationIcon} ${styles[`operationIcon_${operation.kind}`]} ${styles[`operationIcon_${statusTone}`]}`}
                >
                  {operationIcon(operation.kind, operation.label)}
                </span>
                <div className={`${styles.operationText} ${styles[`operationText_${statusTone}`]}`}>
                  <span className={`${styles.operationName} ${styles[`operationText_${statusTone}`]}`}>{operationLabel(operation)}</span>
                  {operation.summary ? (
                    <span className={`${styles.operationSummaryText} ${styles[`operationText_${statusTone}`]}`}>{operation.summary}</span>
                  ) : null}
                </div>
                <span className={`${styles.operationStatus} ${styles[`operationStatus_${statusTone}`]}`}>
                  {operationStatusIcon(operation)}
                  <span>{operationStatusText(operation.status)}</span>
                </span>
                {duration ? <span className={styles.operationDuration}>{duration}</span> : null}
                {canExpandDetails ? (
                  <VButton
                    type="button"
                    className={styles.operationDetailToggle}
                    aria-expanded={detailsExpanded}
                    aria-controls={detailsId}
                    onClick={() => toggleSection(operation.id, "details", false)}
                    title={detailToggleTitle}
                    isIconOnly
                    icon={detailsExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />} />
                ) : (
                  <span className={styles.operationChevron} aria-hidden="true">
                    {hasOperationDetails(operation) ? <ChevronRight size={16} /> : null}
                  </span>
                )}
              </div>
              {canExpandDetails ? (
                <DeferredOperationDetails
                  operation={operation}
                  expanded={detailsExpanded}
                  detailsId={detailsId}
                  kind={operationDetailsKind(operation)}
                  buildDetailRows={(detailOperation) => buildOperationDetailRows(detailOperation, operationDetailLabels)}
                />
              ) : null}
              {computerUseResult}
            </div>
          );
        })}
      </div>
    );
  }

  function renderAgentMessageTimeline(
    message: ConversationMessage,
    items: AgentMessageTimelineItem[],
    rowIdentity: AgentMessageTimelineRowIdentity,
    processSectionIds?: string,
  ) {
    if (items.length === 0) {
      return null;
    }
    const activeItemId = activeAgentMessageTimelineItemId(message, items);
    return (
      <div
        className={styles.conversationCellTimeline}
        data-conversation-part-key={rowIdentity.processKey}
        data-agent-process-section-ids={processSectionIds}
        data-agent-process-kind={processSectionIds ? "timeline" : undefined}
      >
        {items.map((item) => renderAgentMessageTimelineItem(message, item, rowIdentity, item.id === activeItemId))}
      </div>
    );
  }

  function renderCodexTranscriptCells(
    message: ConversationMessage,
    cells: CodexTranscriptCell[],
    rowIdentity: AgentMessageTimelineRowIdentity,
  ) {
    const visibleCells = settleCodexTranscriptActiveStatuses(
      cells.filter((cell) => cell.kind !== "user"),
    );
    if (visibleCells.length === 0) {
      return null;
    }
    const isFinalResponseCell = (cell: CodexTranscriptCell) => (
      cell.kind === "assistant_markdown" && cell.phase !== "commentary"
    );
    const processCells = visibleCells.filter((cell) => !isFinalResponseCell(cell));
    const finalCells = visibleCells.filter(isFinalResponseCell);
    const renderTimelineNodes = (
      timelineCells: CodexTranscriptCell[],
      options?: { attachToolApproval?: boolean },
    ) => {
      const nodes = buildCodexTranscriptTimelineNodes(timelineCells);
      const canAttach = Boolean(options?.attachToolApproval && toolApproval && !toolApprovalConsumedRef.current);
      const toolActivities = nodes.filter((node) => node.kind === "tool_activity");
      const matchedActivityId = canAttach
        ? (
          toolActivities.find((node) => node.kind === "tool_activity" && shouldAttachToolApprovalToActivity(
            node.activity,
            toolApproval?.toolName,
            { preferAnyOpenWhenUnmatched: false },
          ))
          ?? toolActivities.find((node) => node.kind === "tool_activity" && shouldAttachToolApprovalToActivity(
            node.activity,
            toolApproval?.toolName,
            { preferAnyOpenWhenUnmatched: true },
          ))
          ?? toolActivities[toolActivities.length - 1]
        )
        : null;
      const matchedId = matchedActivityId && matchedActivityId.kind === "tool_activity"
        ? matchedActivityId.activity.id
        : "";
      return nodes.map((node) => {
        if (node.kind !== "tool_activity") {
          return renderCodexTranscriptCell(message, node.cell, { attachToolApproval: false });
        }
        const attachApproval = Boolean(canAttach && node.activity.id === matchedId);
        if (attachApproval) {
          toolApprovalConsumedRef.current = true;
        }
        return (
          <ConversationToolActivity
            key={node.activity.id}
            activity={node.activity}
            language={lang === "en" ? "en" : "zh"}
            renderToolDetails={renderCodexTranscriptToolDetailContent}
            approvalSlot={attachApproval && toolApproval ? toolApproval.content : null}
          />
        );
      });
    };
    return (
      <div
        className={styles.codexTranscriptSurface}
        data-codex-transcript-surface="true"
        data-conversation-part-key={`${rowIdentity.messageKey}:codex-transcript`}
      >
        {processCells.length > 0 ? (
          <ConversationProcessDisclosure
            cells={processCells}
            language={lang === "en" ? "en" : "zh"}
            messageOrder={activeTimelineMessageOrder}
            onUserToggle={handleProcessDisclosureUserToggle}
            turnStreaming={Boolean(message.streaming)}
          >
            {/* Approvals stay composer-adjacent only (toolApprovalFallback); never re-attach into process rows. */}
            {renderTimelineNodes(processCells, { attachToolApproval: false })}
          </ConversationProcessDisclosure>
        ) : null}
        {finalCells.length > 0 ? (
          <div data-codex-final-response="true">
            {renderTimelineNodes(finalCells, { attachToolApproval: false })}
          </div>
        ) : null}
        {changedFiles.length > 0 ? (
          <div
            className={styles.codexTurnChangeBadge}
            data-codex-turn-change-badge="true"
            title={changedFiles.slice(0, 12).join("\n")}
          >
            {lang === "zh"
              ? `${changedFiles.length} 个文件已更改`
              : `${changedFiles.length} file${changedFiles.length === 1 ? "" : "s"} changed`}
          </div>
        ) : null}
      </div>
    );
  }

  function shouldRenderCompactActiveTurnPlaceholder(
    message: ConversationMessage,
    options: {
      showResponseBlock: boolean;
      hasFeedbackTimeline: boolean;
      hasActiveProcess: boolean;
      turnErrorMessage: boolean;
    },
  ) {
    return resolveShouldRenderCompactActiveTurnPlaceholder({
      role: message.role,
      streaming: Boolean(message.streaming),
      showResponseBlock: options.showResponseBlock,
      hasFeedbackTimeline: options.hasFeedbackTimeline,
      hasActiveProcess: options.hasActiveProcess,
      turnErrorMessage: options.turnErrorMessage,
    });
  }

  function renderCodexTranscriptCell(
    message: ConversationMessage,
    cell: CodexTranscriptCell,
    options?: { attachToolApproval?: boolean },
  ) {
    if (cell.kind === "assistant_markdown") {
      const text = cell.text?.trim() ?? "";
      if (!text || isNoFinalAnswerStatusContent(text) || isStreamingStatusPlaceholderContent(text)) {
        return null;
      }
      const assistantPhaseClassName = cell.phase === "commentary"
        ? styles.codexTranscriptCommentaryCell
        : styles.codexTranscriptFinalCell;
      return (
        <section
          key={cell.id}
          className={[styles.codexTranscriptCell, styles.codexTranscriptAssistantCell, assistantPhaseClassName].filter(Boolean).join(" ")}
          data-codex-transcript-cell-kind={cell.kind}
          data-codex-transcript-cell-status={cell.status}
          data-codex-transcript-cell-tone={cell.tone}
          data-codex-transcript-cell-channel={cell.channel || undefined}
          data-codex-transcript-cell-phase={cell.phase ?? ""}
          data-conversation-part-key={cell.id}
        >
          {message.streaming ? renderStreamingResponseText(text) : renderResponseText(text, imageArtifactUrlsBeforeMessage.get(message.id))}
        </section>
      );
    }
    if (cell.kind === "reasoning_summary") {
      return renderCodexReasoningSummaryCell(message, cell);
    }
    if (cell.kind === "error_notice") {
      const rawErrorTitle = cell.title?.trim() || (lang === "zh" ? "执行失败" : "Failed");
      const visibleErrorTitle = conversationToolPresentationLabel(rawErrorTitle, lang === "en" ? "en" : "zh");
      const errorText = completedToolPresentationSummary({
        cellSummary: cell.summary,
        resultPreview: cell.text,
        toolName: rawErrorTitle,
        status: cell.status,
        language: lang === "en" ? "en" : "zh",
      });
      const diagnosticRows = buildTurnErrorDiagnosticRows(cell.diagnosticSummary, lang);
      const isCompactToolFailure = Boolean(cell.operationIds?.length);
      if (isCompactToolFailure) {
        const compactErrorSummary = (
          <>
            <span className={styles.codexTranscriptCellTitle}>{visibleErrorTitle}</span>
            {cell.failureCount && cell.failureCount > 1 ? (
              <span className={styles.codexTranscriptCellMeta}>· {cell.failureCount} {lang === "zh" ? "次" : "times"}</span>
            ) : null}
            {diagnosticRows.length > 0 ? (
              <ChevronDown className={styles.codexTranscriptInlineChevron} size={14} aria-hidden="true" />
            ) : null}
            {errorText ? <span className={styles.codexTranscriptCellMeta} aria-hidden="true">·</span> : null}
            {errorText ? <span className={styles.codexTranscriptCompactErrorSummary}>{errorText}</span> : null}
          </>
        );
        return (
          <section
            key={cell.id}
            className={[styles.codexTranscriptCell, styles.codexTranscriptProcessCell, styles.codexTranscriptCell_error].filter(Boolean).join(" ")}
            data-codex-transcript-cell-kind={cell.kind}
            data-codex-transcript-cell-status={cell.status}
            data-codex-transcript-cell-tone={cell.tone}
            data-codex-tool-error-compact="true"
            data-conversation-part-key={cell.id}
            role="status"
          >
            <span className={styles.codexTranscriptCellIcon} aria-hidden="true">
              <TerminalSquare size={14} />
            </span>
            <div className={styles.codexTranscriptCellBody}>
              {diagnosticRows.length > 0 ? (
                <details className={styles.codexTranscriptCompactErrorDetails} data-codex-error-diagnostic="true">
                  <summary className={`${styles.codexTranscriptCellTitleRow} ${styles.codexTranscriptCompactErrorDetailsSummary}`}>
                    {compactErrorSummary}
                  </summary>
                  <dl className={styles.turnErrorReasonList}>
                    {diagnosticRows.map((row) => (
                      <div key={`${cell.id}-${row.label}-${row.value}`} className={styles.turnErrorReasonRow}>
                        <dt>{row.label}</dt>
                        <dd>{row.value}</dd>
                      </div>
                    ))}
                  </dl>
                </details>
              ) : (
                <div className={styles.codexTranscriptCellTitleRow}>
                  {compactErrorSummary}
                </div>
              )}
            </div>
          </section>
        );
      }
      return (
        <section
          key={cell.id}
          className={[styles.codexTranscriptCell, styles.codexTranscriptProcessCell, styles.codexTranscriptCell_error].filter(Boolean).join(" ")}
          data-codex-transcript-cell-kind={cell.kind}
          data-codex-transcript-cell-status={cell.status}
          data-codex-transcript-cell-tone={cell.tone}
          data-codex-transcript-cell-channel={cell.channel || undefined}
          data-codex-transcript-cell-phase={cell.phase ?? ""}
          data-codex-transcript-cell-terminal={cell.terminal ? "true" : "false"}
          data-conversation-part-key={cell.id}
          role="status"
        >
          <span className={styles.codexTranscriptCellIcon} aria-hidden="true">
            <TerminalSquare size={14} />
          </span>
          <div className={styles.codexTranscriptCellBody}>
            <span className={styles.codexTranscriptCellTitleRow}>
              <span className={styles.codexTranscriptCellTitle}>{cell.title?.trim() || (lang === "zh" ? "执行失败" : "Failed")}</span>
            </span>
            {errorText ? (
              <div className={styles.codexTranscriptCellSummary}>{renderResponseText(errorText)}</div>
            ) : null}
            {diagnosticRows.length > 0 ? (
              <details className={styles.operationDetailsDisclosure} data-codex-error-diagnostic="true">
                <summary className={styles.operationDetailsSummary}>
                  <span className={styles.codexTranscriptCellTitle}>{lang === "zh" ? "诊断详情" : "Diagnostics"}</span>
                  <span className={styles.operationDetailsChevronButton} aria-hidden="true">
                    <span className={styles.operationDetailsChevronClosed}>▸</span>
                    <span className={styles.operationDetailsChevronOpen}>▾</span>
                  </span>
                </summary>
                <dl className={styles.turnErrorReasonList}>
                  {diagnosticRows.map((row) => (
                    <div key={`${cell.id}-${row.label}-${row.value}`} className={styles.turnErrorReasonRow}>
                      <dt>{row.label}</dt>
                      <dd>{row.value}</dd>
                    </div>
                  ))}
                </dl>
              </details>
            ) : null}
          </div>
        </section>
      );
    }
    if (cell.kind === "stream_tail") {
      return (
        <section
          key={cell.id}
          className={`${styles.codexTranscriptCell} ${styles.codexTranscriptProcessCell} ${styles.codexTranscriptCell_running}`}
          data-codex-transcript-cell-kind={cell.kind}
          data-codex-transcript-cell-status={cell.status}
          data-codex-transcript-cell-tone={cell.tone}
          data-conversation-part-key={cell.id}
          role="status"
          aria-live="polite"
        >
          <span className={styles.codexTranscriptCellIcon} aria-hidden="true">
            <LoaderCircle className={styles.statusSpinner} size={14} />
          </span>
          <span className={styles.codexTranscriptCellBody}>
            <span className={styles.codexTranscriptCellTitle}>{lang === "zh" ? "正在生成" : "Streaming"}</span>
          </span>
        </section>
      );
    }
    if (cell.kind === "tool_call") {
      const activity = createCodexTranscriptToolActivity([cell]);
      const attachApproval = Boolean(
        options?.attachToolApproval
        && toolApproval
        && !toolApprovalConsumedRef.current
        && shouldAttachToolApprovalToActivity(activity, toolApproval.toolName, { preferAnyOpenWhenUnmatched: true }),
      );
      if (attachApproval) {
        toolApprovalConsumedRef.current = true;
      }
      return (
        <ConversationToolActivity
          key={cell.id}
          activity={activity}
          language={lang === "en" ? "en" : "zh"}
          renderToolDetails={renderCodexTranscriptToolDetailContent}
          approvalSlot={attachApproval && toolApproval ? toolApproval.content : null}
        />
      );
    }
    const toneClassName = styles[`codexTranscriptCell_${cell.tone}` as keyof typeof styles] ?? "";
    const icon = codexTranscriptCellIcon(cell);
    const title = codexTranscriptCellTitle(cell);
    const meta = codexTranscriptCellMeta(cell);
    const summary = codexTranscriptVisibleSummary(cell);
    return (
      <section
        key={cell.id}
        className={[styles.codexTranscriptCell, styles.codexTranscriptProcessCell, toneClassName].filter(Boolean).join(" ")}
        data-codex-transcript-cell-kind={cell.kind}
        data-codex-transcript-cell-status={cell.status}
        data-codex-transcript-cell-tone={cell.tone}
        data-codex-transcript-cell-channel={cell.channel || undefined}
        data-codex-transcript-cell-phase={cell.phase || undefined}
        data-conversation-part-key={cell.id}
        role={cell.status === "running" || cell.status === "pending" ? "status" : undefined}
        aria-live={cell.status === "running" || cell.status === "pending" ? "polite" : undefined}
      >
        <span className={styles.codexTranscriptCellIcon} aria-hidden="true">
          {icon}
        </span>
        <span className={styles.codexTranscriptCellBody}>
          <span className={styles.codexTranscriptCellTitleRow}>
            <span className={styles.codexTranscriptCellTitle}>{title}</span>
            {meta ? <span className={styles.codexTranscriptCellMeta}>{meta}</span> : null}
          </span>
          {summary ? <span className={styles.codexTranscriptCellSummary}>{summary}</span> : null}
        </span>
      </section>
    );
  }

  function renderCodexReasoningSummaryCell(
    message: ConversationMessage,
    cell: CodexTranscriptCell,
  ) {
    const fullText = String(cell.text || cell.summary || "").trim();
    if (!fullText) {
      return null;
    }
    // Live SSE: expand while the model is still thinking so tokens stream in the body.
    // When the cell settles, default flips false and expansion defaults auto-collapse
    // (unless the user explicitly toggled the section open/closed).
    const defaultExpanded = cell.status === "running" || cell.status === "pending";
    const sectionId = reasoningExpansionSectionId(cell);
    const expanded = getExpansionState(message.id, sectionId, defaultExpanded);
    const inlinePreview = humanizeReasoningPreview(fullText);
    const title = codexTranscriptCellTitle(cell);
    const meta = codexTranscriptCellMeta(cell);
    const toneClassName = styles[`codexTranscriptCell_${cell.tone}` as keyof typeof styles] ?? "";
    const toggleLabel = expanded ? t("thoughtProcessVisible") : t("thoughtProcessHidden");
    const toggleReasoning = (event?: { stopPropagation?: () => void }) => {
      event?.stopPropagation?.();
      toggleSection(message.id, sectionId, defaultExpanded);
    };
    return (
      <section
        key={cell.id}
        className={[
          styles.codexTranscriptCell,
          styles.codexTranscriptReasoningCell,
          toneClassName,
        ].filter(Boolean).join(" ")}
        data-codex-transcript-cell-kind={cell.kind}
        data-codex-transcript-cell-status={cell.status}
        data-codex-transcript-cell-tone={cell.tone}
        data-conversation-part-key={cell.id}
        data-thought-section={sectionId}
        data-thought-expanded={expanded ? "true" : "false"}
        role={cell.status === "running" || cell.status === "pending" ? "status" : undefined}
        aria-live={cell.status === "running" || cell.status === "pending" ? "polite" : undefined}
      >
        <VButton
          type="button"
          contentLayout="plain"
          className={styles.codexTranscriptReasoningHeader}
          aria-expanded={expanded}
          aria-label={toggleLabel}
          onClick={(event) => {
            event.stopPropagation();
            toggleReasoning();
          }}
        >
          <span className={styles.codexTranscriptCellIcon} aria-hidden="true">
            {cell.status === "running" || cell.status === "pending"
              ? <LoaderCircle className={styles.statusSpinner} size={14} />
              : <BrainCircuit size={14} />}
          </span>
          <span className={styles.codexTranscriptReasoningHeaderBody}>
            <span className={styles.codexTranscriptReasoningTitleRow}>
              <span className={styles.codexTranscriptCellTitle}>{title}</span>
              {meta ? <span className={styles.codexTranscriptCellMeta}>{meta}</span> : null}
              {!expanded && inlinePreview ? (
                <>
                  <span className={styles.timelineCellSeparator} aria-hidden="true">·</span>
                  <span className={styles.codexTranscriptReasoningInlinePreview}>{inlinePreview}</span>
                </>
              ) : null}
            </span>
          </span>
          {expanded ? <ChevronDown size={15} aria-hidden="true" /> : <ChevronRight size={15} aria-hidden="true" />}
        </VButton>
        {expanded ? (
          <VButton
            type="button"
            contentLayout="plain"
            className={styles.codexTranscriptReasoningTextButton}
            aria-label={toggleLabel}
            onClick={(event) => {
              event.stopPropagation();
              toggleReasoning();
            }}
          >
            <pre className={styles.codexTranscriptReasoningText}>{fullText}</pre>
          </VButton>
        ) : null}
      </section>
    );
  }

  function codexTranscriptVisibleSummary(cell: CodexTranscriptCell) {
    if (cell.kind === "tool_call") {
      return cell.status === "completed"
        ? codexTranscriptCompletedToolSummary(cell)
        : cell.summary || cell.text;
    }
    if (cell.kind === "error_notice") {
      return "";
    }
    if (cell.kind === "reasoning_summary") {
      // Collapsed preview is rendered by renderCodexReasoningSummaryCell.
      return cell.summary || cell.text;
    }
    return cell.summary || cell.text;
  }

  function codexTranscriptCompletedToolSummary(cell: CodexTranscriptCell) {
    const toolCall = cell.toolLifecycleModel?.toolCalls?.[0];
    return completedToolPresentationSummary({
      toolSummary: toolCall?.summary,
      cellSummary: cell.summary,
      resultPreview: toolCall?.resultPreview,
      cellText: cell.text,
      toolName: toolCall?.rawToolName || cell.title,
      status: cell.status,
      language: lang,
    });
  }

  function codexTranscriptCellIcon(cell: CodexTranscriptCell) {
    if (cell.status === "running" || cell.status === "pending") {
      return <LoaderCircle className={styles.statusSpinner} size={14} />;
    }
    if (cell.kind === "reasoning_summary") {
      return <BrainCircuit size={14} />;
    }
    if (cell.kind === "status") {
      return <CircleDot size={14} />;
    }
    if (cell.kind === "error_notice" || cell.status === "failed") {
      return <TerminalSquare size={14} />;
    }
    return <CheckCircle2 size={14} />;
  }

  function codexTranscriptCellTitle(cell: CodexTranscriptCell) {
    if (cell.kind === "tool_call") {
      const rawToolName = cell.toolLifecycleModel?.toolCalls?.[0]?.rawToolName?.trim();
      const rawTitle = cell.title?.trim();
      return codexTranscriptToolLabel(rawToolName || rawTitle || "");
    }
    if (cell.title?.trim()) {
      return cell.title.trim();
    }
    if (cell.kind === "reasoning_summary") {
      return lang === "zh" ? "思考" : "Reasoning";
    }
    if (cell.kind === "status") {
      return lang === "zh" ? "状态" : "Status";
    }
    if (cell.kind === "error_notice") {
      return lang === "zh" ? "执行失败" : "Failed";
    }
    return lang === "zh" ? "工具调用" : "Tool call";
  }

  function codexTranscriptToolLabel(name: string) {
    return conversationToolPresentationLabel(name, lang);
  }

  function codexTranscriptCellMeta(cell: CodexTranscriptCell) {
    if (cell.status === "completed") {
      const duration = codexTranscriptToolDurationSeconds(cell);
      const completedLabel = lang === "zh" ? "完成" : "Completed";
      return duration === null ? completedLabel : `${completedLabel} ${formatCodexTranscriptDuration(duration)}`;
    }
    if (cell.status === "failed") {
      return lang === "zh" ? "失败" : "Failed";
    }
    if (cell.status === "degraded") {
      return lang === "zh" ? "降级" : "Degraded";
    }
    if (cell.status === "pending") {
      return lang === "zh" ? "等待中" : "Pending";
    }
    if (cell.status === "running") {
      return lang === "zh" ? "运行中" : "Running";
    }
    return "";
  }

  function renderCodexTranscriptToolDetailContent(cell: CodexTranscriptCell): ReactNode {
    if (cell.kind === "error_notice") {
      const diagnosticRows = buildTurnErrorDiagnosticRows(cell.diagnosticSummary, lang);
      if (diagnosticRows.length === 0) {
        return null;
      }
      return (
        <dl className={styles.turnErrorReasonList} data-codex-error-diagnostic="true">
          {diagnosticRows.map((row) => (
            <div key={`${cell.id}-${row.label}-${row.value}`} className={styles.turnErrorReasonRow}>
              <dt>{row.label}</dt>
              <dd>{row.value}</dd>
            </div>
          ))}
        </dl>
      );
    }
    if (cell.kind !== "tool_call") {
      return null;
    }
    const terminalDetail = buildConversationTerminalToolDetail(cell, lang);
    const rows = terminalDetail ? [] : codexTranscriptToolDetailRows(cell);
    const rolloutEvents = renderCodexTranscriptRolloutEvents(cell);
    if (!terminalDetail && rows.length === 0 && !rolloutEvents) {
      return null;
    }
    return (
      <>
        {terminalDetail ? (
          <ConversationTerminalToolDetail detail={terminalDetail} language={lang} />
        ) : rows.length > 0 ? (
          <div className={styles.operationDetails}>
            {rows.map((row, index) => {
              return (
                <div key={`${cell.id}-${row.label}-${index}`} className={styles.operationDetailRow}>
                  <pre
                    className={styles.operationDetailValue}
                    aria-label={row.label}
                    tabIndex={0}
                  >
                    {row.value}
                  </pre>
                </div>
              );
            })}
          </div>
        ) : null}
        {rolloutEvents}
      </>
    );
  }

  function codexTranscriptToolDetailRows(cell: CodexTranscriptCell): OperationDetailRow[] {
    const model = cell.toolLifecycleModel;
    if (!model) {
      return [];
    }
    const operationIds = new Set(cell.operationIds ?? []);
    const matchedToolCalls = model.toolCalls.filter((toolCall) =>
      operationIds.size === 0
      || operationIds.has(toolCall.rawOperationId)
      || operationIds.has(toolCall.toolCallId)
      || (toolCall.terminalOperationId ? operationIds.has(toolCall.terminalOperationId) : false)
    );
    const toolCalls = matchedToolCalls.length > 0 ? matchedToolCalls : model.toolCalls;
    const toolCallIds = new Set(toolCalls.map((toolCall) => toolCall.toolCallId).filter(Boolean));
    const terminalOperations = model.terminalOperations.filter((operation) =>
      toolCallIds.has(operation.toolCallId)
      || operationIds.has(operation.rawOperationId)
      || operationIds.has(operation.operationId)
    );
    const rows: OperationDetailRow[] = [];
    const primaryToolCall = toolCalls[0];
    const toolName = primaryToolCall?.rawToolName || primaryToolCall?.title || codexTranscriptToolRawName(cell);
    const presentDetail = (value: string) => boundedCodexToolDetailText(
      conversationToolDetailPresentation({
        value,
        toolName,
        language: lang,
      }),
    );
    const visibleTitle = codexTranscriptCellTitle(cell);
    const instructionLabel = lang === "zh" ? "指令" : "Instruction";
    const pushedInstructions = new Set<string>();
    function pushInstruction(value: string) {
      const text = value.trim();
      if (!text || text === visibleTitle || pushedInstructions.has(text)) {
        return;
      }
      pushedInstructions.add(text);
      rows.push({ label: instructionLabel, value: presentDetail(text) });
    }
    for (const operation of terminalOperations) {
      const displayCommand = operation.request?.displayCommand?.trim();
      if (displayCommand) {
        pushInstruction(displayCommand);
      }
      const output = firstNonEmptyText(
        operation.result?.formattedOutput,
        operation.result?.stdout,
      );
      if (output) {
        rows.push({
          label: operationDetailLabels.toolCallResult,
          value: presentDetail(output),
        });
      }
      const error = firstNonEmptyText(operation.result?.stderr);
      if (error) {
        rows.push({
          label: operationDetailLabels.toolCallError,
          value: presentDetail(error),
        });
      }
    }
    const resultPreview = firstNonEmptyText(...toolCalls.map((toolCall) => toolCall.resultPreview));
    if (resultPreview && !rows.some((row) => row.label === operationDetailLabels.toolCallResult && row.value.includes(resultPreview.slice(0, 80)))) {
      rows.push({
        label: operationDetailLabels.toolCallResult,
        value: presentDetail(resultPreview),
      });
    }
    const error = firstNonEmptyText(...toolCalls.map((toolCall) => toolCall.error));
    if (error) {
      rows.push({
        label: operationDetailLabels.toolCallError,
        value: presentDetail(error),
      });
    }
    return rows;
  }

  function firstNonEmptyText(...values: Array<string | undefined | null>) {
    for (const value of values) {
      const text = String(value ?? "").trim();
      if (text) {
        return text;
      }
    }
    return "";
  }

  function boundedCodexToolDetailText(value: string) {
    const normalized = String(value ?? "").trim();
    if (!normalized) {
      return "";
    }
    const maxLines = 18;
    const maxChars = 1600;
    const lines = normalized.split(/\r?\n/);
    const lineBounded = lines.slice(0, maxLines).join("\n").trimEnd();
    const lengthBounded = lineBounded.length > maxChars
      ? lineBounded.slice(0, maxChars).trimEnd()
      : lineBounded;
    const omittedLineCount = Math.max(0, lines.length - maxLines);
    const omittedCharCount = Math.max(0, normalized.length - lengthBounded.length);
    const notices = [
      omittedLineCount > 0 ? (lang === "zh" ? `已省略 ${omittedLineCount} 行` : `${omittedLineCount} lines omitted`) : "",
      omittedCharCount > 0 ? (lang === "zh" ? `已省略 ${omittedCharCount} 个字符` : `${omittedCharCount} characters omitted`) : "",
    ].filter(Boolean);
    return notices.length > 0 ? `${lengthBounded}\n\n[${notices.join(lang === "zh" ? "，" : ", ")}]` : lengthBounded;
  }

  function renderCodexTranscriptRolloutEvents(cell: CodexTranscriptCell) {
    if (cell.tone !== "error" && cell.tone !== "warning" && cell.status !== "running") {
      return null;
    }
    const events = cell.rolloutTraceEvents ?? [];
    if (events.length === 0) {
      return null;
    }
    return (
      <details
        className={styles.operationDetailsDisclosure}
        data-codex-tool-technical-details="true"
      >
        <summary className={styles.operationDetailsSummary}>
          <span className={styles.operationDetailsChevronButton} aria-hidden="true">
            <span className={styles.operationDetailsChevronClosed}>▸</span>
            <span className={styles.operationDetailsChevronOpen}>▾</span>
          </span>
          <span>{lang === "zh" ? "技术详情" : "Technical details"}</span>
        </summary>
        <ol className={styles.rolloutTraceList} aria-label={lang === "zh" ? "工具生命周期" : "Tool lifecycle"}>
          {events.map((event) => {
            const eventClassName = [
              styles.rolloutTraceItem,
              styles[`rolloutTraceItem_${event.status}`],
            ].filter(Boolean).join(" ");
            const detailText = [
              event.error,
              event.exitCode !== undefined && event.exitCode !== null ? `exit ${event.exitCode}` : "",
              event.timedOut ? (lang === "zh" ? "已超时" : "timed out") : "",
            ].filter(Boolean).join(" · ");
            return (
              <li
                key={event.id}
                className={eventClassName}
                data-rollout-trace-kind={event.kind}
                data-rollout-trace-status={event.status}
                data-rollout-tool-call-id={event.toolCallId}
                data-rollout-terminal-operation-id={event.terminalOperationId}
                data-rollout-terminal-id={event.terminalId}
              >
                <span className={styles.rolloutTraceDot} aria-hidden="true" />
                <span className={styles.rolloutTraceText}>
                  <span className={styles.rolloutTraceTitle}>{rolloutTraceEventLabel(event.kind)}</span>
                  {detailText ? <span className={styles.rolloutTraceMeta}>{detailText}</span> : null}
                </span>
              </li>
            );
          })}
        </ol>
      </details>
    );
  }

  function renderAgentMessageTimelineItem(
    message: ConversationMessage,
    item: AgentMessageTimelineItem,
    rowIdentity: AgentMessageTimelineRowIdentity,
    isActiveTimelineItem: boolean,
  ) {
    if (item.kind === "thought") {
      return renderThoughtTimelineItem(message, item, rowIdentity, isActiveTimelineItem);
    }
    if (item.kind === "assistant_text") {
      return renderAssistantTextTimelineItem(message, item, rowIdentity);
    }
    if (item.kind === "command_group") {
      return renderCommandGroupTimelineItem(message, item, rowIdentity, isActiveTimelineItem);
    }
    return renderOperationTimelineItem(item, rowIdentity, isActiveTimelineItem);
  }

  function renderThoughtTimelineItem(
    message: ConversationMessage,
    item: Extract<AgentMessageTimelineItem, { kind: "thought" }>,
    rowIdentity: AgentMessageTimelineRowIdentity,
    isActiveTimelineItem: boolean,
  ) {
    // Live SSE: keep the body open while thought is running so streaming text is visible.
    // Settled thoughts default collapsed; shouldRefreshConversationExpansionDefault auto-closes.
    const inlinePreview = humanizeReasoningPreview(String(item.preview || item.text || ""));
    const defaultExpanded = Boolean(item.defaultExpanded)
      || item.status === "running"
      || item.status === "pending";
    const sectionId = `thought:${item.id}`;
    const expanded = getExpansionState(message.id, sectionId, defaultExpanded);
    const toggleLabel = expanded ? t("thoughtProcessVisible") : t("thoughtProcessHidden");
    return (
      <section
        key={agentMessageTimelineItemRowKey(rowIdentity, item)}
        className={styles.timelineThoughtCell}
        data-conversation-part-key={agentMessageTimelineItemRowKey(rowIdentity, item)}
        data-thought-section={sectionId}
        data-thought-expanded={expanded ? "true" : "false"}
      >
        <VButton
          type="button"
        contentLayout="plain"
          className={styles.timelineThoughtHeader}
          aria-expanded={expanded}
          aria-label={toggleLabel}
          onClick={(event) => {
            event.stopPropagation();
            toggleSection(message.id, sectionId, defaultExpanded);
          }}
        >
          {isActiveTimelineItem && item.status === "running" ? <LoaderCircle className={styles.statusSpinner} size={14} /> : <BrainCircuit size={14} />}
          <span className={styles.timelineCellBody}>
            <span className={`${styles.timelineCellTitleRow} ${styles.timelineCellCompactTitleRow}`}>
              <span className={styles.timelineCellTitle}>{lang === "zh" ? "思考" : "Thinking"}</span>
              {!expanded && inlinePreview ? (
                <>
                  <span className={styles.timelineCellSeparator} aria-hidden="true">·</span>
                  <span className={styles.timelineThoughtInlinePreview}>{inlinePreview}</span>
                </>
              ) : null}
            </span>
          </span>
          {expanded ? <ChevronDown size={15} aria-hidden="true" /> : <ChevronRight size={15} aria-hidden="true" />}
        </VButton>
        {expanded ? (
          <VButton
            type="button"
            contentLayout="plain"
            className={styles.timelineThoughtTextButton}
            aria-label={toggleLabel}
            onClick={(event) => {
              event.stopPropagation();
              toggleSection(message.id, sectionId, defaultExpanded);
            }}
          >
            <pre className={styles.timelineThoughtText}>{item.text}</pre>
          </VButton>
        ) : null}
      </section>
    );
  }

  function renderAssistantTextTimelineItem(
    message: ConversationMessage,
    item: Extract<AgentMessageTimelineItem, { kind: "assistant_text" }>,
    rowIdentity: AgentMessageTimelineRowIdentity,
  ) {
    const segments = getCachedResponseSegments(item.text);
    return (
      <section
        key={agentMessageTimelineItemRowKey(rowIdentity, item)}
        className={styles.timelineAssistantTextCell}
        data-conversation-part-key={agentMessageTimelineItemRowKey(rowIdentity, item)}
      >
        {segments.map((segment) => renderResponseSegment(segment, imageArtifactUrlsBeforeMessage.get(message.id)))}
      </section>
    );
  }

  function timelineStatusText(item: AgentMessageTimelineItem) {
    const status = item.status;
    if (status === "failed") {
      return lang === "zh" ? "执行失败" : "Failed";
    }
    if (status === "degraded") {
      const rawStatus = item.kind === "operation"
        ? String(item.operation.status || item.operation.rawStatus || "").trim().toLowerCase()
        : "";
      if (rawStatus === "fallback") {
        return lang === "zh" ? "备用路径" : "Fallback";
      }
      if (rawStatus === "partial") {
        return lang === "zh" ? "部分结果" : "Partial";
      }
      if (rawStatus === "unavailable") {
        return lang === "zh" ? "不可用" : "Unavailable";
      }
      if (rawStatus === "recovered") {
        return lang === "zh" ? "已恢复" : "Recovered";
      }
      return lang === "zh" ? "降级" : "Degraded";
    }
    if (status === "running") {
      return lang === "zh" ? "运行中" : "Running";
    }
    if (status === "pending") {
      return lang === "zh" ? "等待中" : "Pending";
    }
    return "";
  }

  function buildLegacyToolActivityPills(
    operation: AgentMessageOperation,
    options?: {
      status?: string;
      title?: string;
      summary?: string;
      durationLabel?: string;
    },
  ): CodexToolActivityPills {
    const rawToolName = String(
      operation.rawLabel
      || options?.title
      || operation.label
      || "",
    ).trim();
    const exitCode = typeof operation.exitCode === "number" ? operation.exitCode : null;
    // Prefer rawStatus so fallback/partial survive timeline status normalization.
    const status = operation.rawStatus || options?.status || operation.status;
    const timedOut = Boolean(operation.timedOut)
      || /超时|timed?\s*out/i.test(`${operation.summary || ""} ${operation.error || ""}`);
    // Prefer product-facing labels (operation.label / timeline title) over raw tool ids.
    const productActionLabel = [operation.label, options?.title]
      .map((value) => String(value || "").trim())
      .find((value) => value && value !== rawToolName && !/_tool$/i.test(value));
    const normalizedStatus = String(status || "").trim().toLowerCase();
    const isFailedRow = normalizedStatus === "failed"
      || normalizedStatus === "error"
      || timedOut;
    // Failed rows surface diagnostics; completed rows keep command/summary only (not raw previews).
    const diagnosticSubject = [
      operation.error,
      options?.summary,
      operation.summary,
    ].map((value) => String(value || "").trim()).find(Boolean) || "";
    const pills = buildCodexToolActivityPills({
      toolName: productActionLabel ? productActionLabel : rawToolName,
      status,
      language: lang === "en" ? "en" : "zh",
      durationSeconds: operation.durationSeconds,
      durationLabel: options?.durationLabel ?? formatDuration(operation.durationSeconds),
      toolSummary: isFailedRow ? diagnosticSubject : operation.summary,
      cellSummary: isFailedRow ? diagnosticSubject : (options?.summary || operation.summary),
      resultPreview: isFailedRow ? diagnosticSubject : undefined,
      displayCommand: isFailedRow ? "" : extractToolDisplayCommand(operation.arguments),
      timedOut,
      nonzeroExit: exitCode !== null && exitCode !== 0 && !isFailedRow,
    });
    if (productActionLabel && pills.actionLabel !== productActionLabel) {
      return { ...pills, actionLabel: productActionLabel };
    }
    return pills;
  }

  function renderCommandGroupTimelineItem(
    message: ConversationMessage,
    item: Extract<AgentMessageTimelineItem, { kind: "command_group" }>,
    rowIdentity: AgentMessageTimelineRowIdentity,
    isActiveTimelineItem: boolean,
  ) {
    const expanded = getExpansionState(message.id, item.id, false);
    const duration = formatDuration(
      item.operations
        .map((operation) => operation.durationSeconds)
        .filter((value): value is number => typeof value === "number" && Number.isFinite(value) && value > 0)
        .reduce((total, value) => total + value, 0),
    );
    const groupPills = buildCodexToolActivityPills({
      toolName: "exec_command",
      status: item.status,
      language: lang === "en" ? "en" : "zh",
      durationLabel: duration,
      cellSummary: item.summary,
    });
    // Package title stays prominent; summary is the muted subject under the pill pair.
    if (item.title?.trim()) {
      groupPills.actionLabel = item.title.trim();
    }
    if (item.summary?.trim()) {
      groupPills.subject = item.summary.trim();
    }
    const statusTone = item.status === "completed" ? "success" : item.status === "degraded" ? "warning" : item.status;
    const timelineToneClassName = styles[`timelineOperationCell_${statusTone}` as keyof typeof styles] ?? "";
    const toneTextClassName = styles[`operationText_${statusTone}` as keyof typeof styles] ?? "";
    const toneIconClassName = styles[`operationIcon_${statusTone}` as keyof typeof styles] ?? "";
    const className = [
      styles.timelineOperationCell,
      timelineToneClassName,
    ].filter(Boolean).join(" ");
    return (
      <section
        key={agentMessageTimelineItemRowKey(rowIdentity, item)}
        className={className}
        data-conversation-part-key={agentMessageTimelineItemRowKey(rowIdentity, item)}
      >
        <VButton
          type="button"
        contentLayout="plain"
          className={`${styles.timelineCellHeader} ${toneTextClassName}`}
          aria-expanded={expanded}
          aria-label={toolActivityAriaTitle(groupPills)}
          onClick={() => toggleSection(message.id, item.id, false)}
          title={expanded ? t("executionDetailsVisible") : t("executionDetailsHidden")}
        >
          <ConversationToolActivityPills
            pills={groupPills}
            leadingIcon={(
              <span className={`${styles.operationIcon} ${toneIconClassName}`}>
                {isActiveTimelineItem && item.status === "running"
                  ? <LoaderCircle className={styles.statusSpinner} size={14} />
                  : <TerminalSquare size={14} />}
              </span>
            )}
          />
        </VButton>
        {expanded ? (
          <div className={styles.timelineCommandList}>
            {item.operations.map((operation) => {
              const operationIconClassName = styles[`operationIcon_${operationStatusToneClassName(operation)}` as keyof typeof styles] ?? "";
              const pills = buildLegacyToolActivityPills(operation);
              return (
                <div key={operation.id} className={styles.timelineCommandRow}>
                  <ConversationToolActivityPills
                    pills={pills}
                    leadingIcon={(
                      <span className={`${styles.operationIcon} ${operationIconClassName}`}>
                        {operationStatusIcon(operation, isActiveTimelineItem)}
                      </span>
                    )}
                  />
                  {renderRolloutTraceEvents(operation)}
                  {operation.error ? <span className={styles.timelineCommandError}>{operation.error}</span> : null}
                </div>
              );
            })}
          </div>
        ) : null}
      </section>
    );
  }

  function isLowValueToolLoopStatusOperation(operation: AgentMessageOperation) {
    if (operation.kind !== "status") {
      return false;
    }
    const haystack = [
      operation.label,
      operation.rawLabel,
      operation.summary,
      operation.resultPreview,
      operation.error,
    ].map((value) => String(value || "").toLowerCase()).join(" ");
    return (
      haystack.includes("long_loop")
      || haystack.includes("工具循环")
      || haystack.includes("tool loop")
      || haystack.includes("尚未形成最终回答")
      || haystack.includes("本轮尚未形成最终回答")
      || haystack.includes("尚未形成最终回答")
    );
  }

  function renderOperationTimelineItem(
    item: Extract<AgentMessageTimelineItem, { kind: "operation" }>,
    rowIdentity: AgentMessageTimelineRowIdentity,
    isActiveTimelineItem: boolean,
  ) {
    const operation = item.operation;
    // Codex does not surface internal "tool loop / no final answer yet" progress as a tool row.
    if (isLowValueToolLoopStatusOperation(operation)) {
      return null;
    }
    const rawTimelineTitle = item.title.trim();
    const rawOperationLabel = String(operation.rawLabel ?? "").trim();
    const rawToolName = rawOperationLabel || rawTimelineTitle || operation.label;
    const semanticToolTitle = conversationToolPresentationLabel(rawToolName, lang);
    const visibleTitle = operation.kind === "tool"
      ? rawTimelineTitle && rawTimelineTitle !== rawOperationLabel
        ? rawTimelineTitle
        : semanticToolTitle
      : rawTimelineTitle && rawTimelineTitle !== rawOperationLabel
        ? rawTimelineTitle
        : operationLabel(operation);
    const detailsId = `timeline-operation-detail-${operation.id}`;
    const detailsExpanded = getExpansionState(operation.id, "details", false);
    const canExpandDetails = hasOperationDetails(operation);
    const duration = formatDuration(operation.durationSeconds);
    const computerUseResult = renderComputerUseResult(operation);
    const readableResult = operation.kind === "tool" || isCompactInternalStatusOperation(operation)
      ? ""
      : readableOperationResult(operation, operationDetailLabels.structuredResultFallback);
    const showReadableResult = Boolean(operation.kind !== "tool" && readableResult && readableResult !== item.summary.trim());
    const visibleStatus = timelineStatusText(item);
    const statusTone = operationStatusToneClassName(operation);
    const timelineToneClassName = styles[`timelineOperationCell_${statusTone}` as keyof typeof styles] ?? "";
    const toneTextClassName = styles[`operationText_${statusTone}` as keyof typeof styles] ?? "";
    const toneStatusClassName = styles[`operationStatus_${statusTone}` as keyof typeof styles] ?? "";
    const toneIconClassName = styles[`operationIcon_${statusTone}` as keyof typeof styles] ?? "";
    const metaText = [visibleStatus, duration].filter(Boolean).join(" · ");
    const visibleSummary = operation.kind === "tool"
      ? completedToolPresentationSummary({
          toolSummary: operation.error,
          cellSummary: operation.summary,
          resultPreview: operation.resultPreview,
          cellText: item.summary,
          toolName: rawToolName,
          status: item.status,
          language: lang,
        })
      : statusTone === "failed" && operation.error?.trim()
        ? [item.summary, operation.error.trim()].filter(Boolean).join(" · ")
        : item.summary;
    const toolPills = operation.kind === "tool"
      ? buildLegacyToolActivityPills(operation, {
          status: item.status,
          title: rawToolName,
          summary: item.summary || visibleSummary,
          durationLabel: duration,
        })
      : null;
    const className = [
      styles.timelineOperationCell,
      timelineToneClassName,
    ].filter(Boolean).join(" ");
    const leadingIcon = (
      <span className={`${styles.operationIcon} ${toneIconClassName}`}>
        {operationStatusIcon(operation, isActiveTimelineItem)}
      </span>
    );
    // Tool rows: Codex quiet chrome — leading status icon only. A trailing
    // ChevronRight was wrapping onto a second grid line as a lone "›" under the icon.
    const headerContent = toolPills ? (
      <ConversationToolActivityPills pills={toolPills} leadingIcon={leadingIcon} />
    ) : (
      <>
        {leadingIcon}
        <span className={styles.timelineCellBody}>
          <span className={`${styles.timelineCellTitleRow} ${styles.timelineCellCompactTitleRow}`}>
            <span className={`${styles.timelineCellTitle} ${toneTextClassName}`}>{visibleTitle}</span>
            {metaText ? <span className={`${styles.timelineCellMeta} ${toneStatusClassName}`}>{metaText}</span> : null}
            {canExpandDetails ? (
              <span className={styles.timelineCellInlineChevron} aria-hidden="true">
                {detailsExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              </span>
            ) : null}
            {visibleSummary ? <span className={styles.timelineCellSeparator} aria-hidden="true">·</span> : null}
            {visibleSummary ? <span className={styles.timelineCellInlineSummary}>{visibleSummary}</span> : null}
          </span>
        </span>
      </>
    );
    const headerAriaLabel = toolPills ? toolActivityAriaTitle(toolPills) : visibleTitle;
    return (
      <section
        key={agentMessageTimelineItemRowKey(rowIdentity, item)}
        className={className}
        data-conversation-part-key={agentMessageTimelineItemRowKey(rowIdentity, item)}
        data-codex-tool-unified-row={toolPills ? "true" : undefined}
      >
        {canExpandDetails ? (
          <VButton
            type="button"
            className={`${styles.timelineCellHeader} ${toneTextClassName}`}
            aria-expanded={detailsExpanded}
            aria-controls={detailsId}
            aria-label={headerAriaLabel}
            onClick={() => toggleSection(operation.id, "details", false)}
            title={detailsExpanded ? t("toolCallDetailsVisible") : t("toolCallDetailsHidden")}
          >
            {headerContent}
          </VButton>
        ) : (
          <div className={`${styles.timelineCellHeader} ${toneTextClassName}`}>
            {headerContent}
          </div>
        )}
        {canExpandDetails ? (
          <>
            <DeferredOperationDetails
              operation={operation}
              expanded={detailsExpanded}
              detailsId={detailsId}
              kind={operationDetailsKind(operation)}
              buildDetailRows={(detailOperation) => buildOperationDetailRows(detailOperation, operationDetailLabels)}
            />
            {detailsExpanded ? renderRolloutTraceEvents(operation) : null}
          </>
        ) : null}
        {showReadableResult ? <pre className={styles.timelineOperationResult}>{readableResult}</pre> : null}
        {computerUseResult}
      </section>
    );
  }

  function isCompactInternalStatusOperation(operation: AgentMessageOperation) {
    return Boolean(
      operation.kind === "status"
      && !operation.error?.trim()
      && isInternalRuntimeStatus({
        kind: "status",
        name: operation.rawLabel ?? operation.label,
        status: operation.status,
        summary: operation.summary,
        resultPreview: operation.resultPreview,
      }),
    );
  }

  function renderReActActionSection(group: AgentMessageReActOperationGroup) {
    const actions = reActActionOperations(group);
    if (actions.length === 0) {
      return null;
    }
    return (
      <section className={styles.reActOperationSection}>
        <div className={styles.reActToolList}>
          {actions.map((operation) => {
            const duration = formatDuration(operation.durationSeconds);
            const detailsId = `operation-detail-${operation.id}`;
            const detailsExpanded = getExpansionState(operation.id, "details", false);
            const canExpandDetails = hasOperationDetails(operation);
            const computerUseResult = renderComputerUseResult(operation);
            const statusTone = operationStatusToneClassName(operation);
            const pills = operation.kind === "tool"
              ? buildLegacyToolActivityPills(operation)
              : null;
            return (
              <div key={operation.id} className={`${styles.reActToolItem} ${styles[`operationItem_${statusTone}`]}`}>
                <div className={`${styles.reActToolLine} ${styles[`operationItem_${statusTone}`]}`}>
                  {pills ? (
                    <ConversationToolActivityPills pills={pills} />
                  ) : (
                    <span className={`${styles.reActToolName} ${styles[`operationText_${statusTone}`]}`}>{operationLabel(operation)}</span>
                  )}
                  {!pills && operation.summary ? (
                    <span className={`${styles.reActToolSummary} ${styles[`operationText_${statusTone}`]}`}>{operation.summary}</span>
                  ) : null}
                  {!pills ? (
                    <span className={`${styles.reActToolStatus} ${styles[`operationStatus_${statusTone}`]}`}>
                      {operationStatusIcon(operation)}
                      <span>{operationStatusText(operation.status)}</span>
                      {duration ? <span>{duration}</span> : null}
                    </span>
                  ) : null}
                  {canExpandDetails ? (
                    <VButton
                      type="button"
                      className={styles.reActToolDetailToggle}
                      aria-expanded={detailsExpanded}
                      aria-controls={detailsId}
                      onClick={() => toggleSection(operation.id, "details", false)}
                      title={detailsExpanded ? t("toolCallDetailsVisible") : t("toolCallDetailsHidden")}
                      isIconOnly
                      icon={detailsExpanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />} />
                  ) : null}
                </div>
                {canExpandDetails ? (
                  <DeferredOperationDetails
                    operation={operation}
                    expanded={detailsExpanded}
                    detailsId={detailsId}
                    kind="tool"
                    buildDetailRows={(detailOperation) => buildOperationDetailRows(detailOperation, operationDetailLabels)}
                  />
                ) : null}
                {computerUseResult}
              </div>
            );
          })}
        </div>
      </section>
    );
  }

  function renderReActThoughtSection(group: AgentMessageReActOperationGroup) {
    const thoughts = reActThoughtItems(group);
    if (thoughts.length === 0) {
      return null;
    }
    return (
      <section className={styles.reActOperationSection}>
        <span className={styles.reActOperationSectionLabel}>{lang === "zh" ? "思考" : "Thinking"}</span>
        <div className={styles.reActThoughtStack}>
          {thoughts.map((item) => (
            <pre key={item.id} className={styles.reActThoughtText}>{item.value}</pre>
          ))}
        </div>
      </section>
    );
  }

  function renderReActResultSection(messageId: string, group: AgentMessageReActOperationGroup) {
    const results = reActResultItems(group, {
      operationLabel,
      readableOperationResult: (operation) => readableOperationResult(operation, operationDetailLabels.structuredResultFallback),
    });
    if (results.length === 0) {
      return null;
    }
    const sectionId = `feedback-react-results-${group.id}`;
    const bodyId = `${sectionId}-body`;
    const expanded = getExpansionState(messageId, sectionId, false);
    const label = lang === "zh"
      ? results.length > 1 ? `结果 ${results.length}` : "结果"
      : results.length > 1 ? `${results.length} results` : "Result";
    return (
      <section className={styles.reActOperationSection}>
        <VButton
          type="button"
          className={styles.reActResultToggle}
          aria-expanded={expanded}
          aria-controls={bodyId}
          onClick={() => toggleSection(messageId, sectionId, false)}
          title={expanded
            ? lang === "zh" ? "折叠工具结果" : "Collapse tool results"
            : lang === "zh" ? "展开工具结果" : "Expand tool results"}
          trailingIcon={expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
        >
          <span className={styles.reActOperationSectionLabel}>{label}</span>
        </VButton>
        {expanded ? (
          <div id={bodyId} className={styles.reActResultList}>
            {results.map((item) => (
              <div
                key={item.id}
                className={`${styles.reActResultItem} ${item.tone === "failed" ? styles.reActResultItem_failed : ""}`}
              >
                <span className={styles.reActResultLabel}>{item.label}</span>
                <pre className={styles.reActResultValue}>{item.value}</pre>
              </div>
            ))}
          </div>
        ) : null}
      </section>
    );
  }

  function renderReActOperationContent(messageId: string, group: AgentMessageReActOperationGroup) {
    return (
      <div className={styles.reActOperationBody}>
        {renderReActThoughtSection(group)}
        {renderReActActionSection(group)}
        {renderReActResultSection(messageId, group)}
      </div>
    );
  }

  function feedbackTimelineGroups(operations: AgentMessageOperation[]) {
    const visibleOperations = compactVisibleTimelineOperations(operations.filter(shouldShowTimelineOperation));
    return {
      visibleOperations,
      reActGroups: buildAgentMessageReActOperationGroups(visibleOperations),
    };
  }

  function renderFeedbackTimelineDetails(messageId: string, operations: AgentMessageOperation[]) {
    const { reActGroups } = feedbackTimelineGroups(operations);
    if (reActGroups.length === 0) {
      return null;
    }
    return (
      <div className={styles.reActOperationList}>
        {reActGroups.map((group) => (
          <div key={group.id}>
            {renderReActOperationContent(messageId, group)}
          </div>
        ))}
      </div>
    );
  }

  function renderOperationGroup(
    messageId: string,
    section: "thought" | "mental" | "tools",
    operations: AgentMessageOperation[],
    defaultExpanded: boolean,
  ) {
    if (operations.length === 0) {
      return null;
    }
    const expanded = getExpansionState(messageId, section, defaultExpanded);
    const kind = operations[0]?.kind ?? "tool";
    const title = operationGroupTitle(kind, operations.length);
    const toggleTitle = expanded
      ? section === "thought"
        ? t("thoughtProcessVisible")
        : section === "mental"
          ? t("mentalProcessVisible")
          : t("toolProcessVisible")
      : section === "thought"
        ? t("thoughtProcessHidden")
        : section === "mental"
          ? t("mentalProcessHidden")
          : t("toolProcessHidden");
    return (
      <section className={styles.operationGroup}>
        <VButton
          type="button"
          className={styles.operationSummary}
          aria-expanded={expanded}
          onClick={() => toggleSection(messageId, section, defaultExpanded)}
          title={toggleTitle}
          icon={operationIcon(kind, title)}
          trailingIcon={expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        >
          <span>{title}</span>
          {!expanded && operations[0]?.summary ? (
            <span className={styles.operationSummaryPreview}>{operations[0].summary}</span>
          ) : null}
        </VButton>
        {expanded ? renderOperationTimeline(operations) : null}
      </section>
    );
  }

  function renderFeedbackTimelineGroup(
    messageId: string,
    operations: AgentMessageOperation[],
    defaultExpanded: boolean,
    processSectionIds?: string,
  ) {
    if (operations.length === 0) {
      return null;
    }
    const { visibleOperations, reActGroups } = feedbackTimelineGroups(operations);
    if (visibleOperations.length === 0) {
      return null;
    }
    if (reActGroups.length === 0) {
      return null;
    }
    const defaultTimelineExpanded = defaultExpanded || reActGroups.some((group) => shouldExpandReActGroupByDefault(group));
    const expanded = getExpansionState(messageId, "feedback", defaultTimelineExpanded);
    const title = operationTimelineTitle(visibleOperations);
    const collectionTone = operationCollectionTone(operations);
    const stateLabel = operations.length > visibleOperations.length && collectionTone === "running"
      ? compactInternalProcessStateLabel(collectionTone, operations, operationStateLabels)
      : operationStateLabel(operationCollectionTone(visibleOperations), operationStateLabels);
    return (
      <section
        className={`${styles.operationGroup} ${styles.executionTraceGroup}`}
        data-agent-process-section-ids={processSectionIds}
        data-agent-process-kind={processSectionIds ? "feedback" : undefined}
      >
        <VButton
          type="button"
          className={styles.operationSummary}
          aria-expanded={expanded}
          onClick={() => toggleSection(messageId, "feedback", defaultTimelineExpanded)}
          title={expanded ? t("executionDetailsVisible") : t("executionDetailsHidden")}
          icon={operationIcon(operations[0]?.kind ?? "tool", title)}
          trailingIcon={expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        >
          <span>{title}</span>
          <span className={styles.operationSummaryCount}>{stateLabel}</span>
        </VButton>
        {expanded ? renderFeedbackTimelineDetails(messageId, operations) : null}
      </section>
    );
  }

  function renderAnswerOnlyProcessGroup(
    messageId: string,
    operations: AgentMessageOperation[],
    defaultExpanded: boolean,
    renderDetails: () => ReactNode,
    inlinePreview?: string,
    processSectionIds?: string,
  ) {
    if (operations.length === 0) {
      return null;
    }
    const tone = operationCollectionTone(operations);
    const toneStyle = styles[`answerOnlyProcessGroup_${tone}` as keyof typeof styles] ?? "";
    const expanded = getExpansionState(messageId, "process", defaultExpanded);
    const preview = inlinePreview || processSummaryPreview(operations, operationStateLabels, compactPreview);
    const title = processSummaryTitle(tone, operations, operationStateLabels);
    const meta = processSummaryMeta(operations, operationStateLabels);
    const hasExpandableDetails = operations.some(shouldShowTimelineOperation);
    if (!hasExpandableDetails) {
      return null;
    }
    const summaryContent = (
      <>
        <span className={styles.answerOnlyProcessIcon} aria-hidden="true">
          {processSummaryIcon(tone)}
        </span>
        <span className={styles.answerOnlyProcessTitle}>{title}</span>
        {meta ? <span className={styles.answerOnlyProcessMeta}>{meta}</span> : null}
      </>
    );
    return (
      <section
        className={[styles.answerOnlyProcessGroup, toneStyle].filter(Boolean).join(" ")}
        data-agent-process-section-ids={processSectionIds}
        data-agent-process-kind={processSectionIds ? "answer-only" : undefined}
      >
        <VButton
          type="button"
        contentLayout="plain"
          className={styles.answerOnlyProcessToggle}
          aria-expanded={expanded}
          onClick={() => toggleSection(messageId, "process", defaultExpanded)}
          title={expanded ? t("executionDetailsVisible") : t("executionDetailsHidden")}
        >
          {summaryContent}
          {preview ? <span className={styles.answerOnlyProcessPreview}>{preview}</span> : null}
          {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </VButton>
        {expanded ? <div className={styles.answerOnlyProcessDetails}>{renderDetails()}</div> : null}
      </section>
    );
  }

  function shouldExpandToolGroupByDefault(message: ConversationMessage, operations: AgentMessageOperation[]) {
    return Boolean(message.streaming)
      || operations.some((operation) => operation.kind === "tool" && (operation.rawLabel ?? operation.label) === COMPUTER_USE_TOOL_NAME);
  }

  function renderAgentMentalPanel(
    messageId: string,
    part: AgentMentalPart | undefined,
    defaultExpandedOverride: boolean | undefined,
    isRunning: boolean,
  ) {
    if (!showMentalSnapshots || !part || !part.snapshot) {
      return null;
    }
    const snapshot = part.snapshot;
    const expanded = getExpansionState(messageId, "mental", defaultExpandedOverride ?? true);
    const toggleTitle = expanded ? t("mentalProcessVisible") : t("mentalProcessHidden");
    const mentalLabels: MentalStateLabels = {
      feeling: t("mentalFeeling"),
      summary: t("mentalSummary"),
      feelingSummary: `${t("mentalFeeling")} / ${t("mentalSummary")}`,
      mood: t("mentalMood"),
      cognitiveState: t("mentalCognitiveState"),
      source: t("mentalSource"),
      confidence: t("mentalConfidence"),
      samples: t("mentalSamples"),
      lastUpdated: t("mentalLastUpdated"),
      whisper: t("mentalWhisper"),
      intervention: t("mentalIntervention"),
      cognitiveStateUnknown: t("mentalCognitiveState_unknown"),
      cognitiveStateNormal: t("mentalCognitiveState_normal"),
      cognitiveStateProductive: t("mentalCognitiveState_productive"),
      cognitiveStateLooping: t("mentalCognitiveState_looping"),
      cognitiveStateThrashing: t("mentalCognitiveState_thrashing"),
      cognitiveStateTunnelVision: t("mentalCognitiveState_tunnel_vision"),
      cognitiveStateDisoriented: t("mentalCognitiveState_disoriented"),
      sourceState: t("mentalSourceState"),
      sourceDiagnosis: t("mentalSourceDiagnosis"),
      sourceRuntime: t("runtime"),
    };
    const mentalFormatters: MentalStateFormatters = {
      compactPreview,
      formatTimestamp,
    };
    const metaRows = buildMentalMetaRows(snapshot, mentalLabels, mentalFormatters);
    const bodyRows = buildMentalBodyRows(snapshot, mentalLabels);
    const preview = mentalSnapshotPreview(snapshot, mentalLabels, mentalFormatters);
    return (
      <section className={`${styles.auxiliaryBlock} ${styles.auxiliaryBlock_mental}`}>
        <VButton
          type="button"
          className={styles.operationSummary}
          aria-expanded={expanded}
          onClick={() => toggleSection(messageId, "mental", defaultExpandedOverride ?? true)}
          title={toggleTitle}
          icon={<BrainCircuit size={17} />}
          trailingIcon={
            <>
              {isRunning ? <LoaderCircle className={styles.statusSpinner} size={14} /> : null}
              {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
            </>
          }
        >
          <span>{t("mentalProcess")}</span>
          {!expanded && preview ? (
            <span className={styles.operationSummaryPreview}>{preview}</span>
          ) : null}
        </VButton>
        {expanded ? (
          <div className={`${styles.auxiliaryPanel} ${styles.auxiliaryPanel_mental}`}>
            {metaRows.length ? (
              <div className={styles.mentalMetaGrid}>
                {metaRows.map((row) => (
                  <span key={row.label} className={styles.mentalMetaItem}>
                    <small>{row.label}</small>
                    <strong>{row.value}</strong>
                  </span>
                ))}
              </div>
            ) : null}
            {bodyRows.length ? (
              <div className={styles.mentalBodyList}>
                {bodyRows.map((row) => (
                  <p key={row.label} className={styles.mentalBodyRow}>
                    <span>{row.label}</span>
                    {row.value}
                  </p>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
      </section>
    );
  }

  function responseSegmentLabel(segment: ResponseSegment) {
    return resolveResponseSegmentLabel(segment, (key) => t(key));
  }

  function renderResponseSegment(segment: ResponseSegment, duplicateImageUrls?: Set<string>) {
    const label = responseSegmentLabel(segment);
    return (
      <section
        key={segment.id}
        className={`${styles.responseSegment} ${styles[`responseSegment_${segment.kind}`]}`}
      >
        <div className={styles.responseSegmentHeader}>
          <span className={styles.responseSegmentLabel}>{label}</span>
          {segment.language && segment.kind !== "code" ? (
            <span className={styles.responseSegmentMeta}>{segment.language}</span>
          ) : null}
        </div>
        {isResponseSegmentCodeLike(segment) ? (
          <pre className={styles.responseSegmentPre}>
            <code>{formattedCodeBlockContent(segment.content, segment.language)}</code>
          </pre>
        ) : (
          renderResponseText(segment.content, duplicateImageUrls)
        )}
      </section>
    );
  }

  function shouldShowAgentResponseBlock(
    message: ConversationMessage,
    sectionState: AgentMessageSectionState,
    hasFeedbackTimeline: boolean,
  ) {
    return resolveShouldShowAgentResponseBlock({
      hasResponseBlock: sectionState.hasResponseBlock,
      answerText: sectionState.answerText,
      hasFeedbackTimeline,
      streaming: Boolean(message.streaming),
      segments: getCachedResponseSegments(sectionState.answerText),
    });
  }

  function renderResponseText(content: string, duplicateImageUrls?: Set<string>) {
    return (
      <LazyConversationMarkdownRenderer
        content={content}
        duplicateImageUrls={duplicateImageUrls}
        renderImage={renderMarkdownImage}
      />
    );
  }

  function renderStreamingResponseText(content: string) {
    if (!content) {
      return null;
    }
    return (
      <ConversationStreamingResponseContent
        content={content}
      />
    );
  }

  function renderMarkdownImage(alt: string, url: string, duplicateImageUrls?: Set<string>) {
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
  }

  function isNonNullNode<T>(node: T | null): node is T {
    return node !== null;
  }

  const composerActions = (
    <div className={styles.composerActionStack}>
      {!runningGuidanceActionsEnabled || showSafeGuidanceAction ? (
        <VButton
          className={primaryActionClassName}
          isIconOnly={!primaryActionIsEditSubmit}
          isDisabled={runningGuidanceActionsEnabled ? guidanceActionDisabled || !onSafeGuidance : resolvedActionDisabled}
          type="button"
          onClick={runningGuidanceActionsEnabled ? onSafeGuidance : handlePrimaryAction}
          icon={
            primaryActionIsEditSubmit
              ? (
                composerPending || composerSafeGuidancePending
                  ? <LoaderCircle className={styles.statusSpinner} size={14} aria-hidden="true" />
                  : <RefreshCw size={14} aria-hidden="true" />
              )
              : undefined
          }
          title={
            runningGuidanceActionsEnabled
              ? composerSafeGuidancePending
                ? (safeGuidancePendingLabel ?? t("safeGuidancePending"))
                : (safeGuidanceLabel ?? t("safeGuidance"))
              : composerPending
                ? resolvedPendingLabel
                : resolvedActionLabel
          }
          aria-label={
            runningGuidanceActionsEnabled
              ? composerSafeGuidancePending
                ? (safeGuidancePendingLabel ?? t("safeGuidancePending"))
                : (safeGuidanceLabel ?? t("safeGuidance"))
              : composerPending
                ? resolvedPendingLabel
                : resolvedActionLabel
          }
        >
          {primaryActionIsEditSubmit
            ? (composerPending || composerSafeGuidancePending ? resolvedPendingLabel : resolvedActionLabel)
            : (composerPending || composerSafeGuidancePending
              ? <LoaderCircle className={styles.statusSpinner} size={17} aria-hidden="true" />
              : <ArrowUp size={16} aria-hidden="true" />)}
        </VButton>
      ) : null}
      {runningGuidanceActionsEnabled ? (
        <VButton
          className={`${styles.sendButton} ${styles.composerRoundButton} ${styles.stopButton}`}
          isIconOnly
          isDisabled={resolvedActionDisabled}
          type="button"
          onClick={handlePrimaryAction}
          title={composerPending ? resolvedPendingLabel : resolvedActionLabel}
          aria-label={composerPending ? resolvedPendingLabel : resolvedActionLabel}
        >
          {composerPending ? (
            <LoaderCircle className={styles.statusSpinner} size={17} aria-hidden="true" />
          ) : (
            <Square size={14} aria-hidden="true" />
          )}
        </VButton>
      ) : null}
    </div>
  );

  return (
    <div
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

      <div ref={timelineRef} className={styles.timeline}>
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
            </div>
          )
        ) : (
          <div ref={timelineContentRef} className={styles.timelineContent}>
            {timelineVirtualRange.topSpacerPx > 0 ? (
              <div
                aria-hidden="true"
                className={styles.timelineVirtualSpacer}
                style={{ height: timelineVirtualRange.topSpacerPx }}
              />
            ) : null}
            {virtualTimelineMessages.map((message, virtualIndex) => {
              const index = timelineVirtualRange.start + virtualIndex;
              const rowIdentity = virtualTimelineRowIdentities[virtualIndex] ?? activeTimelineRowIdentities[index];
              const rowKey = rowIdentity?.rowKey ?? message.id;
              return (
              <div
                key={rowKey}
                ref={timelineVirtualRowRef(rowKey)}
                className={styles.timelineVirtualRow}
                data-conversation-virtual-row={rowKey}
              >
              <ConversationTurnRow
                message={message}
                previousMessage={activeTimelineMessages[index - 1]}
                agentMessage={agentMessagesByMessageId.get(message.id)}
                agentRenderState={agentRenderStatesByMessageId.get(message.id)}
                previousAgentRenderState={
                  activeTimelineMessages[index - 1]
                    ? agentRenderStatesByMessageId.get(activeTimelineMessages[index - 1].id)
                    : undefined
                }
                codexTranscriptCells={agentCodexSurfacesByMessageId.get(message.id)?.cells}
                rowIdentity={rowIdentity}
                defaultResponseExpanded={defaultExpandedResponseIds.has(message.id)}
                latestUserMessageId={latestUserMessageId}
                editingMessageId={editingMessageId}
                editUserMessageLabel={editUserMessageLabel}
                editUserMessageDisabled={editUserMessageDisabled}
                composerPlaceholder={composerPlaceholder}
                answerOnlyProcessMode={answerOnlyProcessMode}
                showMentalSnapshots={showMentalSnapshots}
                lang={lang}
                assistantLabel={assistantLabel}
                assistantAvatarImageUrl={assistantAvatarImageUrl}
                assistantAvatarFallback={assistantAvatarFallback}
                userLabel={userLabel}
                userAvatarLabel={userAvatarLabel}
                userAvatarImageUrl={userAvatarImageUrl}
                operationLabels={operationLabels}
                resolveTurnAvatar={resolveTurnAvatar}
                onEditUserMessage={onEditUserMessage}
                sectionExpansionForMessage={sectionExpansion[message.id] ?? EMPTY_SECTION_EXPANSION}
                computerUseStateForMessage={buildComputerUseStateForMessage(
                  message,
                  computerUseSessionResults,
                  computerUseSessionPending,
                )}
                imageArtifactUrlsBeforeMessage={imageArtifactUrlsBeforeMessage.get(message.id)}
                renderTurn={() => {
            const rowIdentity = activeTimelineRowIdentities[index];
            if (isCliAgentLifecycleMessage(message)) {
              const detail = cliAgentLifecycleDetail(message);
              return (
                <article
                  key={rowIdentity?.rowKey ?? message.id}
                  className={styles.cliAgentLifecycleTurn}
                  data-conversation-row-key={rowIdentity?.rowKey ?? message.id}
                >
                  <span className={styles.cliAgentLifecycleIcon} aria-hidden="true">
                    <TerminalSquare size={14} />
                  </span>
                  <span className={styles.cliAgentLifecycleText}>
                    {cliAgentLifecycleLabel(message, lang)}
                  </span>
                  {detail ? <code className={styles.cliAgentLifecycleMeta}>{detail}</code> : null}
                  {message.timestamp ? (
                    <span className={styles.cliAgentLifecycleTime}>{formatTimestamp(message.timestamp)}</span>
                  ) : null}
                </article>
              );
            }
            const agentMessage = agentMessagesByMessageId.get(message.id);
            if (!agentMessage) {
              return null;
            }
            const baseOperationGroups = agentOperationGroupsByMessageId.get(agentMessage.id)
              ?? buildAgentMessageOperationGroups(agentMessage, operationLabels);
            const operationGroups = operationGroupsWithFeedbackStatusPlaceholder(baseOperationGroups, message, lang);
            const agentRenderState = agentRenderStatesByMessageId.get(message.id) ?? buildAgentMessageRenderState(agentMessage);
            const agentSections = agentRenderState.sectionState;
            const processSections = agentRenderState.processSections;
            const responseText = agentSections.answerText;
            const noFinalAnswerStatusText = isNoFinalAnswerStatusContent(responseText)
              ? responseText.trim()
              : "";
            const userContentText = agentSections.userText;
            const hasActiveProcess = operationGroups.timeline.some((operation) => isRunningOperationStatus(operation.status));
            const hasFeedbackTimeline = agentSections.hasFeedbackTimeline;
            const showResponseBlock = shouldShowAgentResponseBlock(message, agentSections, hasFeedbackTimeline);
            const turnErrorMessage = isTurnErrorMessage(message);
            const imageArtifact = imageArtifactForMessage(message);
            const agentInboxMessage = isAgentInboxMessage(message);
            const groupTranscriptMessage = isGroupRoomTranscriptMessage(message);
            const previousMessage = activeTimelineMessages[index - 1];
            const previousAgentRenderState = previousMessage
              ? agentRenderStatesByMessageId.get(previousMessage.id)
              : undefined;
            const compactTurnHeader = shouldCompactConversationTurnHeader(
              previousMessage,
              message,
              previousAgentRenderState?.sectionState,
              agentSections,
            );
            const codexTranscriptSurface = agentCodexSurfacesByMessageId.get(agentMessage.id);
            const codexTranscriptCells = codexTranscriptSurface?.cells ?? [];
            // Phase C: display plan picks package_cells vs legacy; single track for final answer.
            const displayPlanSeed = resolveAssistantDisplayPlan({
              message,
              surface: codexTranscriptSurface,
              serverTimelineItems: message.timelineItems,
            });
            const shouldRenderLegacyTurnError = Boolean(
              turnErrorMessage && !displayPlanSeed.suppressProjectedError,
            );
            const timelineOptions = {
              lang,
              includeAssistantText: displayPlanSeed.includeTimelineAssistantText,
            };
            const timelineServerItems = filterServerTimelineItemsForDisplayPlan(
              message.timelineItems,
              displayPlanSeed,
            );
            const agentMessageTimelineItems = buildAgentMessageTimelineItems(
              agentMessage,
              operationGroups.timeline,
              timelineOptions,
              timelineServerItems as typeof message.timelineItems | undefined,
            );
            const hasAgentMessageTimeline =
              message.role === "assistant"
              && hasFeedbackTimeline
              && !turnErrorMessage
              && !agentInboxMessage
              && !groupTranscriptMessage
              && agentMessageTimelineItems.length > 0;
            const displayPlan = resolveAssistantDisplayPlan({
              message,
              surface: codexTranscriptSurface,
              serverTimelineItems: message.timelineItems,
              builtTimelineItems: agentMessageTimelineItems,
              hasAgentMessageTimeline,
            });
            // Package/native ownership never lets timeline re-own the final body.
            const timelineRendersAssistantText = displayPlan.renderMode === "legacy"
              && displayPlan.timelineOwnsFinalAnswer;
            const shouldRenderNativeProcessTimeline = displayPlan.shouldRenderNativeProcessAlongsideAnswer;
            const showUserContent = agentSections.hasUserContent;
            const userAuthoredMessage = message.role === "user" && !agentInboxMessage;
            const isStreamingStatusPlaceholder = Boolean(message.streaming)
              && showResponseBlock
              && answerOnlyProcessMode
              && isStreamingStatusPlaceholderContent(responseText);
            const isResponseStreaming = Boolean(message.streaming) && showResponseBlock && !isStreamingStatusPlaceholder;
            const showResponseSpinner = isResponseStreaming && !hasActiveProcess;
            const defaultResponseExpanded = Boolean(message.streaming) || defaultExpandedResponseIds.has(message.id);
            const responseExpanded = getExpansionState(message.id, "response", defaultResponseExpanded);
            const responseSegments = showResponseBlock && !isStreamingStatusPlaceholder && !isResponseStreaming
              ? getCachedResponseSegments(responseText)
              : [];
            const codexTranscriptNode = (
              displayPlan.shouldRenderCodexSurface
              && !agentInboxMessage
              && !groupTranscriptMessage
            )
              ? renderCodexTranscriptCells(message, codexTranscriptCells, rowIdentity)
              : null;
            // Only force the answer body open while tokens are still streaming.
            // Tying this to defaultResponseExpanded made the last few answers
            // impossible to collapse (toggle flipped aria state but body stayed).
            const shouldForceResponseBodyVisible = isResponseStreaming;
            const isEditingMessage = userAuthoredMessage && message.id === editingMessageId;
            const agentInboxExpanded = getExpansionState(message.id, "agentInbox", false);
            const agentInboxPreview = agentInboxMessage ? compactPreview(agentInboxSummary(message), 140) : "";
            const researchOrgChips = researchOrgMessageChips(message);
            const contextNode = (agentRenderState.contextSections?.length ?? 0) > 0 ? (
              <React.Suspense fallback={null}>
                <AgentContextSectionsView sections={agentRenderState.contextSections} lang={lang} />
              </React.Suspense>
            ) : null;
            const turnClassName = [
              groupTranscriptMessage
                ? styles.groupTranscriptTurn
                : message.role === "assistant"
                  ? styles.assistantTurn
                  : agentInboxMessage
                  ? styles.agentInboxTurn
                  : styles.userTurn,
              turnErrorMessage ? styles.turnErrorTurn : "",
              compactTurnHeader ? styles.assistantTurnContinuation : "",
              isEditingMessage ? styles.turnEditing : "",
            ].filter(Boolean).join(" ");
            const speakerLabel = groupTranscriptMessage
              ? groupRoomTranscriptLabel(message)
              : message.role === "assistant"
                ? assistantLabel
                : agentInboxMessage
                  ? agentInboxSourceLabel(message)
                  : userLabel;
            const editDisabled = Boolean(editUserMessageDisabled);
            const processTone = operationCollectionTone(operationGroups.timeline);
            const processDefaultExpanded = processTone === "running";
            const renderAgentProcessDetails = (defaultExpandedOverride?: boolean) => (
              <>
                {renderOperationGroup(
                  message.id,
                  "thought",
                  operationGroups.thoughts,
                  defaultExpandedOverride ?? Boolean(message.streaming),
                )}
                {renderAgentMentalPanel(
                  message.id,
                  latestAgentMentalPart(processSections),
                  defaultExpandedOverride,
                  Boolean(message.streaming) && operationGroups.tools.length === 0 && !agentSections.hasResponseBlock,
                )}
                {renderOperationGroup(
                  message.id,
                  "tools",
                  operationGroups.tools,
                  defaultExpandedOverride ?? shouldExpandToolGroupByDefault(message, operationGroups.tools),
                )}
              </>
            );
            const renderProcessDetails = () => {
              if (hasAgentMessageTimeline) {
                return renderAgentMessageTimeline(message, agentMessageTimelineItems, rowIdentity, agentRenderState.processSectionIds);
              }
              if (hasFeedbackTimeline) {
                return renderFeedbackTimelineDetails(message.id, operationGroups.timeline);
              }
              return renderAgentProcessDetails(true);
            };
            // package_cells / native_transcript: final body lives in codex cells only.
            const responseSectionNode = (
              displayPlan.renderMode === "legacy"
              && !displayPlan.suppressProjectedResponse
              && showResponseBlock
              && !isStreamingStatusPlaceholder
              && !timelineRendersAssistantText
            ) ? (
              <AgentResponseSectionView
                answerKey={rowIdentity.answerKey}
                answerContentSectionIds={agentRenderState.answerContentSectionIds}
                expanded={responseExpanded}
                label={t("responseLabel")}
                expandedTitle={t("responseHidden")}
                collapsedTitle={t("responseVisible")}
                showSpinner={showResponseSpinner}
                forceBodyVisible={shouldForceResponseBodyVisible}
                onToggle={() => toggleSection(message.id, "response", defaultResponseExpanded)}
              >
                {isResponseStreaming
                  ? renderStreamingResponseText(responseText)
                  : responseSegments.map((segment) =>
                    renderResponseSegment(segment, imageArtifactUrlsBeforeMessage.get(message.id)),
                  )}
              </AgentResponseSectionView>
            ) : null;
            // Process rail: suppressed when cells already carry tools; otherwise timeline/legacy.
            const processNode = displayPlan.suppressProjectedProcess
              ? null
              : shouldRenderNativeProcessTimeline
                ? renderAgentMessageTimeline(message, agentMessageTimelineItems, rowIdentity, agentRenderState.processSectionIds)
                : displayPlan.renderMode === "package_cells"
                  // Package answer is in cells; only render non-answer process timeline if any.
                  ? (
                    hasAgentMessageTimeline
                      ? renderAgentMessageTimeline(message, agentMessageTimelineItems, rowIdentity, agentRenderState.processSectionIds)
                      : hasFeedbackTimeline
                        ? renderFeedbackTimelineGroup(
                          message.id,
                          operationGroups.timeline,
                          false,
                          agentRenderState.processSectionIds,
                        )
                        : null
                  )
                  : answerOnlyProcessMode && !timelineRendersAssistantText
                    ? renderAnswerOnlyProcessGroup(
                      message.id,
                      operationGroups.timeline,
                      processDefaultExpanded,
                      renderProcessDetails,
                      isStreamingStatusPlaceholder ? compactStreamingStatusPlaceholder(responseText, compactPreview) : undefined,
                      agentRenderState.processSectionIds,
                    )
                    : hasAgentMessageTimeline
                      ? renderAgentMessageTimeline(message, agentMessageTimelineItems, rowIdentity, agentRenderState.processSectionIds)
                      : hasFeedbackTimeline
                        ? renderFeedbackTimelineGroup(
                          message.id,
                          operationGroups.timeline,
                          false,
                          agentRenderState.processSectionIds,
                        )
                        : renderAgentProcessDetails();
            const turnStatusNode = !displayPlan.suppressProjectedTurnStatus && noFinalAnswerStatusText ? (
              <div className={styles.turnStatusNote} role="status" aria-live="polite">
                <span className={styles.turnStatusLabel}>{lang === "zh" ? "状态" : "Status"}</span>
                <span className={styles.turnStatusText}>{noFinalAnswerStatusText}</span>
              </div>
            ) : null;
            const compactActiveTurnPlaceholderNode = shouldRenderCompactActiveTurnPlaceholder(message, {
              showResponseBlock,
              hasFeedbackTimeline,
              hasActiveProcess,
              turnErrorMessage,
            }) ? (
              <ConversationActiveTurnStatusNote
                message={message}
                lang={lang}
                statusLabel={lang === "zh" ? "状态" : "Status"}
              />
            ) : null;
            return (
              <AgentMessageTurnView
                key={rowIdentity.rowKey}
                rowKey={rowIdentity.rowKey}
                messageKey={rowIdentity.messageKey}
                agentMessageId={agentMessage.id}
                sectionCount={agentSections.sectionCount}
                sectionKinds={agentRenderState.sectionKinds}
                className={turnClassName}
                compactHeader={false}
                avatar={
                  <ConversationTurnAvatarContent
                    content={resolveMessageTurnAvatar(message, {
                      resolveTurnAvatar,
                      assistantAvatarImageUrl,
                      assistantAvatarFallback,
                      assistantLabel,
                      userAvatarImageUrl,
                      userAvatarLabel,
                      agentInboxMessage,
                      groupTranscriptMessage,
                    })}
                  />
                }
                speakerLabel={speakerLabel}
                identityAccessory={
                  isEditingMessage ? <span className={styles.turnEditBadge}>{t("editMessage")}</span> : null
                }
                metaActions={
                  <>
                    {message.timestamp ? <span>{formatTimestamp(message.timestamp)}</span> : null}
                    {userAuthoredMessage && message.id === latestUserMessageId && onEditUserMessage ? (
                      <VButton
                        type="button"
                        className={
                          isEditingMessage
                            ? `${styles.turnIconButton} ${styles.turnIconButtonActive}`
                            : styles.turnIconButton
                        }
                        onClick={() => onEditUserMessage(message)}
                        isDisabled={editDisabled}
                        aria-pressed={isEditingMessage}
                        title={editDisabled ? composerPlaceholder : editUserMessageLabel ?? t("editMessage")}
                        aria-label={editUserMessageLabel ?? t("editMessage")}
                        isIconOnly
                        icon={<Pencil size={14}/>} />
                    ) : null}
                  </>
                }
              >

                  <span
                    hidden
                    data-codex-transcript-cell-count={codexTranscriptCells.length}
                    data-codex-transcript-surface-mode={codexTranscriptSurface?.mode ?? "empty"}
                    data-codex-transcript-native-primary={displayPlan.nativePrimary ? "true" : "false"}
                    data-assistant-render-mode={displayPlan.renderMode}
                    data-assistant-has-turn-item-package={displayPlan.hasTurnItemPackage ? "true" : "false"}
                    data-codex-transcript-projection-gap-reason={codexTranscriptSurface?.projectionGap?.reason ?? ""}
                    data-codex-transcript-projection-gap-projected-cell-count={codexTranscriptSurface?.projectionGap?.projectedCellCount ?? 0}
                  />
                  {agentInboxMessage ? (
                    <section className={styles.agentInboxSection}>
                      {researchOrgChips.length > 0 ? (
                        <div className={styles.researchOrgChipRow} aria-label={lang === "zh" ? "科研组织消息标签" : "Research organization message labels"}>
                          {researchOrgChips.map((chip) => (
                            <span
                              key={chip.key}
                              className={`${styles.researchOrgChip} ${styles[`researchOrgChip_${chip.tone}`]}`}
                            >
                              {chip.label}
                            </span>
                          ))}
                        </div>
                      ) : null}
                      <VButton
                        type="button"
                        className={styles.agentInboxToggle}
                        aria-expanded={agentInboxExpanded}
                        onClick={() => toggleSection(message.id, "agentInbox", false)}
                        title={agentInboxExpanded ? (lang === "zh" ? "折叠私信内容" : "Collapse private message") : (lang === "zh" ? "展开私信内容" : "Expand private message")}
                        icon={agentInboxExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}><span>{lang === "zh" ? "私信内容" : "Private message"}</span>
                        {agentInboxPreview ? <span className={styles.agentInboxPreview}>{agentInboxPreview}</span> : null}</VButton>
                      {agentInboxExpanded ? (
                        <div className={styles.agentInboxMessageBody}>
                          {renderResponseText(message.content)}
                        </div>
                      ) : null}
                    </section>
                  ) : showUserContent ? (
                    <AgentUserContentSectionView userContentSectionIds={agentRenderState.userContentSectionIds}>
                      {renderResponseText(userContentText)}
                    </AgentUserContentSectionView>
                  ) : null}
                  {groupTranscriptMessage ? (
                    <div className={styles.groupTranscriptBody}>{renderResponseText(message.content)}</div>
                  ) : null}
                  {contextNode}

                  {/*
                    Codex-aligned order: process / tools first, then final answer surface.
                    - renderCodexTranscriptCells already does processCells → finalCells inside.
                    - When tools only exist on feedback/timeline (alongside), processNode must
                      still precede codexTranscriptNode so the answer is not above the tools.
                  */}
                  {processNode}
                  {compactActiveTurnPlaceholderNode}
                  {codexTranscriptNode}
                  {turnStatusNode}
                  {shouldRenderLegacyTurnError ? (
                    <div className={styles.turnErrorNotice} role="status" aria-live="polite">
                      <div className={styles.turnErrorNoticeIcon} aria-hidden="true">
                        <TerminalSquare size={15} />
                      </div>
                      <div className={styles.turnErrorNoticeBody}>
                        <div className={styles.turnErrorNoticeMeta}>
                          <span>{lang === "zh" ? "运行提示" : "Runtime notice"}</span>
                          {resolveConversationTurnErrorType(message) ? <span>{resolveConversationTurnErrorType(message)}</span> : null}
                        </div>
                        <div className={styles.turnErrorNoticeText}>{renderResponseText(message.content)}</div>
                        {buildConversationTurnErrorReasonRows(message, lang).length > 0 ? (
                          <details className={styles.turnErrorDiagnostics}>
                            <summary className={styles.turnErrorDiagnosticsSummary}>
                              {lang === "zh" ? "诊断详情" : "Diagnostics"}
                            </summary>
                            <dl className={styles.turnErrorReasonList}>
                              {buildConversationTurnErrorReasonRows(message, lang).map((row) => (
                                <div key={`${row.label}-${row.value}`} className={styles.turnErrorReasonRow}>
                                  <dt>{row.label}</dt>
                                  <dd>{row.value}</dd>
                                </div>
                              ))}
                            </dl>
                          </details>
                        ) : null}
                      </div>
                    </div>
                  ) : null}
                  {answerOnlyProcessMode ? responseSectionNode : null}
                  {imageArtifact ? (
                    <ConversationImageArtifactView
                      artifact={imageArtifact}
                      lang={lang}
                      onPreviewImage={openImagePreview}
                    />
                  ) : null}

                  {!answerOnlyProcessMode ? responseSectionNode : null}
              </AgentMessageTurnView>
            );
                }}
              />
              </div>
              );
            })}
            {timelineVirtualRange.bottomSpacerPx > 0 ? (
              <div
                aria-hidden="true"
                className={styles.timelineVirtualSpacer}
                style={{ height: timelineVirtualRange.bottomSpacerPx }}
              />
            ) : null}
          </div>
        )}
      </div>

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
          <span>{t("backToBottom")}</span>
        </VButton>
      ) : null}

      {toolApproval && !toolApprovalConsumedRef.current ? (
        <div className={styles.toolApprovalFallback} data-codex-tool-approval-fallback="true">
          {toolApproval.content}
        </div>
      ) : null}

      {turnError?.message && !hasVisibleTurnErrorMessage ? (
        <div className={styles.turnError} role="status" aria-live="polite">
          <div className={styles.turnErrorText}>
            <span className={styles.turnErrorLabel}>{t("turnErrorLabel")}</span>
            <span>{summarizeCurrentTurnError(turnError, lang)}</span>
            <details className={styles.turnErrorDiagnostics}>
              <summary className={styles.turnErrorDiagnosticsSummary}>
                {lang === "zh" ? "诊断详情" : "Diagnostics"}
              </summary>
              <div className={styles.turnErrorDiagnosticsBody}>
                <span className={styles.turnErrorDetail}>{turnError.message}</span>
                {buildCurrentTurnErrorRows(turnError, lang).map((row) => (
                  <span key={`${row.label}-${row.value}`} className={styles.turnErrorDetail}>
                    {row.label}: {row.value}
                  </span>
                ))}
              </div>
            </details>
          </div>
          {turnError.errorType ? <span className={styles.turnErrorType}>{turnError.errorType}</span> : null}
        </div>
      ) : null}

      {showComposer ? (
      <div className={composerVariant === "codex" ? styles.composerCodex : styles.composer}>
        <div
          className={
            composerDragActive
              ? `${composerVariant === "codex" ? styles.composerFieldCodex : styles.composerField} ${styles.composerFieldDragActive}`
              : composerVariant === "codex" ? styles.composerFieldCodex : styles.composerField
          }
          onDragEnter={handleComposerDragEnter}
          onDragOver={handleComposerDragOver}
          onDragLeave={handleComposerDragLeave}
          onDrop={handleComposerDrop}
        >
          {composerError ? <p className={styles.composerError}>{composerError}</p> : null}
          {composerGuidance ? (
            <div className={styles.composerGuidance} role="status" aria-live="polite" data-composer-guidance>
              <span className={styles.composerGuidanceIcon} aria-hidden="true">i</span>
              <span>{composerGuidance}</span>
            </div>
          ) : null}
          {composerModeNotice ? (
            <div
              className={styles.composerEditModeBar}
              role="status"
              title={composerModeNotice}
              aria-label={composerModeNotice}
            >
              <span className={styles.composerEditModeIcon} aria-hidden="true">
                <Pencil size={14} />
              </span>
              <span className={styles.composerEditModeCopy}>
                <span className={styles.composerEditModeLabel}>{t("editMessage")}</span>
                {composerEditFailureNote ? (
                  <span className={styles.composerEditModeWarning}>{composerEditFailureNote}</span>
                ) : null}
              </span>
              {onCancelComposerMode ? (
                <VButton
                  type="button"
                  className={styles.composerEditModeCancel}
                  onClick={onCancelComposerMode}
                >
                  {cancelComposerModeLabel ?? t("cancelEditMessage")}
                </VButton>
              ) : null}
            </div>
          ) : null}
          {composerAttachments.length ? (
            <div
              className={styles.composerAttachmentTray}
              role="list"
              aria-label={lang === "zh" ? "待发送图片" : "Images to send"}
            >
              {composerAttachments.map((attachment) => (
                <div key={attachment.id} className={styles.composerAttachmentChip} role="listitem">
                  <img className={styles.composerAttachmentThumb} src={attachment.previewUrl} alt={attachment.filename} />
                  <span className={styles.composerAttachmentName} title={attachment.filename}>{attachment.filename}</span>
                  {onRemoveComposerAttachment ? (
                    <VButton
                      className={styles.composerAttachmentRemoveButton}
                      isIconOnly
                      type="button"
                      onClick={() => onRemoveComposerAttachment(attachment.id)}
                      title={lang === "zh" ? "移除图片" : "Remove image"}
                      aria-label={lang === "zh" ? "移除图片" : "Remove image"}
                    >
                      <X size={13} aria-hidden="true" />
                    </VButton>
                  ) : null}
                </div>
              ))}
            </div>
          ) : null}
          {composerReferences.length ? (
            <div
              className={styles.composerReferenceTray}
              role="list"
              aria-label={lang === "zh" ? "待发送会话引用" : "Session references to send"}
            >
              {composerReferences.map((reference) => {
                const referenceId = reference.referenceId || reference.sessionId;
                const title = reference.title || reference.sessionId;
                const agentLabel = reference.agentDisplayName || reference.agentCode || reference.agentId || "";
                return (
                  <div key={referenceId} className={styles.composerReferenceChip} role="listitem">
                    <span className={styles.composerReferenceIcon} aria-hidden="true">
                      <Link2 size={13} />
                    </span>
                    <span className={styles.composerReferenceCopy}>
                      <strong title={title}>{title}</strong>
                      {agentLabel ? <small title={agentLabel}>{agentLabel}</small> : null}
                    </span>
                    {onRemoveComposerReference ? (
                      <VButton
                        type="button"
                        onClick={() => onRemoveComposerReference(referenceId)}
                        title={lang === "zh" ? "移除会话引用" : "Remove session reference"}
                        aria-label={lang === "zh" ? "移除会话引用" : "Remove session reference"}
                        isIconOnly
                        icon={<X size={13} aria-hidden="true"/>} />
                    ) : null}
                  </div>
                );
              })}
            </div>
          ) : null}
          {showSlashSuggestions ? (
            <div
              id={slashSuggestionListId}
              role="listbox"
              aria-label={lang === "zh" ? "斜杠指令" : "Slash commands"}
              className={styles.slashCommandSuggestions}
            >
              {slashSuggestions.map((skill, index) => {
                const description = skill.description?.trim() || skill.name || skill.directoryName;
                return (
                  <div
                    id={`${slashSuggestionListId}-option-${index}`}
                    key={skill.command}
                    role="option"
                    aria-selected={false}
                    className={styles.slashCommandSuggestionOption}
                  >
                    <VButton
                      type="button"
                      className={styles.slashCommandSuggestionButton}
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => handleSlashCommandSuggestion(skill)}
                    >
                      <code className={styles.slashCommandSuggestionCode}>
                        {skill.command}
                      </code>
                      <span className={styles.slashCommandSuggestionDescription}>{description}</span>
                    </VButton>
                  </div>
                );
              })}
            </div>
          ) : null}
          <VNativeTextarea
            ref={composerInputRef}
            className={composerVariant === "codex" ? styles.inputCodex : styles.input}
            value={composerValue}
            disabled={composerDisabled && resolvedActionMode !== "stop"}
            placeholder={composerPlaceholder}
            aria-controls={showSlashSuggestions ? slashSuggestionListId : undefined}
            aria-expanded={showSlashSuggestions ? true : undefined}
            aria-autocomplete={showSlashSuggestions ? "list" : undefined}
            onChange={(event) => onComposerChange(event.target.value)}
            onPaste={(event) => {
              if (!onAddComposerAttachments || attachmentInputDisabled) {
                return;
              }
              const files = Array.from(event.clipboardData.files || []).filter((file) => file.type.startsWith("image/"));
              if (!files.length) {
                return;
              }
              event.preventDefault();
              onAddComposerAttachments(files);
            }}
            onKeyDown={(event) => {
              if (
                shouldSubmitComposerOnKeydown({
                  key: event.key,
                  shiftKey: event.shiftKey,
                  ctrlKey: event.ctrlKey,
                  metaKey: event.metaKey,
                  altKey: event.altKey,
                  isComposing: event.nativeEvent.isComposing,
                })
              ) {
                event.preventDefault();
                if (
                  resolvedActionMode === "send"
                  && !resolvedActionDisabled
                  && (composerValue.trim() || hasComposerAttachments || hasComposerReferences)
                ) {
                  handleSendAndFollowLatest();
                }
              }
            }}
          />
          <div className={composerVariant === "codex" ? styles.composerToolbarCodex : styles.composerToolbar}>
            <div className={styles.composerToolbarStart}>
              <VButton
                className={styles.attachButton}
                isIconOnly
                isDisabled={attachmentInputDisabled || !onAddComposerAttachments}
                type="button"
                onClick={() => attachmentInputRef.current?.click()}
                title={lang === "zh" ? "添加图片" : "Attach image"}
                aria-label={lang === "zh" ? "添加图片" : "Attach image"}
              >
                <ImagePlus size={16} />
              </VButton>
              {permissionControl ? (
                <AgentPermissionPresetControl
                  {...permissionControl}
                  lang={lang}
                  surface="composer"
                />
              ) : null}
            </div>
            <div className={styles.composerToolbarEnd}>
              {llmControl ? <ConversationInferenceControl {...llmControl} /> : null}
              {composerVariant === "codex" ? composerActions : null}
            </div>
          </div>
        </div>
        <VNativeInput
          ref={attachmentInputRef}
          className={styles.hiddenAttachmentInput}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          multiple
          disabled={attachmentInputDisabled}
          onChange={(event) => {
            if (event.currentTarget.files && onAddComposerAttachments) {
              onAddComposerAttachments(event.currentTarget.files);
            }
            event.currentTarget.value = "";
          }}
        />
        {composerVariant === "compact" ? composerActions : null}
      </div>
      ) : null}
      {previewImage ? (
        <React.Suspense fallback={null}>
          <ConversationImagePreviewDialog image={previewImage} lang={lang} onClose={closeImagePreview} />
        </React.Suspense>
      ) : null}
    </div>
  );
}
