import {
  ArrowDown,
  ArrowUp,
  BookOpen,
  BrainCircuit,
  CheckCircle2,
  CircleDot,
  CirclePlus,
  Cpu,
  FileText,
  Gauge,
  ImagePlus,
  Link2,
  LoaderCircle,
  MessageSquareText,
  Quote,
  RefreshCw,
  Square,
  X,
  Sparkles,
} from "lucide-react";
import React, { DragEvent, ReactNode, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import type {
  ConversationMessage,
  SessionMessageCurationAction,
} from "../../api/types";
import type {
  AgentMessage,
  AgentMentalPart,
} from "../../agent-thread/types";
import { fetchJson } from "../../api/client";
import { fetchPublicConfig } from "../../api/config";
import { fetchSessionMessageCuration, isFetchJsonHttpError, setSessionMessageCuration } from "../../api/chat";
import { queryKeys } from "../../api/queryKeys";
import { VStateSurface } from "../../components/vui";
import { useAppI18n } from "../../i18n/useAppI18n";
import type { ConversationImagePreviewRequest } from "./ConversationImagePreviewDialog";
import { ConversationForkSessionDialog } from "./ConversationForkSessionDialog";
import { ConversationSelectionQuoteMenu } from "./ConversationSelectionQuoteMenu";
import {
  buildQuotedDraftText,
  extractConversationSelectionSnapshot,
  type ConversationSelectionRect,
} from "./conversationTextSelection";
import { ConversationTranscriptLoadingState } from "./ConversationTranscriptLoadingState";
import { ConversationTurnNavigator } from "./ConversationTurnNavigator";
import {
  buildConversationTurnNavDirectory,
  resolveConversationTurnNavCurrentIndex,
  type ConversationTurnNavEntry,
} from "./conversationTurnNavigation";
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
import { ConversationFollowupQueueBar } from "./ConversationFollowupQueueBar";
import {
  navigatePromptHistory,
  readPromptHistory,
} from "./conversationPromptHistory";
import {
  MAX_COMPOSER_STARTERS,
  resolveComposerPlaceholder,
  shouldAcceptComposerGhost,
  type ComposerStarter,
} from "./composerPromptSuggestionModel";
import { useComposerPromptSuggestion } from "./useComposerPromptSuggestion";
import { resolveComposerQueuePrimaryKind } from "./composerFollowupQueueModel";
import {
  insertSlashCommandSuggestion,
  groupSlashCommandSuggestionsBySection,
  mergeSlashCommandSuggestions,
  moveSlashCommandActiveIndex,
  parseSideSlashCommand,
  shouldShowSlashCommandSuggestions,
  type BuiltinSlashCommand,
  type BuiltinSlashCommandId,
  type SlashCommandSuggestion,
} from "./conversationSlashCommandSuggestions";
import {
  detectReferenceToken,
  filterReferenceTypeaheadOptions,
  removeReferenceToken,
  type ReferenceTypeaheadOption,
  type ReferenceTypeaheadToken,
} from "./conversationReferenceTypeahead";
import { buildAgentMessageRenderState, type AgentMessageRenderState } from "./agentMessageRenderState";
import {
  assistantFinalAnswerText,
  assistantTurnIsInFlight,
  assistantTurnIsStreaming,
} from "../../routes/chatTurnProtocol";
import { buildMessageReferencePayload } from "../../routes/chat/chatComposerSubmitModel";
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
  compactCodexTranscriptCellsAcrossMessages,
  type CodexTranscriptCell,
} from "./codexTranscriptCells";
import { resolveCodexTranscriptSurface, type CodexTranscriptSurface } from "./codexNativeTranscriptSurface";
import {
  captureConversationProcessScrollAnchor,
  restoreConversationProcessScrollAnchor,
} from "./conversationProcessScrollAnchor";
import { ConversationToolActivityPills } from "./ConversationToolActivityPills";
import {
  preserveConversationExpansionDefaults,
  shouldRefreshConversationExpansionDefault,
} from "./conversationExpansionDefaults";
import { type AgentMessageTimelineRowIdentity } from "./agentMessageTimelineRows";
import { useAgentThread } from "./useAgentThread";
import { projectAgentMessageTimelineMessages } from "./useAgentMessageTimelineProjection";
import { projectConversationDisplayMessages } from "./conversationDisplayMessages";
import {
  imageArtifactForMessage,
  isAgentInboxMessage,
  isSteerGuidanceMessage,
  isTurnErrorMessage,
} from "./conversationMessagePredicates";
import {
  shouldLoadEarlierConversationMessages,
  shouldPreferServerEarlierLoad,
  TIMELINE_HISTORY_LOAD_THRESHOLD_PX,
} from "./conversationHistoryWindow";
import { parseResponseSegments, ResponseSegment } from "./messageResponseSegments";
import { ConversationInferenceControl } from "./ConversationInferenceControl";
import { ConversationTurnModelControl } from "./ConversationTurnModelControl";
import { ComposerContextRing } from "./ComposerContextRing";
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
  restoreTimelineRowKeyAnchor,
  type TimelineScrollRowKeyAnchor,
} from "./timelineScrollAnchor";
import {
  buildStreamingTimelineScrollSignal,
  buildTimelineScrollSignal,
} from "./conversationTimelineScrollSignals";
import {
  CONVERSATION_VIRTUAL_ROW_ESTIMATE_PX,
  freshTimelineUserScrollIntent,
  isTimelineNearBottom,
  reconcileFollowingBeforeContentStick,
  resolveTimelineFollowState,
  shouldKeepFollowingLatestOnProcessToggle,
  shouldStickTimelineToBottomOnContentResize,
  TIMELINE_CONTENT_WIDTH_RESIZE_SETTLE_MS,
  timelineKeyboardScrollIntent,
  timelineTouchScrollIntent,
  timelineWheelScrollIntent,
  type TimelineScrollSource,
  type TimelineUserScrollIntent,
} from "./conversationTimelineFollowState";
import {
  peekSessionTimelineScroll,
  rememberSessionTimelineScroll,
  restoreSessionTimelineScroll,
} from "./conversationSessionScrollMemory";
import {
  conversationPerformanceNowMs,
  transcriptCellSequenceMatches,
} from "./conversationTurnRowMemo";
import {
  extractComposerImageDropFiles,
  extractComposerSessionReferenceDrop,
  hasComposerImageDragPayload,
  hasComposerSessionReferenceDragPayload,
} from "./conversationComposerDropPayload";
import { extractComposerPastedTextOverflow } from "./conversationComposerPastePayload";
import {
  composerAttachmentAcceptAttribute,
  isComposerAttachableFile,
} from "./conversationConstants";
import {
  buildTurnErrorDiagnosticRows,
  buildCurrentTurnErrorRows,
  summarizeCurrentTurnError,
  resolveConversationTurnErrorType,
  resolveConversationTurnErrorRecoveryAction,
  resolveSessionTurnErrorRecoveryAction,
  resolveTurnErrorTypeLabelKey,
} from "./conversationTurnErrorPresentation";
import { buildConversationToolActivityDetailRows } from "./conversationToolActivityDetail";
import { projectedConversationMessageIds } from "./conversationMessageIdentity";
import { shouldApplyComposerFocusRequest } from "./conversationComposerFocus";
import { scheduleComposerFocusAttempts } from "./conversationComposerFocusSchedule";
import {
  resolveMessageTurnAvatar,
  userAvatarSymbol,
  type TurnAvatarResolution,
} from "./conversationTurnAvatar";
import type {
  ConversationForkScope,
  ConversationViewProps,
} from "./conversationViewTypes";
import { AgentPermissionPresetControl } from "../vui/product/agent-management";
import { compactConversationPreview } from "./conversationOperationPresentation";
import {
  resolveComposerActionDisabled,
  resolveComposerActionLabels,
  resolveComposerActionMode,
  resolveComposerEditMode,
  resolveComposerEnterDelivery,
  resolveComposerGuidanceUi,
  resolveComposerPrimaryActionFlags,
  shouldStopComposerOnEscape,
} from "./conversationComposerActionModel";
import { getCachedResponseSegments as getCachedResponseSegmentsFromCache } from "./conversationResponseSegmentCache";
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
import { useConversationFind } from "./useConversationFind";
import { VButton, VNativeInput, VNativeTextarea } from "../vui";
import styles from "./ConversationView.styles";


// How long the "long paste became an attachment" status row stays visible.
const COMPOSER_PASTE_NOTICE_VISIBLE_MS = 8000;

const DEFAULT_EXPANDED_RESPONSE_TAIL_COUNT = 3;
const RESPONSE_PARSE_CACHE_LIMIT = 80;
const RESPONSE_PREWARM_MESSAGE_LIMIT = 8;
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
// Prepend anchor correction: bounded frames for measurements to land before
// the viewport position is declared final (2px tolerance = subpixel jitter).
const TIMELINE_ANCHOR_CORRECTION_MAX_FRAMES = 30;
const TIMELINE_ANCHOR_CORRECTION_TOLERANCE_PX = 2;

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

/** Turn navigator label source: the user's prompt, else the assistant answer. */
function turnNavPreviewText(message: ConversationMessage | undefined): string {
  if (!message) {
    return "";
  }
  if (message.role === "user") {
    return String((message as { content?: string }).content ?? "");
  }
  return assistantFinalAnswerText(message);
}

/**
 * Markdown-free single-line preview for the turn rail hover cards: same
 * extraction as the nav label, then fences/images/links/emphasis/headings
 * reduced to plain words so the card never shows raw markdown punctuation.
 */
function turnNavPlainPreviewText(message: ConversationMessage | undefined): string {
  const raw = turnNavPreviewText(message);
  if (!raw) {
    return "";
  }
  return raw
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/^\s{0,3}#{1,6}\s+/gm, "")
    .replace(/^\s{0,3}>\s?/gm, "")
    .replace(/\*\*|__|~~|`/g, "")
    .replace(/\s+/g, " ")
    .trim();
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
  // /api/config/public summary (modelLabels id→label map) instead of the full
  // /api/config/workspace payload: this mount only needs labels, and the heavy
  // workspace endpoint landed in every boot volley. Shares the configPublic
  // cache key with the shell-wide summary consumers; absence of data degrades
  // to the raw model id.
  const configSummaryQuery = useQuery({
    queryKey: queryKeys.configPublic(),
    queryFn: ({ signal }) => fetchPublicConfig({ signal }),
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
  // Prompt history browse state (ArrowUp/Down on an empty draft). Refs instead
  // of state so the keydown closure never reads a stale index or stash.
  const promptHistoryIndexRef = useRef<number | null>(null);
  const promptHistoryDraftRef = useRef<string | null>(null);
  const inlineEditInputRef = useRef<HTMLTextAreaElement | null>(null);
  const attachmentInputRef = useRef<HTMLInputElement | null>(null);
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
  const autoScrollToLatestRef = useRef(autoScrollToLatest);
  autoScrollToLatestRef.current = autoScrollToLatest;
  const lastComposerFocusSignalRef = useRef("");
  const lastComposerRestoreSignalRef = useRef("");
  const composerDisabledRef = useRef(composerDisabled);
  composerDisabledRef.current = composerDisabled;
  const defaultExpansionRef = useRef<Record<string, Record<string, boolean>>>({});
  const responseSegmentCacheRef = useRef<Map<string, ResponseSegment[]>>(new Map());
  const [sectionExpansion, setSectionExpansion] = useState<Record<string, Record<string, boolean>>>({});
  const [isAtBottom, setIsAtBottom] = useState(true);
  const [previewImage, setPreviewImage] = useState<ConversationImagePreviewRequest | null>(null);
  const [composerDragActive, setComposerDragActive] = useState(false);
  const streamingPaintMetricsRef = useRef({ streamingMessageCount: 0, renderedTextLength: 0 });
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
    enabled: Boolean(sessionId) && !companionMode,
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
  /** Branch fork exit: dialog target message + copy scope (route executes the API call). */
  const [forkDialogMessage, setForkDialogMessage] = useState<ConversationMessage | null>(null);
  const [forkScope, setForkScope] = useState<ConversationForkScope>("visible_path");
  const [forkPending, setForkPending] = useState(false);
  // Text-selection quote menu (zai-org/ZCode useTextSelection pattern,
  // Apache-2.0): snapshot of the selected text. The menu centers itself on
  // that viewport rect.
  const timelineAreaRef = useRef<HTMLDivElement | null>(null);
  const selectionQuoteDismissedTextRef = useRef<string | null>(null);
  const selectionQuoteTextRef = useRef("");
  const [selectionQuoteMenu, setSelectionQuoteMenu] = useState<{
    text: string;
    rect: ConversationSelectionRect;
    sourceMessageId: string;
  } | null>(null);
  // Selection quote lifecycle: document-level selectionchange + mouseup/keyup,
  // rAF-coalesced. The menu opens only for a non-empty selection fully inside
  // the timeline (never the composer), and closes on collapse, timeline
  // scroll, outside mousedown, or Escape (Escape also arms a dismiss guard so
  // keyup cannot immediately re-open the same selection).
  useEffect(() => {
    let frame: number | null = null;
    const evaluateSelection = () => {
      frame = null;
      const timelineArea = timelineAreaRef.current;
      const snapshot = extractConversationSelectionSnapshot(window.getSelection(), timelineRef.current);
      if (!snapshot || !timelineArea) {
        selectionQuoteDismissedTextRef.current = null;
        selectionQuoteTextRef.current = "";
        setSelectionQuoteMenu(null);
        return;
      }
      selectionQuoteTextRef.current = snapshot.text;
      if (selectionQuoteDismissedTextRef.current !== null) {
        // Escape dismissed this selection; a genuinely different selection
        // (new text) re-arms the menu, the same one stays dismissed.
        if (snapshot.text === selectionQuoteDismissedTextRef.current) {
          return;
        }
        selectionQuoteDismissedTextRef.current = null;
      }
      setSelectionQuoteMenu({
        text: snapshot.text,
        sourceMessageId: snapshot.sourceMessageId,
        rect: snapshot.rect,
      });
    };
    const scheduleEvaluation = () => {
      if (frame !== null) {
        return;
      }
      frame = requestAnimationFrame(evaluateSelection);
    };
    const handleDocumentMouseDown = (event: MouseEvent) => {
      // Mousedown inside the menu belongs to an action click, not a dismissal.
      if (event.target instanceof Element && event.target.closest("[data-conversation-selection-menu]")) {
        return;
      }
      selectionQuoteDismissedTextRef.current = null;
      setSelectionQuoteMenu(null);
    };
    const handleDocumentKeydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        selectionQuoteDismissedTextRef.current = selectionQuoteTextRef.current;
        setSelectionQuoteMenu(null);
      }
    };
    const handleTimelineScroll = () => {
      setSelectionQuoteMenu(null);
    };
    const timeline = timelineRef.current;
    document.addEventListener("selectionchange", scheduleEvaluation);
    document.addEventListener("mouseup", scheduleEvaluation);
    document.addEventListener("keyup", scheduleEvaluation);
    document.addEventListener("keydown", handleDocumentKeydown);
    document.addEventListener("mousedown", handleDocumentMouseDown);
    timeline?.addEventListener("scroll", handleTimelineScroll);
    return () => {
      if (frame !== null) {
        cancelAnimationFrame(frame);
      }
      document.removeEventListener("selectionchange", scheduleEvaluation);
      document.removeEventListener("mouseup", scheduleEvaluation);
      document.removeEventListener("keyup", scheduleEvaluation);
      document.removeEventListener("keydown", handleDocumentKeydown);
      document.removeEventListener("mousedown", handleDocumentMouseDown);
      timeline?.removeEventListener("scroll", handleTimelineScroll);
    };
  }, []);
  const handleSelectionSideChat = useCallback(() => {
    if (!selectionQuoteMenu || !onOpenSideChat) {
      return;
    }
    onOpenSideChat(buildQuotedDraftText("", selectionQuoteMenu.text), false);
    setSelectionQuoteMenu(null);
    selectionQuoteDismissedTextRef.current = null;
    window.getSelection()?.removeAllRanges();
  }, [onOpenSideChat, selectionQuoteMenu]);
  const handleSelectionQuoteToComposer = useCallback(() => {
    if (!selectionQuoteMenu) {
      return;
    }
    onComposerChange(buildQuotedDraftText(composerValue, selectionQuoteMenu.text));
    setSelectionQuoteMenu(null);
    selectionQuoteDismissedTextRef.current = null;
    // Park focus and the caret at the end of the appended quote.
    requestAnimationFrame(() => {
      const input = composerInputRef.current;
      if (!input) {
        return;
      }
      input.focus();
      const end = input.value.length;
      input.setSelectionRange(end, end);
    });
  }, [composerValue, onComposerChange, selectionQuoteMenu]);
  const handleSelectionCopy = useCallback(() => {
    if (!selectionQuoteMenu) {
      return;
    }
    void copyTextToClipboard(selectionQuoteMenu.text);
    setSelectionQuoteMenu(null);
  }, [selectionQuoteMenu]);
  /**
   * Structured quote: attaches the selection as a `message` reference chip
   * (contract: referenceId `message:{sourceMessageId}` + source session/
   * message ids + quote + single-line title). Only offered when the selection
   * anchor lives inside a message row.
   */
  const handleSelectionReferenceToComposer = useCallback(() => {
    if (!selectionQuoteMenu?.sourceMessageId || !onAddComposerReference) {
      return;
    }
    onAddComposerReference(buildMessageReferencePayload({
      sourceSessionId: sessionId,
      sourceMessageId: selectionQuoteMenu.sourceMessageId,
      quote: selectionQuoteMenu.text,
    }));
    setSelectionQuoteMenu(null);
    selectionQuoteDismissedTextRef.current = null;
  }, [onAddComposerReference, selectionQuoteMenu, sessionId]);
  const resolvedActionMode = resolveComposerActionMode(composerActionMode);
  const composerPromptSuggestion = useComposerPromptSuggestion(
    {
      sessionId,
      suggestionEnabled: promptSuggestionEnabled && !composerDisabled && !editingMessageId,
      starterEnabled: !composerDisabled && !editingMessageId,
      busy: resolvedActionMode === "stop" || composerPending,
      draft: composerValue,
      hasConversation: messages.length > 0,
    },
    (suggestion) => {
      onComposerChange(suggestion);
      requestAnimationFrame(() => composerInputRef.current?.focus());
    },
  );
  const fallbackComposerStarters = useMemo<ComposerStarter[]>(() => [
    { heading: t("sessionStarterOrganizeHeading"), command: t("sessionStarterOrganizeCommand") },
    { heading: t("sessionStarterResearchHeading"), command: t("sessionStarterResearchCommand") },
    { heading: t("sessionStarterDraftHeading"), command: t("sessionStarterDraftCommand") },
  ], [t]);
  // Backend starters win; without them the dictionary keeps generic research
  // starters so the empty session still offers a clickable first step.
  const composerStarters = composerPromptSuggestion.starters.length > 0
    ? composerPromptSuggestion.starters.slice(0, MAX_COMPOSER_STARTERS)
    : fallbackComposerStarters;
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
  const {
    guidanceActionDisabled,
    showQueuePrimary,
    queuePrimaryIsImmediate,
  } = resolveComposerGuidanceUi({
    runningGuidanceActionsEnabled,
    composerValue,
    composerDisabled,
    safeGuidancePending: composerSafeGuidancePending,
    interruptGuidancePending: composerInterruptGuidancePending,
    queueCount: followupQueue.length,
  });
  const queuePrimaryKind = resolveComposerQueuePrimaryKind({
    sessionBusy: runningGuidanceActionsEnabled,
    draft: composerValue,
    queueCount: followupQueue.length,
  });
  const primaryActionIsQueueSubmit = runningGuidanceActionsEnabled && showQueuePrimary;
  const resolvedQueueFollowupLabel = t("queueFollowup");
  const resolvedImmediateSteerLabel = t("immediateSteer");
  const resolvedSafeGuidanceLabel = safeGuidanceLabel ?? t("safeGuidance");
  const resolvedSafeGuidancePendingLabel = safeGuidancePendingLabel ?? t("safeGuidancePending");
  const resolvedBusyPrimaryLabel = queuePrimaryIsImmediate
    ? resolvedImmediateSteerLabel
    : resolvedQueueFollowupLabel;
  // Tooltip carries the keyboard contract: running Enter delivers immediately
  // (or queues the draft when guidance cannot carry it); the button itself
  // stays the explicit queue entry.
  const resolvedBusyPrimaryHint = queuePrimaryIsImmediate
    ? t("composerSteerEnterHint")
    : t("composerQueueSteerEnterHint");
  const baseComposerPlaceholder = composerPlaceholder.trim()
    ? composerPlaceholder
    : resolvedActionMode === "stop"
      ? (followupQueue.length ? t("sessionBusyQueuedPlaceholder") : t("sessionBusyPlaceholder"))
      : composerPlaceholder;
  const resolvedComposerPlaceholder = resolveComposerPlaceholder({
    ghost: composerPromptSuggestion.ghost,
    exampleCommand: composerPromptSuggestion.exampleCommand,
    hasConversation: messages.length > 0,
    lang,
    fallback: baseComposerPlaceholder,
  });
  // Edit/rerun and running-turn queue/steer are labeled primary pills. Do not mix in
  // round icon-only geometry (composerRoundButtonPrimary forces a square slot).
  const primaryActionClassName = primaryActionIsEditSubmit || primaryActionIsQueueSubmit
    ? styles.composerEditSubmitButton
    : `${styles.sendButton} ${styles.composerRoundButton} ${styles.composerRoundButtonPrimary}`;
  const composerCanAcceptImageDrop = Boolean(onAddComposerAttachments) && !attachmentInputDisabled;
  const composerCanAcceptReferenceDrop = Boolean(onAddComposerReference) && !composerDisabled;
  // Recomputed per render on purpose: `t` is not a stable identity and the list
  // is tiny; keyboard state is keyed on composerValue, not on these arrays.
  const builtinSlashCommands: BuiltinSlashCommand[] = [];
  if (onCreateSession) {
    builtinSlashCommands.push({
      id: "new_session",
      command: t("slashBuiltinNewSessionCommand"),
      aliases: String(t("slashBuiltinNewSessionAliases")).split(/\s+/).filter(Boolean),
      description: t("slashBuiltinNewSessionDescription"),
    });
  }
  if (onOpenAgentModelConfig) {
    builtinSlashCommands.push({
      id: "model",
      command: t("slashBuiltinModelCommand"),
      aliases: String(t("slashBuiltinModelAliases")).split(/\s+/).filter(Boolean),
      description: t("slashBuiltinModelDescription"),
    });
  }
  if (onOpenComposerContextDetail) {
    builtinSlashCommands.push({
      id: "compress_context",
      command: t("slashBuiltinCompressCommand"),
      aliases: String(t("slashBuiltinCompressAliases")).split(/\s+/).filter(Boolean),
      description: t("slashBuiltinCompressDescription"),
    });
  }
  if (onOpenSideChat) {
    builtinSlashCommands.push({
      id: "side",
      command: t("slashBuiltinSideCommand"),
      aliases: String(t("slashBuiltinSideAliases")).split(/\s+/).filter(Boolean),
      description: t("slashBuiltinSideDescription"),
    });
  }
  const slashSuggestions = mergeSlashCommandSuggestions(
    builtinSlashCommands,
    slashCommandSuggestions,
    composerValue,
  );
  // Escape dismisses the list for the exact draft that produced it; any edit
  // (including the builtin clearing the draft) re-arms suggestions.
  const [slashDismissedAtValue, setSlashDismissedAtValue] = useState<string | null>(null);
  const [slashActiveIndex, setSlashActiveIndex] = useState(-1);
  useEffect(() => {
    setSlashActiveIndex(-1);
    setReferenceActiveIndex(-1);
  }, [composerValue]);
  const showSlashSuggestions = !composerDisabled
    && slashDismissedAtValue !== composerValue
    && (slashSuggestions.length > 0
      // ZCode panel parity: a still-loading or failed skill catalog must not
      // read as silence — the panel opens to say so instead of staying shut.
      || (shouldShowSlashCommandSuggestions(composerValue) && slashSkillsCatalogState !== "ready"));
  const activeSlashIndex = showSlashSuggestions
    ? (slashActiveIndex >= 0 && slashActiveIndex < slashSuggestions.length ? slashActiveIndex : 0)
    : -1;
  const slashSuggestionListId = `conversation-${sessionId}-slash-suggestions`;
  // "@" reference type-ahead: caret-aware token detection over the same draft.
  // The composer never inserts reference markup; selecting a candidate registers
  // the same structured reference chip as the plus-menu picker and removes the
  // "@fragment" from the draft.
  const [composerReferenceCaret, setComposerReferenceCaret] = useState(0);
  const [composerComposing, setComposerComposing] = useState(false);
  // Oversized plain-text pastes convert into a document attachment; this status
  // row is the light notice (auto-dismisses, never steals focus from the draft).
  const [composerPasteNotice, setComposerPasteNotice] = useState("");
  const [referenceDismissedAtValue, setReferenceDismissedAtValue] = useState<string | null>(null);
  const [referenceActiveIndex, setReferenceActiveIndex] = useState(-1);
  const activeReferenceToken: ReferenceTypeaheadToken | null = useMemo(
    () => (
      composerComposing || composerDisabled || editingMessageId || !onAddComposerReference
        ? null
        : detectReferenceToken(composerValue, composerReferenceCaret)
    ),
    [composerComposing, composerDisabled, composerReferenceCaret, composerValue, editingMessageId, onAddComposerReference],
  );
  const referenceSuggestions = useMemo(
    () => (activeReferenceToken
      ? filterReferenceTypeaheadOptions(composerReferenceOptions, activeReferenceToken.query)
      : []),
    [activeReferenceToken, composerReferenceOptions],
  );
  const showReferenceSuggestions = !composerDisabled
    && composerReferenceOptions.length > 0
    && referenceDismissedAtValue !== composerValue
    && referenceSuggestions.length > 0;
  const activeReferenceIndex = showReferenceSuggestions
    ? (referenceActiveIndex >= 0 && referenceActiveIndex < referenceSuggestions.length ? referenceActiveIndex : 0)
    : -1;
  const referenceSuggestionListId = `conversation-${sessionId}-reference-suggestions`;
  useEffect(() => {
    if (!composerPasteNotice) {
      return;
    }
    const timer = window.setTimeout(
      () => setComposerPasteNotice(""),
      COMPOSER_PASTE_NOTICE_VISIBLE_MS,
    );
    return () => window.clearTimeout(timer);
  }, [composerPasteNotice]);
  function syncComposerReferenceCaret(element: HTMLTextAreaElement | null) {
    setComposerReferenceCaret(element ? element.selectionStart ?? element.value.length : 0);
  }
  function handleReferenceTypeaheadSelect(option: ReferenceTypeaheadOption) {
    if (!activeReferenceToken) {
      return;
    }
    const token = activeReferenceToken;
    // Same structured-reference path as the plus-menu knowledge/file picker.
    onAddComposerReference?.(option.reference);
    const removed = removeReferenceToken(composerValue, token);
    onComposerChange(removed.text);
    setReferenceActiveIndex(-1);
    setReferenceDismissedAtValue(null);
    requestAnimationFrame(() => {
      const input = composerInputRef.current;
      if (!input) {
        return;
      }
      input.focus();
      input.setSelectionRange(removed.caretIndex, removed.caretIndex);
      setComposerReferenceCaret(removed.caretIndex);
    });
  }
  function handleReferenceTypeaheadDismiss() {
    setReferenceDismissedAtValue(composerValue);
    setReferenceActiveIndex(-1);
  }
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

  function handleSlashCommandSuggestion(suggestion: SlashCommandSuggestion) {
    if (suggestion.builtin) {
      // Builtin commands execute immediately: clear the draft so the listbox
      // gate (no leading slash token) closes it, then run the action.
      onComposerChange("");
      setSlashDismissedAtValue("");
      setSlashActiveIndex(-1);
      executeBuiltinSlashCommand(suggestion.builtinId);
      return;
    }
    if (suggestion.skill) {
      onComposerChange(insertSlashCommandSuggestion(composerValue, suggestion.skill.command));
      requestAnimationFrame(() => composerInputRef.current?.focus());
    }
  }

  function executeBuiltinSlashCommand(builtinId?: BuiltinSlashCommandId) {
    switch (builtinId) {
      case "new_session":
        onCreateSession?.();
        break;
      case "model":
        onOpenAgentModelConfig?.();
        break;
      case "compress_context":
        onOpenComposerContextDetail?.();
        break;
      case "side":
        onOpenSideChat?.("", false);
        break;
    }
  }

  function handleSlashCommandDismiss() {
    setSlashDismissedAtValue(composerValue);
    setSlashActiveIndex(-1);
  }

  function handleStarterCardActivate(starter: ComposerStarter) {
    // Fill the composer for editing; the starter is never auto-submitted.
    onComposerChange(starter.command);
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
    let index = activeTimelineMessages.length;
    while (index > 0) {
      const message = activeTimelineMessages[index - 1];
      if (!assistantTurnIsStreaming(message) && !assistantTurnIsInFlight(message)) {
        break;
      }
      index -= 1;
    }
    return index;
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
  // Turn navigation directory (minimap rail): one entry per conversation
  // turn, derived from the same row identities the virtualizer keys on. The
  // markdown-free preview map feeds the rail's VHoverCard content through the
  // entries' userPreviewText / assistantPreviewText fields.
  const timelineTurnNavPreviewTextByRowKey = useMemo(() => {
    const previewTextByRowKey = new Map<string, string>();
    activeTimelineRowIdentities.forEach((identity, index) => {
      const previewText = turnNavPlainPreviewText(activeTimelineMessages[index]);
      if (previewText) {
        previewTextByRowKey.set(identity.rowKey, previewText);
      }
    });
    return previewTextByRowKey;
  }, [activeTimelineRowIdentities, activeTimelineMessages]);
  const timelineTurnNavEntries = useMemo(
    () => buildConversationTurnNavDirectory(
      activeTimelineRowIdentities.map((identity, index) => ({
        rowKey: identity.rowKey,
        previewText: turnNavPreviewText(activeTimelineMessages[index]),
      })),
      {
        fallbackLabel: lang === "zh"
          ? (turnNumber: number) => `第 ${turnNumber} 轮`
          : (turnNumber: number) => `Turn ${turnNumber}`,
        previewTextByRowKey: timelineTurnNavPreviewTextByRowKey,
      },
    ),
    [activeTimelineRowIdentities, activeTimelineMessages, lang, timelineTurnNavPreviewTextByRowKey],
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
  // Minimap current-turn highlight: rebuilt every render like the row plan so
  // scroll notifications stay live (virtual history + static live tail).
  const timelineTurnNavCurrentIndex = resolveConversationTurnNavCurrentIndex({
    entries: timelineTurnNavEntries,
    historyRowCount: timelineLiveTailStartIndex,
    historyTotalSize: timelineVirtualizer.getTotalSize(),
    scrollOffset: timelineVirtualizer.scrollOffset ?? 0,
    viewportHeight: timelineVirtualizer.scrollRect?.height ?? 0,
    rowIndexAtOffset: (offset) => {
      const item = timelineVirtualizer.getVirtualItemForOffset(offset);
      return item ? item.index : null;
    },
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

  function closeImagePreview() {
    setPreviewImage(null);
  }

  function rememberUserScrollIntent(intent: TimelineUserScrollIntent) {
    if (intent === "none") {
      return;
    }
    if (historyAnchorCorrectingRef.current?.geometryReflow) {
      historyAnchorCorrectingRef.current = null;
      historyScrollAnchorRef.current = null;
      readingViewportAnchorRef.current = null;
    }
    userScrollIntentRef.current = intent;
    userScrollIntentAtRef.current = performance.now();
  }

  function currentUserScrollIntent() {
    return freshTimelineUserScrollIntent(
      userScrollIntentRef.current,
      userScrollIntentAtRef.current,
      performance.now(),
    );
  }

  function contentWidthIsChanging() {
    return performance.now() < contentWidthChangingUntilRef.current;
  }

  function noteTimelineContentWidth(width: number) {
    if (!Number.isFinite(width) || width <= 0) {
      return;
    }
    const previous = lastTimelineContentWidthRef.current;
    if (previous > 0 && width !== previous) {
      contentWidthChangingUntilRef.current = performance.now() + TIMELINE_CONTENT_WIDTH_RESIZE_SETTLE_MS;
    }
    lastTimelineContentWidthRef.current = width;
  }

  function reconcileFollowBeforeStick(timeline: HTMLDivElement) {
    const next = reconcileFollowingBeforeContentStick({
      following: followLatestRef.current,
      isAtBottom: isTimelineNearBottom({
        scrollHeight: timeline.scrollHeight,
        clientHeight: timeline.clientHeight,
        scrollTop: timeline.scrollTop,
      }),
      userScrollIntent: currentUserScrollIntent(),
      scrollTop: timeline.scrollTop,
      lastObservedScrollTop: lastTimelineScrollTopRef.current,
    });
    followLatestRef.current = next;
    return next;
  }

  function scrollTimelineToBottom(
    timeline: HTMLDivElement,
    options: { followLatest?: boolean; behavior?: ScrollBehavior } = {},
  ) {
    if (options.followLatest) {
      readingViewportAnchorRef.current = null;
      rememberUserScrollIntent("towardBottom");
    }
    const wasAtBottom = atBottomRef.current;
    ignoreNextProgrammaticFollowRef.current = true;
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
    const timeline = timelineRef.current;
    if (contentWidthIsChanging()) {
      return;
    }
    if (timeline && !reconcileFollowBeforeStick(timeline)) {
      return;
    }
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
    userScrollIntentRef.current = "none";
    userScrollIntentAtRef.current = 0;
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

  function exitComposerPromptHistoryBrowse() {
    promptHistoryIndexRef.current = null;
    promptHistoryDraftRef.current = null;
  }

  /**
   * ZCode parity: ArrowUp/ArrowDown on an empty draft (or while already
   * browsing) recall recently sent prompts. Runs after find-bar/slash/ghost/
   * typeahead/IME claims, so it never steals their arrow navigation, and it
   * leaves multi-line caret movement alone for a non-empty draft.
   */
  function handleComposerPromptHistoryNavigation(
    event: React.KeyboardEvent<HTMLTextAreaElement>,
  ): boolean {
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") {
      return false;
    }
    if (event.nativeEvent.isComposing || composerComposing) {
      return false;
    }
    if (event.shiftKey || event.ctrlKey || event.metaKey || event.altKey) {
      return false;
    }
    // History navigation only takes over from an empty draft or while
    // already browsing; a non-empty draft keeps native caret movement.
    if (promptHistoryIndexRef.current === null && composerValue.length > 0) {
      return false;
    }
    const result = navigatePromptHistory(
      readPromptHistory(),
      promptHistoryIndexRef.current,
      event.key === "ArrowUp" ? "up" : "down",
    );
    if (!result.shouldHandle) {
      return false;
    }
    event.preventDefault();
    if (result.nextIndex === null) {
      // Past the newest entry: hand the composer back to the stashed draft.
      const stashedDraft = promptHistoryDraftRef.current ?? "";
      exitComposerPromptHistoryBrowse();
      onComposerChange(stashedDraft);
      return true;
    }
    if (promptHistoryIndexRef.current === null) {
      // Entering browse mode: stash the (empty) draft for later restore.
      promptHistoryDraftRef.current = composerValue;
    }
    promptHistoryIndexRef.current = result.nextIndex;
    onComposerChange(result.nextValue);
    return true;
  }

  function handleSideChatCommand(): boolean {
    const sideCommand = onOpenSideChat ? parseSideSlashCommand(composerValue) : null;
    if (sideCommand) {
      onComposerChange("");
      onOpenSideChat?.(sideCommand.prompt, Boolean(sideCommand.prompt));
      return true;
    }
    return false;
  }

  function handleQueueSubmit() {
    if (!handleSideChatCommand()) {
      onSubmit();
    }
  }

  function handleSendAndFollowLatest() {
    if (handleSideChatCommand()) {
      return;
    }
    exitComposerPromptHistoryBrowse();
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
      noteTimelineContentWidth(timeline.clientWidth);
      if (shouldStickTimelineToBottomOnContentResize({
        autoScrollToLatest: autoScrollToLatestRef.current,
        followingLatest: followLatestRef.current,
        contentWidthChanging: contentWidthIsChanging(),
      })) {
        scheduleTimelineScrollToBottom();
      }
    });
    observer.observe(timeline);
    const content = timelineContentRef.current;
    if (content) {
      observer.observe(content);
    }
    return () => observer.disconnect();
  }, [sessionId, activeTimelineMessages.length > 0]);


  useEffect(() => () => {
    if (copyAnswerFeedbackTimerRef.current !== null) {
      window.clearTimeout(copyAnswerFeedbackTimerRef.current);
    }
  }, []);

  useLayoutEffect(() => {
    const pending = historyAnchorCorrectingRef.current;
    if (!pending || !pending.anchor) {
      return;
    }
    const timeline = timelineRef.current;
    if (!timeline) {
      return;
    }
    if (!pending.geometryReflow && activeTimelineMessages.length === pending.startLength) {
      // Capture done, prepend not committed yet: keep the anchor pending.
      return;
    }
    if (!pending.fallbackDone) {
      // First pass after the prepend: exact row-key restore when the anchor
      // row is mounted, scrollHeight-delta fallback otherwise (the fallback
      // drifts by the estimate error of all prepended rows; the correction
      // frames below eliminate that residual).
      pending.fallbackDone = true;
      if (restoreTimelineRowKeyAnchor(timeline, pending.anchor)) {
        atBottomRef.current = false;
        followLatestRef.current = false;
        lastTimelineScrollTopRef.current = timeline.scrollTop;
        setIsAtBottom(false);
      }
      return;
    }
    // Correction frames: re-run until the anchor row is mounted at its captured
    // viewport offset. Measurements streaming in after the prepend keep
    // re-rendering this effect, so the residual estimate error converges to
    // zero within a couple of frames instead of shipping a visible jump.
    const rootTop = timeline.getBoundingClientRect().top;
    let anchorRow: Element | null = null;
    for (const row of timeline.querySelectorAll("[data-conversation-row-key]")) {
      if (row.getAttribute("data-conversation-row-key") === pending.anchor.rowKey) {
        anchorRow = row;
        break;
      }
    }
    if (!anchorRow) {
      pending.attempts += 1;
      if (pending.attempts > TIMELINE_ANCHOR_CORRECTION_MAX_FRAMES) {
        historyAnchorCorrectingRef.current = null;
        historyScrollAnchorRef.current = null;
      }
      return;
    }
    const drift = anchorRow.getBoundingClientRect().top - rootTop - pending.anchor.offsetTop;
    if (Math.abs(drift) <= TIMELINE_ANCHOR_CORRECTION_TOLERANCE_PX) {
      historyAnchorCorrectingRef.current = null;
      historyScrollAnchorRef.current = null;
      return;
    }
    timeline.scrollTop += drift;
    lastTimelineScrollTopRef.current = timeline.scrollTop;
  });

  useLayoutEffect(() => {
    // Breakpoint changes alter virtual row offsets as well as text wrapping.
    // Keep a following reader at the tail after react-virtual's next measure.
    const timeline = timelineRef.current;
    if (!timeline) return undefined;
    const anchor = historyAnchorCorrectingRef.current?.geometryReflow
      ? historyAnchorCorrectingRef.current.anchor : readingViewportAnchorRef.current;
    // CSS can temporarily clamp scrollTop to the bottom before the media
    // callback runs. A remembered reading anchor takes precedence over that.
    const following = !anchor && followLatestRef.current;
    if (anchor) followLatestRef.current = false;
    if (!following && !anchor) return undefined;
    const intentAtStart = userScrollIntentAtRef.current;
    let frame = 0;
    let remainingFrames = TIMELINE_ANCHOR_CORRECTION_MAX_FRAMES;
    const restoreViewport = () => {
      const current = timelineRef.current;
      if (!current || userScrollIntentAtRef.current > intentAtStart) return;
      if (following && followLatestRef.current) {
        scrollTimelineToBottom(current);
      } else if (anchor) {
        // Browser/virtualizer clamps may briefly report "at bottom" while
        // remeasuring. Preserve the pre-resize reading intent through them.
        followLatestRef.current = false;
        atBottomRef.current = false;
        setIsAtBottom(false);
        restoreTimelineRowKeyAnchor(current, anchor);
        lastTimelineScrollTopRef.current = current.scrollTop;
      }
      // react-virtual measures rows in rAF; retain the target through those
      // measurements rather than clearing it after the first matching paint.
      if (remainingFrames-- > 0) frame = window.requestAnimationFrame(restoreViewport);
      else if (!followLatestRef.current) readingViewportAnchorRef.current = captureTimelineRowKeyAnchor(current);
    };
    restoreViewport();
    return () => window.cancelAnimationFrame(frame);
  }, [narrowTimelineViewport, sessionId]);

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
    const userScrollIntent = currentUserScrollIntent();
    if (userScrollIntent === "awayFromBottom") {
      followLatestRef.current = false;
    } else if (
      !followLatestRef.current
      && isTimelineNearBottom({
        scrollHeight: timeline.scrollHeight,
        clientHeight: timeline.clientHeight,
        scrollTop: timeline.scrollTop,
      })
    ) {
      // Content growth while still near the bottom re-enables follow even if a prior
      // expand briefly suspended it. An upward wheel recorded before this commit wins.
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
      return undefined;
    }
    const wheelTargetConsumesScroll = (target: EventTarget | null, deltaY: number) => {
      if (!(target instanceof HTMLElement) || target === timeline) {
        return false;
      }
      let node: HTMLElement | null = target;
      while (node && node !== timeline) {
        if (
          node instanceof HTMLInputElement
          || node instanceof HTMLTextAreaElement
          || node.isContentEditable
        ) {
          return true;
        }
        const overflowY = window.getComputedStyle(node).overflowY;
        if (
          (overflowY === "auto" || overflowY === "scroll")
          && node.scrollHeight > node.clientHeight + 1
        ) {
          if (deltaY < 0 && node.scrollTop > 0) {
            return true;
          }
          if (deltaY > 0 && node.scrollTop + node.clientHeight < node.scrollHeight - 1) {
            return true;
          }
        }
        node = node.parentElement;
      }
      return false;
    };
    const onWheel = (event: WheelEvent) => {
      if (wheelTargetConsumesScroll(event.target, event.deltaY)) {
        return;
      }
      rememberUserScrollIntent(timelineWheelScrollIntent(event.deltaY));
    };
    let lastTouchY = 0;
    const onTouchStart = (event: TouchEvent) => {
      lastTouchY = event.touches[0]?.clientY ?? lastTouchY;
    };
    const onTouchMove = (event: TouchEvent) => {
      const nextY = event.touches[0]?.clientY ?? lastTouchY;
      rememberUserScrollIntent(timelineTouchScrollIntent(lastTouchY, nextY));
      lastTouchY = nextY;
    };
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target;
      const editableTarget = target instanceof HTMLElement && (
        target.isContentEditable
        || target.tagName === "INPUT"
        || target.tagName === "TEXTAREA"
      );
      rememberUserScrollIntent(timelineKeyboardScrollIntent({
        key: event.key,
        shiftKey: event.shiftKey,
        editableTarget,
      }));
    };
    timeline.addEventListener("wheel", onWheel, { passive: true });
    timeline.addEventListener("touchstart", onTouchStart, { passive: true });
    timeline.addEventListener("touchmove", onTouchMove, { passive: true });
    window.addEventListener("keydown", onKeyDown);
    return () => {
      timeline.removeEventListener("wheel", onWheel);
      timeline.removeEventListener("touchstart", onTouchStart);
      timeline.removeEventListener("touchmove", onTouchMove);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [sessionId]);

  useEffect(() => {
    const timeline = timelineRef.current;
    if (!timeline) {
      return;
    }
    const handleScroll = (consumeProgrammatic = true) => {
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
      const programmaticFollow = consumeProgrammatic && ignoreNextProgrammaticFollowRef.current;
      if (consumeProgrammatic) {
        ignoreNextProgrammaticFollowRef.current = false;
      }
      const scrollSource: TimelineScrollSource = programmaticFollow ? "programmatic" : "user";
      const nextState = resolveTimelineFollowState({
        scrollHeight: timeline.scrollHeight,
        clientHeight: timeline.clientHeight,
        scrollTop: timeline.scrollTop,
        previousScrollTop,
        wasFollowingLatest: followLatestRef.current,
        scrollSource,
        userScrollIntent: currentUserScrollIntent(),
      });
      lastTimelineScrollTopRef.current = timeline.scrollTop;
      atBottomRef.current = nextState.isAtBottom;
      followLatestRef.current = nextState.shouldFollowLatest;
      setIsAtBottom(nextState.isAtBottom);
      if (!nextState.shouldFollowLatest && !historyAnchorCorrectingRef.current?.geometryReflow) {
        readingViewportAnchorRef.current = captureTimelineRowKeyAnchor(timeline);
      } else if (nextState.shouldFollowLatest && currentUserScrollIntent() === "towardBottom") {
        readingViewportAnchorRef.current = null;
      }
      rememberSessionTimelineScroll(sessionId, {
        scrollTop: timeline.scrollTop,
        followingLatest: nextState.shouldFollowLatest,
      });
    };
    const onTimelineScroll = () => handleScroll(true);
    handleScroll(false);
    timeline.addEventListener("scroll", onTimelineScroll);
    return () => {
      timeline.removeEventListener("scroll", onTimelineScroll);
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
    if (!focusSignal) {
      // Reset so re-editing the same message after a cancel refocuses.
      lastComposerFocusSignalRef.current = "";
      return;
    }
    if (focusSignal === lastComposerFocusSignalRef.current || composerDisabled) {
      return;
    }
    lastComposerFocusSignalRef.current = focusSignal;
    // Inline edit lives in the timeline row, not the composer; the row editor
    // mounts in this same commit, so focus it on the next frame.
    const raf = window.requestAnimationFrame(() => {
      const input = inlineEditInputRef.current;
      if (!input) {
        return;
      }
      input.focus();
      const cursorPosition = input.value.length;
      input.setSelectionRange(cursorPosition, cursorPosition);
    });
    return () => window.cancelAnimationFrame(raf);
  }, [composerDisabled, editingMessageId]);

  useEffect(() => {
    const focusSignal = String(composerFocusSignal || "").trim();
    if (!focusSignal) {
      return;
    }
    if (!shouldApplyComposerFocusRequest({
      composerDisabled,
      focusSignal,
      hasCompetingFocus: false,
      lastAppliedFocusSignal: lastComposerRestoreSignalRef.current,
    })) {
      return;
    }

    const settleFocusRequest = () => {
      lastComposerRestoreSignalRef.current = focusSignal;
      onComposerFocusRequestSettled?.(focusSignal);
    };

    return scheduleComposerFocusAttempts({
      getInput: () => composerInputRef.current,
      isDisabled: () => composerDisabledRef.current,
      shouldAbort: () => false,
      onSuccess: settleFocusRequest,
      onGiveUp: settleFocusRequest,
    });
  }, [composerDisabled, composerFocusSignal, onComposerFocusRequestSettled]);

  useEffect(() => {
    readingViewportAnchorRef.current = null;
    historyScrollAnchorRef.current = null;
    historyAnchorCorrectingRef.current = null;
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
            && !assistantTurnIsStreaming(message)
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
        getCachedResponseSegments(assistantFinalAnswerText(message));
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

  function scrollToBottom() {
    const timeline = timelineRef.current;
    if (!timeline) {
      return;
    }
    scrollTimelineToBottom(timeline, { followLatest: true, behavior: "smooth" });
  }

  /**
   * Minimap jump: virtualized history rows go through the virtualizer's
   * scrollToIndex; the live tail (last entry) just pins to the bottom.
   * Reduced motion falls back to instant jumps.
   */
  function handleTurnNavigate(entry: ConversationTurnNavEntry) {
    const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    const behavior: ScrollBehavior = reducedMotion ? "auto" : "smooth";
    if (entry.anchorRowIndex < timelineLiveTailStartIndex) {
      timelineVirtualizer.scrollToIndex(entry.anchorRowIndex, { behavior, align: "start" });
      return;
    }
    const timeline = timelineRef.current;
    if (timeline) {
      scrollTimelineToBottom(timeline, { followLatest: false, behavior });
    }
  }

  function revealEarlierTimelineMessages() {
    const preferServerEarlier = shouldPreferServerEarlierLoad({
      visibleMessageCount,
      displayMessageCount: displayMessages.length,
      hasEarlierMessages: Boolean(hasEarlierMessages),
      earlierMessagesLoading: Boolean(earlierMessagesLoading),
    });
    if (!preferServerEarlier || !onLoadEarlierMessages) {
      // U5 with full-history virtualization: every local message is already
      // rendered (visibleMessageCount === displayMessages.length), so there is
      // no client window left to expand — earlier history is server pages only.
      return;
    }
    preserveCurrentExpansionDefaults();
    historyScrollAnchorRef.current = captureTimelineRowKeyAnchor(timelineRef.current);
    historyAnchorCorrectingRef.current = historyScrollAnchorRef.current
      ? {
        anchor: historyScrollAnchorRef.current,
        startLength: activeTimelineMessages.length,
        attempts: 0,
        fallbackDone: false,
      }
      : null;
    atBottomRef.current = false;
    followLatestRef.current = false;
    setIsAtBottom(false);
    onLoadEarlierMessages();
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
    setForkScope,
    setForkDialogMessage,
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

  // Shared so the queue bar stays visible while an inline edit hides the
  // composer field (one edit UI lives in the row, the queue is session status).
  const composerFollowupQueueBar = followupQueue.length ? (
    <ConversationFollowupQueueBar
      items={followupQueue}
      lang={lang}
      variant={composerVariant}
      editLabel={t("editFollowupQueue")}
      withdrawLabel={t("withdrawFollowupQueue")}
      steerLabel={followupQueueSteerLabel ?? t("immediateSteer")}
      saveEditLabel={t("saveFollowupQueueEdit")}
      cancelEditLabel={t("cancelFollowupQueueEdit")}
      dragHandleLabel={t("dragFollowupQueue")}
      sendNowLabel={t("sendFollowupQueueNow")}
      sendNowPendingLabel={t("sendFollowupQueueNowPending")}
      turnRunning={runningGuidanceActionsEnabled}
      onUpdate={onFollowupQueueUpdate ?? (() => undefined)}
      onRemove={onFollowupQueueRemove ?? (() => undefined)}
      onMove={onFollowupQueueMove ?? (() => undefined)}
      onSteer={onFollowupQueueSteer}
      onSendNow={onFollowupQueueSendNow}
    />
  ) : null;

  const composerActions = (
    <div className={styles.composerActionStack}>
      {resolvedActionMode === "stop" && composerPending ? (
        <span
          className={styles.composerStopPendingFeedback}
          role="status"
          aria-live="polite"
          data-testid="composer-stop-pending-feedback"
        >
          {resolvedPendingLabel}
        </span>
      ) : null}
      {!runningGuidanceActionsEnabled || showQueuePrimary ? (
        <VButton
          className={primaryActionClassName}
          isIconOnly={!primaryActionIsEditSubmit && !primaryActionIsQueueSubmit}
          isDisabled={runningGuidanceActionsEnabled ? guidanceActionDisabled : resolvedActionDisabled}
          type="button"
          onClick={runningGuidanceActionsEnabled ? handleQueueSubmit : handlePrimaryAction}
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
                ? resolvedSafeGuidancePendingLabel
                : resolvedBusyPrimaryHint
              : composerPending
                ? resolvedPendingLabel
                : primaryActionIsEditSubmit
                  ? resolvedActionLabel
                  : t("composerSendEnterHint")
          }
          aria-label={
            runningGuidanceActionsEnabled
              ? composerSafeGuidancePending
                ? resolvedSafeGuidancePendingLabel
                : resolvedBusyPrimaryLabel
              : composerPending
                ? resolvedPendingLabel
                : resolvedActionLabel
          }
        >
          {primaryActionIsEditSubmit
            ? (composerPending || composerSafeGuidancePending ? resolvedPendingLabel : resolvedActionLabel)
            : primaryActionIsQueueSubmit
              ? (composerSafeGuidancePending ? resolvedSafeGuidancePendingLabel : resolvedBusyPrimaryLabel)
            : (composerPending || composerSafeGuidancePending
              ? <LoaderCircle className={styles.statusSpinner} size={17} aria-hidden="true" />
              : <ArrowUp size={16} aria-hidden="true" />)}
        </VButton>
      ) : null}
      {runningGuidanceActionsEnabled ? (
        <VButton
          className={`${styles.composerRoundButton} ${styles.stopButton}`}
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
                    const turnErrorTypeLabelKey = turnError ? resolveTurnErrorTypeLabelKey(turnError.errorType) : "";
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

{selectionQuoteMenu ? (
        <ConversationSelectionQuoteMenu
          selectionRect={selectionQuoteMenu.rect}
          quoteLabel={lang === "zh" ? "引用到输入框" : "Quote to composer"}
          referenceLabel={lang === "zh" ? "作为引用" : "As reference"}
          copyLabel={lang === "zh" ? "复制" : "Copy"}
          sideLabel={lang === "zh" ? "辅助对话" : "Side chat"}
          onSideChat={onOpenSideChat ? handleSelectionSideChat : undefined}
          onQuote={handleSelectionQuoteToComposer}
          onReference={selectionQuoteMenu.sourceMessageId && onAddComposerReference
            ? handleSelectionReferenceToComposer
            : undefined}
          onCopy={handleSelectionCopy}
        />
      ) : null}

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

      {showComposer ? (
      <div className={composerVariant === "codex" ? styles.composerCodex : styles.composer}>
        {/* Inline edit owns the row editor; the composer field steps aside and
            only session status (the followup queue) keeps its slot here. */}
        {editingMessageId ? (
          composerFollowupQueueBar
        ) : (
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
          {/* Upload-failure repair: the error row grows a retry-all action only
              while failed attachment chips exist, so unrelated composer errors
              stay plain. */}
          {composerError ? (
            <p className={styles.composerError} role="alert">
              {composerError}
              {composerAttachments.some((attachment) => attachment.uploadStatus === "failed") && onRetryComposerAttachmentUploads ? (
                <VButton
                  className={styles.composerErrorRetryButton}
                  variant="ghost"
                  type="button"
                  isDisabled={composerPending}
                  onClick={onRetryComposerAttachmentUploads}
                  title={t("retryUpload")}
                  icon={<RefreshCw size={12} aria-hidden="true" />}
                >
                  <span>{t("retryUpload")}</span>
                </VButton>
              ) : null}
            </p>
          ) : null}
          {composerGuidance ? (
            <div className={styles.composerGuidance} role="status" aria-live="polite" data-composer-guidance>
              <span className={styles.composerGuidanceIcon} aria-hidden="true">i</span>
              <span>{composerGuidance}</span>
            </div>
          ) : null}
          {composerPasteNotice ? (
            <div className={styles.composerGuidance} role="status" aria-live="polite" data-composer-paste-notice="true">
              <span className={styles.composerGuidanceIcon} aria-hidden="true">i</span>
              <span>{composerPasteNotice}</span>
            </div>
          ) : null}
          {composerFollowupQueueBar}
          {composerAttachments.length ? (
            <div
              className={styles.composerAttachmentTray}
              role="list"
              aria-label={t("composerAttachmentTrayLabel")}
            >
              {composerAttachments.map((attachment) => {
                const attachmentIsImage = isImageAttachment(attachment);
                const previewLabel = t("composerAttachmentPreviewLabel").replace("{filename}", attachment.filename);
                const sizeLabel = attachmentSizeLabel(attachment.sizeBytes);
                const uploadFailed = attachment.uploadStatus === "failed";
                const uploading = attachment.uploadStatus === "uploading";
                return (
                  <div
                    key={attachment.id}
                    className={uploadFailed
                      ? `${styles.composerAttachmentChip} ${styles.composerAttachmentChipFailed}`
                      : styles.composerAttachmentChip}
                    role="listitem"
                    aria-invalid={uploadFailed || undefined}
                    title={uploadFailed ? t("attachmentUploadFailedRetryHint") : undefined}
                  >
                    {attachmentIsImage ? (
                      <VButton
                        className={styles.composerAttachmentPreview}
                        variant="ghost"
                        type="button"
                        onClick={() => openImagePreview({
                          src: attachment.previewUrl,
                          alt: attachment.filename,
                          downloadUrl: attachment.previewUrl,
                          downloadName: attachment.filename,
                        })}
                        title={previewLabel}
                        aria-label={previewLabel}
                      >
                        <span className={styles.composerAttachmentThumbFrame}>
                          <img className={styles.composerAttachmentThumb} src={attachment.previewUrl} alt="" />
                          <span className={styles.composerAttachmentThumbHint} aria-hidden="true">
                            {lang === "zh" ? "看大图" : "Zoom"}
                          </span>
                        </span>
                      </VButton>
                    ) : (
                      <span className={styles.composerAttachmentFileBadge} aria-hidden="true">
                        <FileText size={15} />
                      </span>
                    )}
                    <span className={styles.composerAttachmentCopy}>
                      <span className={styles.composerAttachmentName} title={attachment.filename}>{attachment.filename}</span>
                      {uploading ? (
                        <span className={styles.composerAttachmentStatusUploading}>
                          <LoaderCircle size={11} aria-hidden="true" className={styles.composerAttachmentUploadingIcon} />
                          {t("attachmentUploading")}
                        </span>
                      ) : sizeLabel ? (
                        <span className={styles.composerAttachmentMeta}>{sizeLabel}</span>
                      ) : null}
                      {uploadFailed ? (
                        <span className={styles.composerAttachmentStatusFailed}>{t("attachmentUploadFailedRetryHint")}</span>
                      ) : null}
                    </span>
                    {uploadFailed && onRetryComposerAttachment ? (
                      <VButton
                        className={styles.composerAttachmentRetryButton}
                        isIconOnly
                        variant="ghost"
                        type="button"
                        onClick={() => onRetryComposerAttachment(attachment.id)}
                        title={t("retryUpload")}
                        aria-label={`${t("retryUpload")}: ${attachment.filename}`}
                      >
                        <RefreshCw size={13} aria-hidden="true" />
                      </VButton>
                    ) : null}
                    {onRemoveComposerAttachment ? (
                      <VButton
                        className={styles.composerAttachmentRemoveButton}
                        isIconOnly
                        type="button"
                        onClick={() => onRemoveComposerAttachment(attachment.id)}
                        title={t("composerAttachmentRemove")}
                        aria-label={t("composerAttachmentRemove")}
                      >
                        <X size={13} aria-hidden="true" />
                      </VButton>
                    ) : null}
                  </div>
                );
              })}
            </div>
          ) : null}
          {composerReferences.length ? (
            <div
              className={styles.composerReferenceTray}
              role="list"
              aria-label={t("composerReferenceTrayLabel")}
            >
              {composerReferences.map((reference) => {
                const referenceId = reference.referenceId || reference.sessionId || reference.artifactId || "";
                const title = reference.title || reference.sessionId || reference.artifactId || "";
                const agentLabel = reference.agentDisplayName || reference.agentCode || reference.agentId || "";
                const kind = String(reference.kind || "session");
                const kindLabel = kind === "knowledge_base"
                  ? t("composerReferenceKindKnowledgeBase")
                  : kind === "knowledge_item"
                    ? t("composerReferenceKindKnowledgeItem")
                    : kind === "file"
                      ? t("composerReferenceKindFile")
                      : kind === "message"
                        ? t("composerReferenceKindMessage")
                        : t("composerReferenceKindSession");
                return (
                  <div key={`${kind}:${referenceId}`} className={styles.composerReferenceChip} role="listitem">
                    <span className={styles.composerReferenceIcon} aria-hidden="true">
                      {kind === "knowledge_base" || kind === "knowledge_item"
                        ? <BookOpen size={13} />
                        : kind === "file"
                          ? <FileText size={13} />
                          : kind === "message"
                            ? <Quote size={13} />
                            : <Link2 size={13} />}
                    </span>
                    <span className={styles.composerReferenceCopy}>
                      <strong title={title}>{title}</strong>
                      <small title={agentLabel || kindLabel}>{agentLabel || kindLabel}</small>
                    </span>
                    {onRemoveComposerReference ? (
                      <VButton
                        type="button"
                        onClick={() => onRemoveComposerReference(referenceId)}
                        title={t("composerReferenceRemove")}
                        aria-label={t("composerReferenceRemove")}
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
              {/* ZCode panel sections: two labeled groups (builtins vs skills);
                  ArrowUp/Down and the active index stay flat over the merged
                  ranked list, so option ids keep their flat positions. */}
              {(() => {
                let flatIndex = -1;
                const sections = groupSlashCommandSuggestionsBySection(slashSuggestions);
                return (
                  <>
                    {sections.map((section) => (
                      <div
                        key={section.id}
                        role="group"
                        aria-label={section.id === "commands" ? t("slashPanelCommandsSection") : t("slashPanelSkillsSection")}
                        className={styles.slashCommandSection}
                        data-slash-section={section.id}
                      >
                        <div className={styles.slashCommandSectionHeader} aria-hidden="true">
                          {section.id === "commands" ? t("slashPanelCommandsSection") : t("slashPanelSkillsSection")}
                        </div>
                        {section.suggestions.map((suggestion) => {
                          flatIndex += 1;
                          const index = flatIndex;
                          return (
                            <div
                              id={`${slashSuggestionListId}-option-${index}`}
                              key={suggestion.key}
                              role="option"
                              aria-selected={index === activeSlashIndex}
                              aria-label={suggestion.command}
                              className={styles.slashCommandSuggestionOption}
                              data-active={index === activeSlashIndex ? "true" : "false"}
                            >
                              <VButton
                                type="button"
                                className={
                                  index === activeSlashIndex
                                    ? `${styles.slashCommandSuggestionButton} ${styles.slashCommandSuggestionButtonActive}`
                                    : styles.slashCommandSuggestionButton
                                }
                                onMouseDown={(event) => event.preventDefault()}
                                onClick={() => handleSlashCommandSuggestion(suggestion)}
                              >
                                {suggestion.builtin ? (
                                  <span className={styles.slashCommandSuggestionIcon} aria-hidden="true">
                                    {suggestion.builtinId === "new_session" ? (
                                      <CirclePlus size={13} />
                                    ) : suggestion.builtinId === "model" ? (
                                      <Cpu size={13} />
                                    ) : (
                                      <Gauge size={13} />
                                    )}
                                  </span>
                                ) : null}
                                <code className={styles.slashCommandSuggestionCode}>
                                  {suggestion.command}
                                </code>
                                <span className={styles.slashCommandSuggestionDescription}>{suggestion.description}</span>
                                {suggestion.builtin ? (
                                  <span className={styles.slashCommandBuiltinBadge} data-vui="slash-builtin-badge">
                                    {t("slashBuiltinBadge")}
                                  </span>
                                ) : null}
                              </VButton>
                            </div>
                          );
                        })}
                      </div>
                    ))}
                    {/* Skills catalog health: a failed or still-loading library
                        must not read as "no skills" — the section says so. */}
                    {slashSkillsCatalogState === "loading" ? (
                      <div className={styles.slashCommandCatalogNotice} data-slash-catalog-state="loading">
                        {t("slashSkillsCatalogLoading")}
                      </div>
                    ) : slashSkillsCatalogState === "error" ? (
                      <div className={styles.slashCommandCatalogNotice} data-slash-catalog-state="error" role="status">
                        {t("slashSkillsCatalogError")}
                      </div>
                    ) : slashCommandSuggestions.length === 0 ? (
                      <div className={styles.slashCommandCatalogNotice} data-slash-catalog-state="empty">
                        {t("slashSkillsCatalogEmpty")}
                      </div>
                    ) : null}
                  </>
                );
              })()}
            </div>
          ) : null}
          {showReferenceSuggestions ? (
            <div
              id={referenceSuggestionListId}
              role="listbox"
              aria-label={t("composerReferenceTypeaheadListLabel")}
              className={styles.slashCommandSuggestions}
            >
              {referenceSuggestions.map((option, index) => (
                <div
                  id={`${referenceSuggestionListId}-option-${index}`}
                  key={option.id}
                  role="option"
                  aria-selected={index === activeReferenceIndex}
                  aria-label={option.title}
                  className={styles.slashCommandSuggestionOption}
                  data-active={index === activeReferenceIndex ? "true" : "false"}
                >
                  <VButton
                    type="button"
                    className={
                      index === activeReferenceIndex
                        ? `${styles.slashCommandSuggestionButton} ${styles.slashCommandSuggestionButtonActive}`
                        : styles.slashCommandSuggestionButton
                    }
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => handleReferenceTypeaheadSelect(option)}
                  >
                    <span className={styles.slashCommandSuggestionIcon} aria-hidden="true">
                      {option.reference.kind === "file" ? (
                        <FileText size={13} />
                      ) : option.reference.kind === "session" ? (
                        <MessageSquareText size={13} />
                      ) : (
                        <BookOpen size={13} />
                      )}
                    </span>
                    <strong className={styles.slashCommandSuggestionCode}>
                      {option.title}
                    </strong>
                    {option.meta ? (
                      <span className={styles.slashCommandSuggestionDescription}>{option.meta}</span>
                    ) : null}
                    <span className={styles.slashCommandBuiltinBadge} data-vui="reference-typeahead-badge">
                      {t("composerReferenceTypeaheadBadge")}
                    </span>
                  </VButton>
                </div>
              ))}
            </div>
          ) : null}
          <VNativeTextarea
            ref={composerInputRef}
            className={composerVariant === "codex" ? styles.inputCodex : styles.input}
            value={composerValue}
            disabled={composerDisabled && resolvedActionMode !== "stop"}
            placeholder={resolvedComposerPlaceholder}
            data-composer-prompt-suggestion={composerPromptSuggestion.ghost ? "true" : undefined}
            aria-label={lang === "zh" ? "发送消息" : "Message"}
            aria-controls={
              showSlashSuggestions
                ? slashSuggestionListId
                : showReferenceSuggestions
                  ? referenceSuggestionListId
                  : undefined
            }
            aria-expanded={showSlashSuggestions || showReferenceSuggestions ? true : undefined}
            aria-autocomplete={showSlashSuggestions || showReferenceSuggestions ? "list" : undefined}
            aria-activedescendant={
              showSlashSuggestions && activeSlashIndex >= 0
                ? `${slashSuggestionListId}-option-${activeSlashIndex}`
                : showReferenceSuggestions && activeReferenceIndex >= 0
                  ? `${referenceSuggestionListId}-option-${activeReferenceIndex}`
                  : undefined
            }
            onChange={(event) => {
              // Any manual edit (typing, IME, cut) leaves the history browse
              // mode; programmatic history fills do not go through onChange.
              exitComposerPromptHistoryBrowse();
              onComposerChange(event.target.value);
              syncComposerReferenceCaret(event.currentTarget);
            }}
            onCompositionStart={() => setComposerComposing(true)}
            onCompositionEnd={(event) => {
              // IME text was just committed: re-evaluate the token with the
              // post-composition caret so CJK "@引用" arms only after commit.
              setComposerComposing(false);
              syncComposerReferenceCaret(event.currentTarget);
            }}
            onSelect={() => syncComposerReferenceCaret(composerInputRef.current)}
            onKeyUp={() => syncComposerReferenceCaret(composerInputRef.current)}
            onPaste={(event) => {
              if (!onAddComposerAttachments || attachmentInputDisabled) {
                return;
              }
              const files = Array.from(event.clipboardData.files || []).filter((file) => isComposerAttachableFile(file));
              if (files.length) {
                event.preventDefault();
                onAddComposerAttachments(files);
                return;
              }
              // ZCode parity: an oversized plain-text paste silently becomes a
              // document attachment instead of flooding the draft; the attachment
              // chip plus the status row carry the notice.
              const pastedTextOverflow = extractComposerPastedTextOverflow(event.clipboardData);
              if (pastedTextOverflow) {
                event.preventDefault();
                onAddComposerAttachments([pastedTextOverflow]);
                setComposerPasteNotice(
                  t("composerPastedTextAttachmentNotice").replace("{filename}", pastedTextOverflow.name),
                );
              }
            }}
            onKeyDown={(event) => {
              // Find-in-transcript Esc first（优先于停止语义）：查找条打开时
              // Esc 只关查找条，绝不触发轮次停止。
              if (conversationFindOpen && event.key === "Escape" && !event.nativeEvent.isComposing) {
                event.preventDefault();
                closeConversationFind();
                return;
              }
              if (
                shouldAcceptComposerGhost({
                  ghost: composerPromptSuggestion.ghost,
                  key: event.key,
                  shiftKey: event.shiftKey,
                  ctrlKey: event.ctrlKey,
                  metaKey: event.metaKey,
                  altKey: event.altKey,
                })
              ) {
                event.preventDefault();
                composerPromptSuggestion.acceptGhost();
                return;
              }
              if (composerPromptSuggestion.ghost && event.key === "Escape") {
                event.preventDefault();
                composerPromptSuggestion.dismissGhost();
                return;
              }
              if (showSlashSuggestions && !event.shiftKey && !event.ctrlKey && !event.metaKey && !event.altKey) {
                if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                  event.preventDefault();
                  setSlashActiveIndex((current) => moveSlashCommandActiveIndex(
                    current,
                    event.key === "ArrowDown" ? 1 : -1,
                    slashSuggestions.length,
                  ));
                  return;
                }
                if (event.key === "Tab" || (event.key === "Enter" && !event.nativeEvent.isComposing)) {
                  event.preventDefault();
                  if (activeSlashIndex >= 0) {
                    handleSlashCommandSuggestion(slashSuggestions[activeSlashIndex]);
                  }
                  return;
                }
                if (event.key === "Escape") {
                  event.preventDefault();
                  handleSlashCommandDismiss();
                  return;
                }
              }
              if (showReferenceSuggestions && !event.shiftKey && !event.ctrlKey && !event.metaKey && !event.altKey) {
                if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                  event.preventDefault();
                  setReferenceActiveIndex((current) => moveSlashCommandActiveIndex(
                    current,
                    event.key === "ArrowDown" ? 1 : -1,
                    referenceSuggestions.length,
                  ));
                  return;
                }
                if (event.key === "Tab" || (event.key === "Enter" && !event.nativeEvent.isComposing)) {
                  event.preventDefault();
                  if (activeReferenceIndex >= 0) {
                    handleReferenceTypeaheadSelect(referenceSuggestions[activeReferenceIndex]);
                  }
                  return;
                }
                if (event.key === "Escape") {
                  event.preventDefault();
                  handleReferenceTypeaheadDismiss();
                  return;
                }
              }
              // Prompt history recall: claims bare ArrowUp/Down only when the
              // draft is empty (or browsing is already active); everything
              // above (find bar, ghost, slash, typeahead) already had its
              // chance, and IME composition is excluded inside.
              if (handleComposerPromptHistoryNavigation(event)) {
                return;
              }
              // Yield-aware Esc→stop: ghost/slash/typeahead branches above
              // return when they consume Escape; this fallback only fires when
              // the key is still unclaimed and a turn is running. Repeats are
              // deduped downstream by the sessionStopping stop guard.
              if (
                shouldStopComposerOnEscape({
                  key: event.key,
                  defaultPrevented: event.defaultPrevented,
                  composing: event.nativeEvent.isComposing,
                  actionMode: resolvedActionMode,
                  hasStopHandler: Boolean(onStop),
                  ghostVisible: Boolean(composerPromptSuggestion.ghost),
                  slashSuggestionsOpen: showSlashSuggestions,
                  referenceTypeaheadOpen: showReferenceSuggestions,
                })
              ) {
                event.preventDefault();
                onStop?.();
              }
              // Enter delivery: while a turn runs, Enter immediately steers
              // the draft via the existing safe-guidance channel, falling
              // back to queueing when the payload cannot ride guidance
              // (attachments/references) or no guidance handler exists.
              // Idle Enter sends. Modifier keys never change the delivery
              // (user decision removed the Ctrl/⌘+Enter flip).
              const composerEnterDelivery = resolveComposerEnterDelivery({
                key: event.key,
                shiftKey: event.shiftKey,
                ctrlKey: event.ctrlKey,
                metaKey: event.metaKey,
                altKey: event.altKey,
                isComposing: event.nativeEvent.isComposing,
                actionMode: resolvedActionMode,
                canDeliverImmediately: Boolean(onSafeGuidance)
                  && !hasComposerAttachments
                  && !hasComposerReferences,
              });
              if (composerEnterDelivery !== "none") {
                event.preventDefault();
                if (
                  composerEnterDelivery === "send"
                  && !resolvedActionDisabled
                  && (composerValue.trim() || hasComposerAttachments || hasComposerReferences)
                ) {
                  handleSendAndFollowLatest();
                } else if (composerEnterDelivery === "steer" && composerValue.trim() && onSafeGuidance) {
                  if (!guidanceActionDisabled && !handleSideChatCommand()) {
                    onSafeGuidance();
                  }
                } else if (
                  (queuePrimaryKind === "queue" || queuePrimaryKind === "immediate")
                  && !guidanceActionDisabled
                ) {
                  handleQueueSubmit();
                }
              }
            }}
          />
          <div className={composerVariant === "codex" ? styles.composerToolbarCodex : styles.composerToolbar}>
            <div className={styles.composerToolbarStart}>
              {composerLeadingControl ?? (
                <VButton
                  className={styles.attachButton}
                  isIconOnly
                  isDisabled={attachmentInputDisabled || !onAddComposerAttachments}
                  type="button"
                  onClick={() => attachmentInputRef.current?.click()}
                  title={t("composerAttachTooltip")}
                  aria-label={t("composerAttachTooltip")}
                >
                  <ImagePlus size={16} />
                </VButton>
              )}
              {permissionControl ? (
                <AgentPermissionPresetControl
                  {...permissionControl}
                  lang={lang}
                  surface="composer"
                />
              ) : null}
            </div>
            <div className={styles.composerToolbarEnd}>
              {turnModelControl ? <ConversationTurnModelControl {...turnModelControl} /> : null}
              {llmControl ? <ConversationInferenceControl {...llmControl} /> : null}
              {composerContextRing ? (
                <ComposerContextRing
                  model={composerContextRing}
                  lang={lang}
                  sessionId={sessionId}
                  onOpenDetail={onOpenComposerContextDetail}
                />
              ) : null}
              {composerVariant === "codex" ? composerActions : null}
            </div>
          </div>
        </div>
        )}
        <VNativeInput
          ref={attachmentInputRef}
          className={styles.hiddenAttachmentInput}
          type="file"
          accept={composerAttachmentAcceptAttribute()}
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
        onConfirm={() => {
          const message = forkDialogMessage;
          if (!message || !onForkSessionFromNode || forkPending) {
            return;
          }
          setForkPending(true);
          void Promise.resolve(onForkSessionFromNode(message, forkScope))
            .then(() => setForkDialogMessage(null))
            .catch(() => undefined)
            .finally(() => setForkPending(false));
        }}
        onCancel={() => setForkDialogMessage(null)}
      />
    </div>
  );
});
