/**
 * Chat Coding workbench implementation (R01).
 * Entry re-export: web/src/routes/ChatCodingRoute.tsx
 * Prefer editing modules under web/src/routes/chat/ over growing this file.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Apple,
  ArrowUpRight,
  Check,
  ChevronRight,
  HeartHandshake,
  MessageCircleHeart,
  RotateCcw,
  Search,
  Sparkles,
  Trash2,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  lazy,
  Suspense,
  useMemo,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { listPendingSessionToolApprovals } from "../../api/chat";
import { fetchJson } from "../../api/client";
import { createChatWorkspaceCache } from "../chatWorkspaceCache";
import { prefetchConversationView } from "../../components/conversation/prefetchConversationView";
import { queryKeys } from "../../api/queryKeys";
import {
  AgentInstance,
  ChatRoomDetail,
  ChatRoomParticipant,
  ChatRoomMode,
  ChatRoomPurpose,
  ConfigSummary,
  FileContent,
  MentalStateSnapshot,
  PetActionResponse,
  PetSummary,
  RuntimeSummary,
  ChatNextStateSignalSummary,
  SessionGuidanceMode,
  ConversationSummary,
  SessionDetail,
  AgentToolGovernanceRequest,
  SessionRuntimeNotice,
  SessionToolApprovalRequest,
    SessionLlmOptions,
    SessionQueryResponse,
    SessionSummary,
  SessionStreamEvent,
  SessionReferenceAttachment,
  SessionTurnAcceptedResponse,
  SkillLibraryPayload,
  TeamListPayload,
  ConversationMessage,
  ToolCall,
} from "../../api/types";
import type { ConversationStreamingFramePaintMetrics } from "../../components/conversation/conversationStreamingMetrics";
import { shouldShowNextStateSignalInConversation } from "../../components/conversation/conversationNextStateSignal";
import type { TurnAvatarResolution } from "../../components/conversation/conversationTurnAvatar";
import { isAgentInboxMessage } from "../../components/conversation/conversationMessagePredicates";
import { VButton, VContextualHint, VInput, VNativeInput, VStateSurface, VTooltip, type VButtonProps } from "../../components/vui";
import { collectBrowserPageSnapshot, postBrowserTelemetry } from "../../app/browserTelemetry";
import { getPageInstanceId } from "../../app/pageInstance";
import { usePageVisibility, useStartupWarmup } from "../../app/pollingPolicy";
import type { TranslationKey } from "../../i18n/dictionary";
import { useAppI18n } from "../../i18n/useAppI18n";
import { useChatWorkbenchStore } from "../../store/chatWorkbenchStore";
import {
  deriveSessionDetailQueryErrorState,
  deriveSessionListQueryErrorState,
  mergeSessionDetailMessageWindow,
  mergeSessionDetailIntoSummaries,
} from "../chatSessionState";
import {
  reconcileAgentSessionDetailCache,
  updateSessionSummaryCaches,
} from "../chatSessionIndexQuery";
import { isTempSessionId } from "../sessionOptimisticIds";
import {
  shouldShowConversationIndexLoading,
} from "../chatSessionStartupGate";
import {
  resolveChatLiveQueryPolicy,
} from "../chatLiveQueryPolicy";
import { resolveChatSecondaryPollPolicy } from "../chatSecondaryPollPolicy";
import {
  latestUserMessageId as deriveLatestUserMessageId,
  resolveComposerDraftValue,
  resolveLatestEditTarget,
} from "../chatComposerState";
import {
  resolveChatUserDisplayName,
} from "../chatCompactPanel";
import {
  tokenSpeedSampleFromMessages,
  updateTokenSpeedTracker,
  type TokenSpeedTrackerState,
} from "../chatTokenSpeed";
import {
  browserDesktopNotificationBridge,
  createDesktopConversationNotifier,
} from "../chatDesktopNotifications";
import {
  clearPendingSelfEvolutionHandoff,
  loadPendingSelfEvolutionHandoff,
} from "../selfEvolutionHandoff";
import {
  agentDisplayInfo,
  participantAgentDisplayInfo,
  sessionAgentDisplayInfo,
} from "../agentDisplay";
import { type CliAgentRunTab } from "../AgentSessionTabStrip";
import {
  visibleDirectoryAgents,
} from "../AgentConversationDirectory";
import {
  markSessionActivitySeen,
  sessionActivityStamp,
} from "../sessionActivityIndicator";
import type { AgentContextMenuState } from "../AgentContextMenu";
import { teamWorkspaceRoute } from "../teams/researchWorkspaceModel";
import {
  DEFAULT_COLLAPSED_CONVERSATION_GROUPS,
  defaultConversationGroupCollapsed,
  conversationGroupLabel,
  hasInvalidChildSessionLink,
  isRepresentedInAgentSessionTabs,
  rootSessionIdFor,
  sessionToConversationSummary,
  useConversationIndexModel,
  type ConversationIndexDynamicGroupKey,
} from "../conversationIndexModel";
import {
  activeTurnLayerToConversationMessage,
  activeTurnLayerTextLength,
  isActiveTurnSettledByDetail,
  setActiveTurnLayerForSession,
  type ActiveTurnLayerState,
} from "../chatActiveTurnLayer";
import {
  isChildSession,
} from "../DirectSessionIndexItem";
import { agentCenterConfigRoute } from "../agentCenterRoutes";
import {
  buildChatMentionTargets,
  type ChatMentionTarget,
} from "../chatMentionTokens";
import {
  buildConversationComposerBridgeState,
} from "./ChatConversationComposerBridge";
import {
  chatStreamPerformanceNowMs,
  describeChatRouteError as describeError,
  isBusyPhase,
  isRunningPhase,
  isStoppingPhase,
  MAX_LEFT_PANEL_WIDTH,
  MAX_RIGHT_PANEL_WIDTH,
  MIN_LEFT_PANEL_WIDTH,
  MIN_RIGHT_PANEL_WIDTH,
  runtimeMatchesSelectedChatSession,
  shouldSuppressComposerErrorForTurnError,
} from "./chatCodingRouteViewModel";
import { ChatWorkbenchCenterTabStrip } from "./ChatWorkbenchCenterTabStrip";
import {
  ChatWorkbenchLeftResizeHandle,
  ChatWorkbenchRightResizeHandle,
} from "./ChatWorkbenchPaneResizeHandles";
import { ChatSessionWorkbenchShell } from "./ChatSessionWorkbenchShell";
import { ChatWorkbenchCenterColumn } from "./ChatWorkbenchCenterColumn";
import { ChatWorkbenchConversationIndexPanel } from "./ChatWorkbenchConversationIndexPanel";
import { ChatWorkbenchCenterSessionSurface } from "./ChatWorkbenchCenterSessionSurface";
import { ChatWorkbenchConversationIndexRailHost } from "./ChatWorkbenchConversationIndexRailHost";
import {
  ChatWorkbenchOverlayBackdrop,
  ChatWorkbenchSecondaryDialogs,
} from "./ChatWorkbenchSecondarySurfaces";
import { ChatWorkbenchStatusRailHost } from "./ChatWorkbenchStatusRailHost";
import { useChatWorkbenchLayout } from "./useChatWorkbenchLayout";
import {
  useChatLocaleFormatters,
  useChatReturnNavigation,
} from "./useChatWorkbenchPresentation";
import {
  resolveAgentContextMenuArchivePending,
  resolveSessionContextMenuPendingFlags,
} from "./chatContextMenuPending";
import { eventInsideContextMenuSurface } from "./chatContextMenuDismiss";
import { resolveSessionIndexProgressModel } from "./chatSessionIndexProgress";
import {
  useChatComposerSubmitActions,
  useChatComposerTurnMutations,
} from "./useChatComposerSubmit";
import {
  nextSessionStreamGraceWindow,
  resolveSessionStreamRouteSettling,
  resolveSessionStreamRouteSwitchGraceActive,
  resolveSessionStreamRouteTargetMatches,
  resolveSessionStreamShouldConnect,
  type SessionStreamDecisionSnapshot,
} from "./chatSessionStreamConnect";
import { useSessionDetailStream } from "./useSessionDetailStream";
import { useGroupRoomStream } from "./useGroupRoomStream";
import { useChatSessionSelection } from "./useChatSessionSelection";
import { useChatWorkspaceLifecycle } from "./useChatWorkspaceLifecycle";
import { useChatSessionDetailMutations } from "./useChatSessionDetailMutations";
import { useChatWorkspaceActions } from "./useChatWorkspaceActions";
import {
  useChatSessionRenameMenu,
  type SessionContextMenuState,
} from "./useChatSessionRenameMenu";
import { useChatAgentDirectoryActions } from "./useChatAgentDirectoryActions";
import { useChatAgentMutations } from "./useChatAgentMutations";
import { useChatCliAgentTerminal } from "./useChatCliAgentTerminal";
import { buildChatCacheDetailViewModel } from "./chatCacheDetailModel";
import { useChatCacheDetailDialog } from "./useChatCacheDetailDialog";
import { useChatWorkbenchDirectoryQueries } from "./useChatWorkbenchDirectoryQueries";
import { useChatWorkbenchSessionQueries } from "./useChatWorkbenchSessionQueries";
import {
  buildSessionsByIdMap,
  collectRuntimeRunningSessionIds,
  filterSessionsForSelectedAgent,
  mergeVisibleDirectSessions,
  resolveActiveSessionAgentId,
} from "./chatWorkbenchSessionDirectoryModel";
import { buildChatTokenStatusViewModel } from "./chatTokenStatusModel";
import {
  buildAgentSessionTabs,
  buildChatActiveSkillViewModel,
  buildChatMentalStateViewModel,
  buildChatPetCompanionViewModel,
  buildChatSessionStateViewModel,
  type ActiveSkillContract,
} from "./chatSessionSurfaceModel";
import {
  chatRoomModeLabel,
  chatRoomPurposeLabel,
  contextCompositionSegmentClass,
  contextCompositionSegmentLabel,
  cacheCompositionSegmentLabel,
  formatAgentIdentityWithRole,
  compactAgentRoleLabel,
  agentRoleClass,
  avatarInitials,
  avatarImageUrlFrom,
  imageInputModelIdForAgent,
  modelImageInputSupport,
  conversationMetadataText,
  renderAgentAvatar,
  isAvailableGroupParticipant,
} from "./chatRoutePresentation";
import {
  SESSION_DETAIL_INITIAL_MESSAGE_LIMIT,
  SESSION_DETAIL_HISTORY_PAGE_SIZE,
  fetchSessionDetailWindow,
  isSessionNotFoundError,
  isSessionDetailHardLoading,
  latestVisibleTurnErrorMessage,
  prefetchSessionDetailWindow,
  removeDeletedSessionFromConversations,
  mergeSessionDetailIntoConversations,
  resolveActiveSessionDetailForUi,
  resolveNeighborSessionIdsForPrefetch,
  sessionDetailSnapshotKey,
  isStaleLedgerUpdate,
  latestMentalSnapshot,
  latestChatRoomRound,
} from "./chatSessionDetailHelpers";
import {
  forgetSessionDetailPaint,
  resolveStickySessionDetailPaint,
  shouldShowStickyTranscriptPending,
  touchSessionKeepAlive,
} from "./chatSessionPaintCache";

import {
  cliAgentRunIdFromTabId,
  cliAgentRunTabId,
} from "./cliAgentRunModel";
import {
  CHAT_FEATURE_PRESETS,
  DEFAULT_CHAT_FEATURE_PRESETS,
  chatFeaturePresetShortLabel,
  type FeaturePresetKey,
} from "./chatFeaturePresets";
import {
  toolApprovalLabels,
  toolApprovalRiskLabel,
  toolApprovalScopeLabel,
} from "./toolApprovalLabels";
import {
  toolApprovalActionPreview,
  toolApprovalDisplayName,
} from "./toolApprovalPreview";
import { postSubmitTelemetry } from "./chatSubmitTelemetry";
import {
  buildSessionReferencePayload,
  clearSessionImageAttachments,
  clearSessionReferenceAttachments,
  readStoredMentalModelToggle,
  readStoredRuntimeStatusToggle,
  startSessionReferenceDrag,
  type ComposerImageAttachment,
} from "./chatComposerSubmitModel";
import styles from "../ChatCodingRoute.styles";

export type { CliAgentRunView, CliAgentTerminalSession } from "./cliAgentRunModel";
export { canInputTerminal } from "./cliAgentRunModel";

const CliAgentRunTerminalPanel = lazy(() =>
  import("./CliAgentRunTerminalPanel").then((module) => ({
    default: module.CliAgentRunTerminalPanel,
  })),
);


type SessionDetailWithActiveSkill = SessionDetail & {
  activeSkillContract?: ActiveSkillContract | null;
};

type PetInteractionAction = "feed" | "talk" | "care";

type RightIndexPanel = "conversations" | "members";


export function ChatCodingRoute() {
  // pet + evolution: companion rail shows mental/pet labels (otherwise raw keys leak).
  const { lang, t, statusLabel } = useAppI18n({ domains: ["chat", "agents", "pet", "evolution"] });
  const queryClient = useQueryClient();
  const chatWorkspaceCache = useMemo(() => createChatWorkspaceCache(queryClient), [queryClient]);
  const navigate = useNavigate();
  const location = useLocation();
  const activeSessionId = useChatWorkbenchStore((state) => state.activeSessionId);
  const sessionWorkspaces = useChatWorkbenchStore((state) => state.sessionWorkspaces);
  const setActiveSession = useChatWorkbenchStore((state) => state.setActiveSession);
  const hydrateSession = useChatWorkbenchStore((state) => state.hydrateSession);
  const removeSessionWorkspace = useChatWorkbenchStore((state) => state.removeSession);
  const closePreviewTab = useChatWorkbenchStore((state) => state.closePreviewTab);
  const latestDirectSessionSelectionRef = useRef("");
  const latestDirectSessionSelectionAtRef = useRef(0);
  const directSessionSelectionGenerationRef = useRef(0);
  const reselectDirectSessionRef = useRef<(sessionId: string) => void>(() => undefined);
  const setActiveTab = useChatWorkbenchStore((state) => state.setActiveTab);
  const [sessionFilter, setSessionFilter] = useState("");
  const imageUploadInFlightRef = useRef<Record<string, boolean>>({});
  const [sessionDrafts, setSessionDrafts] = useState<Record<string, string>>({});
  const [sessionComposerErrors, setSessionComposerErrors] = useState<Record<string, string>>({});
  const [sessionImageAttachments, setSessionImageAttachments] = useState<Record<string, ComposerImageAttachment[]>>({});
  const [sessionReferenceAttachments, setSessionReferenceAttachments] = useState<Record<string, SessionReferenceAttachment[]>>({});
  const [sessionImageUploadPending, setSessionImageUploadPending] = useState<Record<string, boolean>>({});
  const [sessionEditTargets, setSessionEditTargets] = useState<Record<string, { messageId: string; original: string }>>({});
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const editingSessionIdRef = useRef<string | null>(null);
  /** Suppress tab title blur-submit while create remaps temp id → server id. */
  const suppressRenameBlurUntilRef = useRef(0);
  const [editingSessionTitle, setEditingSessionTitle] = useState("");
  const [sessionContextMenu, setSessionContextMenu] = useState<SessionContextMenuState | null>(null);
  const [agentContextMenu, setAgentContextMenu] = useState<AgentContextMenuState | null>(null);
  const [activeTurnLayersBySession, setActiveTurnLayersBySession] = useState<Record<string, ActiveTurnLayerState>>({});

  useEffect(() => {
    editingSessionIdRef.current = editingSessionId;
  }, [editingSessionId]);

  const [tokenSpeedTracker, setTokenSpeedTracker] = useState<TokenSpeedTrackerState | null>(null);
  const [petActionFeedback, setPetActionFeedback] = useState("");
  const [mentalModelEnabledForNextTurn, setMentalModelEnabledForNextTurn] = useState<boolean>(
    () => readStoredMentalModelToggle() ?? false,
  );
  const [runtimeStatusEnabledForNextTurn, setRuntimeStatusEnabledForNextTurn] = useState<boolean>(
    () => readStoredRuntimeStatusToggle() ?? true,
  );
  const [featurePresetState, setFeaturePresetState] = useState<Record<FeaturePresetKey, boolean>>(
    DEFAULT_CHAT_FEATURE_PRESETS,
  );
  const [groupComposerOpen, setGroupComposerOpen] = useState(false);
  const [groupTitleDraft, setGroupTitleDraft] = useState("");
  const [groupModeDraft, setGroupModeDraft] = useState("round_robin");
  const [groupPurposeDraft, setGroupPurposeDraft] = useState("discussion");
  const [groupSelectedAgentIds, setGroupSelectedAgentIds] = useState<string[]>([]);
  const [collapsedConversationGroups, setCollapsedConversationGroups] = useState<Record<string, boolean>>(
    DEFAULT_COLLAPSED_CONVERSATION_GROUPS,
  );
  const [rightIndexPanel, setRightIndexPanel] = useState<RightIndexPanel>("conversations");
  const [agentCreateWizardOpen, setAgentCreateWizardOpen] = useState(false);
  const agentCreateTriggerRef = useRef<HTMLButtonElement | null>(null);
  const [activeGroupRoomId, setActiveGroupRoomId] = useState("");
  const [expandedGroupAgentSessionIds, setExpandedGroupAgentSessionIds] = useState<string[]>([]);
  const [expandedGroupMessageIds, setExpandedGroupMessageIds] = useState<string[]>([]);
  const [groupTopicDraft, setGroupTopicDraft] = useState("");
  const [projectBusDraft, setProjectBusDraft] = useState("");
  const [projectBusInterruptTargets, setProjectBusInterruptTargets] = useState(false);
  const [groupRoomActionError, setGroupRoomActionError] = useState("");
  const [groupManageTitleDraft, setGroupManageTitleDraft] = useState("");
  const [groupManageSessionIds, setGroupManageSessionIds] = useState<string[]>([]);
  const [groupManageModeDraft, setGroupManageModeDraft] = useState("round_robin");
  const [groupManagePurposeDraft, setGroupManagePurposeDraft] = useState("discussion");
  const lastConversationStreamingFrameTelemetryAtRef = useRef<Record<string, number>>({});
  const lastAssistantDeltaAppliedAtRef = useRef<Record<string, number>>({});
  const activeTurnLayersBySessionRef = useRef<Record<string, ActiveTurnLayerState>>({});
  const desktopConversationNotifierRef = useRef(createDesktopConversationNotifier({
    bridge: browserDesktopNotificationBridge(),
    postTelemetry: postBrowserTelemetry,
  }));
  const sessionStreamDecisionSnapshotRef = useRef<SessionStreamDecisionSnapshot>({
    sessionId: "",
    shouldConnect: false,
    pageVisible: false,
    chatStartupWarmupActive: false,
    chatPollingVisible: false,
    directSessionBackgroundSyncActive: false,
    routeTargetMatches: false,
    routeSettling: false,
    routeSwitchGraceActive: false,
    routeSwitchGraceMsRemaining: 0,
  });

  const chatRouteMountStartedAtRef = useRef(Date.now());
  const chatRouteShellMountedLoggedRef = useRef(false);
  const chatRouteStartupReadyLoggedRef = useRef(false);
  const chatRouteLongTaskCountRef = useRef(0);
  const requestedSessionId = useMemo(() => {
    return new URLSearchParams(location.search).get("session") ?? "";
  }, [location.search]);
  const requestedRoomId = useMemo(() => {
    return new URLSearchParams(location.search).get("room") ?? "";
  }, [location.search]);
  const { chatReturnTarget, chatReturnLabel } = useChatReturnNavigation(location.search, lang);
  useEffect(() => {
    activeTurnLayersBySessionRef.current = activeTurnLayersBySession;
  }, [activeTurnLayersBySession]);
  useEffect(() => {
    if (chatRouteShellMountedLoggedRef.current) {
      return;
    }
    chatRouteShellMountedLoggedRef.current = true;
    postBrowserTelemetry({
      phase: "navigation",
      eventCode: "browser.chat_route.shell_mounted",
      message: "Chat route shell mounted.",
      fields: {
        durationMs: Math.max(0, Date.now() - chatRouteMountStartedAtRef.current),
        pathname: location.pathname,
        requestedSession: Boolean(requestedSessionId),
        requestedRoom: Boolean(requestedRoomId),
        activeSession: Boolean(activeSessionId),
      },
    });
  }, [activeSessionId, location.pathname, requestedRoomId, requestedSessionId]);
  useEffect(() => {
    if (typeof PerformanceObserver === "undefined") {
      return undefined;
    }
    const observer = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (chatRouteLongTaskCountRef.current >= 8) {
          observer.disconnect();
          return;
        }
        chatRouteLongTaskCountRef.current += 1;
        postBrowserTelemetry({
          phase: "navigation",
          eventCode: "browser.chat_route.long_task",
          message: "Chat route long task observed.",
          fields: {
            durationMs: Math.round(entry.duration),
            startTimeMs: Math.round(entry.startTime),
            count: chatRouteLongTaskCountRef.current,
          },
        });
      }
      return undefined;
    });
    try {
      observer.observe({ entryTypes: ["longtask"] });
    } catch {
      return undefined;
    }
    return () => observer.disconnect();
  }, []);
  const pageVisible = usePageVisibility();
  const [chatStartupDataReady, setChatStartupDataReady] = useState(false);
  const [startupDetailSettledSessionId, setStartupDetailSettledSessionId] = useState("");
  const chatStartupWarmupActive = useStartupWarmup(chatStartupDataReady);
  const chatPollingVisible = pageVisible || chatStartupWarmupActive;
  const projectBusActive = activeGroupRoomId === "__project_agent_bus__";
  const groupPanelActive = Boolean(activeGroupRoomId);
  const standardGroupRoomActive = groupPanelActive && !projectBusActive;
  const {
    layoutRef,
    dragState,
    responsiveLayout,
    conversationIndexCollapsed,
    statusRailCollapsed,
    conversationIndexOverlayOpen,
    statusRailOverlayOpen,
    responsiveOverlayOpen,
    layoutStyle,
    chatLayoutClassName,
    centerPaneClassName,
    statusRailClassName,
    conversationIndexPaneClassName,
    leftPanelWidth,
    rightPanelWidth,
    handleResizeStart,
    handleResizeKeyDown,
    closeResponsiveOverlayPane,
    setLeftRailCollapsed,
    setRightPaneCollapsed,
    setResponsiveOverlayPane,
  } = useChatWorkbenchLayout({ standardGroupRoomActive });
  const directSessionPanelActive = Boolean(activeSessionId) && !groupPanelActive;
  const sessionQueryText = sessionFilter.trim();
  const [directSessionBackgroundSyncActive, setDirectSessionBackgroundSyncActive] = useState(false);
  const [groupBackgroundSyncActive, setGroupBackgroundSyncActive] = useState(false);
  const secondaryChatDataEnabled = chatStartupDataReady && (
    !activeSessionId || startupDetailSettledSessionId === activeSessionId
  );
  const sessionStreamRouteTargetMatches = resolveSessionStreamRouteTargetMatches({
    activeSessionId,
    groupPanelActive,
    requestedSessionId,
  });

  useEffect(() => {
    if (!sessionContextMenu && !agentContextMenu) {
      return;
    }
    function closeSessionContextMenu(event?: Event) {
      // Radix portals the menu outside the React tree; a global pointerdown must
      // not unmount it before item onSelect (rename/create) can run.
      if (event && eventInsideContextMenuSurface(event.target)) {
        return;
      }
      setSessionContextMenu(null);
      setAgentContextMenu(null);
    }
    function handleKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") {
        closeSessionContextMenu();
      }
    }
    window.addEventListener("pointerdown", closeSessionContextMenu);
    window.addEventListener("scroll", closeSessionContextMenu, true);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("pointerdown", closeSessionContextMenu);
      window.removeEventListener("scroll", closeSessionContextMenu, true);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [agentContextMenu, sessionContextMenu]);
  const sessionStreamRouteSettling = resolveSessionStreamRouteSettling({
    activeSessionId,
    groupPanelActive,
    requestedSessionId,
  });
  const sessionStreamGraceSessionRef = useRef("");
  const sessionStreamGraceUntilRef = useRef(0);
  const nextGrace = nextSessionStreamGraceWindow({
    activeSessionId,
    currentGraceSessionId: sessionStreamGraceSessionRef.current,
    currentGraceUntilMs: sessionStreamGraceUntilRef.current,
  });
  if (nextGrace.changed) {
    sessionStreamGraceSessionRef.current = nextGrace.graceSessionId;
    sessionStreamGraceUntilRef.current = nextGrace.graceUntilMs;
  }
  const sessionStreamRouteSwitchGraceActive = resolveSessionStreamRouteSwitchGraceActive({
    activeSessionId,
    routeTargetMatches: sessionStreamRouteTargetMatches,
    graceSessionId: sessionStreamGraceSessionRef.current,
    graceUntilMs: sessionStreamGraceUntilRef.current,
  });
  const sessionStreamShouldConnect = resolveSessionStreamShouldConnect({
    activeSessionId,
    routeTargetMatches: sessionStreamRouteTargetMatches && !isTempSessionId(activeSessionId),
    chatPollingVisible,
    routeSwitchGraceActive: sessionStreamRouteSwitchGraceActive,
  });
  sessionStreamDecisionSnapshotRef.current = {
    sessionId: activeSessionId || "",
    shouldConnect: sessionStreamShouldConnect,
    pageVisible,
    chatStartupWarmupActive,
    chatPollingVisible,
    directSessionBackgroundSyncActive,
    routeTargetMatches: sessionStreamRouteTargetMatches,
    routeSettling: sessionStreamRouteSettling,
    routeSwitchGraceActive: sessionStreamRouteSwitchGraceActive,
    routeSwitchGraceMsRemaining: Math.max(0, sessionStreamGraceUntilRef.current - Date.now()),
  };
  const groupStreamShouldConnect = Boolean(
    standardGroupRoomActive
    && activeGroupRoomId
    && (chatPollingVisible || groupBackgroundSyncActive),
  );
  const syncChatRoomDetail = useCallback(
    (room: ChatRoomDetail) => {
      queryClient.setQueryData(queryKeys.chatRoom(room.roomId), room);
      if (String(room.status ?? "").trim().toLowerCase() !== "running") {
        void chatWorkspaceCache.afterChatRoomChanged(room.roomId);
      }
    },
    [chatWorkspaceCache, queryClient],
  );
  const { groupStreamConnected } = useGroupRoomStream({
    activeGroupRoomId,
    groupStreamShouldConnect,
    syncChatRoomDetail,
  });
  const syncSessionDetail = useCallback(
    (detail: SessionDetail) => {
      let shouldSyncSummaries = true;
      queryClient.setQueryData<SessionDetail>(queryKeys.session(detail.id), (previous) => {
        if (isStaleLedgerUpdate(previous?.ledgerSeq, detail.ledgerSeq)) {
          shouldSyncSummaries = false;
          return previous ?? detail;
        }
        const nextDetail = mergeSessionDetailMessageWindow(previous, detail);
        if (previous && sessionDetailSnapshotKey(previous) === sessionDetailSnapshotKey(nextDetail)) {
          shouldSyncSummaries = false;
          return previous;
        }
        return nextDetail;
      });
      if (!shouldSyncSummaries) {
        return;
      }
      updateSessionSummaryCaches(queryClient, (sessions) =>
        mergeSessionDetailIntoSummaries(sessions, detail),
      );
      reconcileAgentSessionDetailCache(queryClient, detail);
      const detailRootSessionId = rootSessionIdFor(detail);
      if (isChildSession(detail) && detailRootSessionId) {
        queryClient.setQueryData<SessionSummary[]>(queryKeys.sessionChildSessions(detailRootSessionId), (sessions) =>
          mergeSessionDetailIntoSummaries(sessions, detail),
        );
      }
      queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations(), (conversations) =>
        mergeSessionDetailIntoConversations(conversations, detail),
      );
    },
    [queryClient],
  );
  const sessionStreamAvailable = typeof EventSource !== "undefined";
  const sessionTitleForNotifications = (
    queryClient.getQueryData<SessionDetail>(queryKeys.session(activeSessionId || "none"))?.title
    || activeSessionId
    || ""
  );
  const { sessionStreamConnected } = useSessionDetailStream({
    activeSessionId,
    sessionStreamShouldConnect,
    queryClient,
    syncSessionDetail,
    setActiveTurnLayersBySession,
    activeTurnLayersBySessionRef,
    lastAssistantDeltaAppliedAtRef,
    sessionStreamDecisionSnapshotRef,
    desktopConversationNotifierRef,
    sessionTitleForNotifications,
  });
  const chatLiveQueryPolicyInput = {
    chatPollingVisible,
    chatStartupWarmupActive,
    directSessionBackgroundSyncActive,
    groupBackgroundSyncActive,
    directSessionPanelActive,
    standardGroupRoomActive,
    sessionStreamAvailable,
    sessionStreamShouldConnect,
    sessionStreamConnected,
    groupStreamShouldConnect,
    groupStreamConnected,
    activeSessionId: activeSessionId || "",
    activeRootSessionId: "",
  };
  const chatLiveQueryPolicy = resolveChatLiveQueryPolicy(chatLiveQueryPolicyInput);
  const { groupStreamOwnsLiveQueries } = chatLiveQueryPolicy;
  const teamsPickerNeeded = groupComposerOpen || standardGroupRoomActive;
  const chatSecondaryPollPolicy = resolveChatSecondaryPollPolicy({
    chatPollingVisible,
    chatStartupWarmupActive,
    secondaryChatDataEnabled,
    directSessionPanelActive,
    teamsPickerNeeded,
    projectBusActive,
  });
  useEffect(() => {
    if (!standardGroupRoomActive && rightIndexPanel === "members") {
      setRightIndexPanel("conversations");
    }
  }, [standardGroupRoomActive, rightIndexPanel]);

  const [selectedAgentId, setSelectedAgentId] = useState("");
  const {
    runtimeQuery,
    petQuery,
    configSummaryQuery,
    activeSessionBootstrapQuery,
    sessionIndexQueryEnabled,
    modelLabelsById,
    modelImageInputSupportById,
    resolveModelLabel,
    rawSessionsQuery,
    sessionsQuery,
    conversationsQuery,
    teamsQuery,
    agentsQuery,
    agentPermissionPresetMutation,
    skillsQuery,
    slashCommandSuggestions,
    chatRoomModesQuery,
    chatRoomPurposesQuery,
    activeGroupRoomQuery,
    projectAgentBusQuery,
    expandedGroupAgentDetailQueries,
  } = useChatWorkbenchDirectoryQueries({
    queryClient,
    secondaryChatDataEnabled,
    chatSecondaryPollPolicy,
    chatLiveQueryPolicy,
    sessionQueryText,
    requestedSessionId,
    requestedRoomId,
    groupComposerOpen,
    standardGroupRoomActive,
    projectBusActive,
    activeSessionId: activeSessionId || "",
    activeGroupRoomId,
    expandedGroupAgentSessionIds,
    chatPollingVisible,
    groupStreamConnected,
    groupBackgroundSyncActive,
    chatStartupWarmupActive,
    lang,
    describeError,
    setSessionComposerErrors,
  });
  const clearSessionTransientUiState = useCallback(
    (sessionId: string) => {
      const normalizedSessionId = String(sessionId || "").trim();
      if (!normalizedSessionId) {
        return;
      }
      setActiveTurnLayersBySession((current) =>
        setActiveTurnLayerForSession(current, normalizedSessionId, undefined)
      );
      setSessionDrafts((current) => {
        const { [normalizedSessionId]: _removed, ...remaining } = current;
        return remaining;
      });
      setSessionImageAttachments((current) => clearSessionImageAttachments(current, normalizedSessionId));
      setSessionReferenceAttachments((current) => clearSessionReferenceAttachments(current, normalizedSessionId));
      delete imageUploadInFlightRef.current[normalizedSessionId];
      setSessionImageUploadPending((current) => {
        const { [normalizedSessionId]: _removed, ...remaining } = current;
        return remaining;
      });
      setSessionComposerErrors((current) => {
        const { [normalizedSessionId]: _removed, ...remaining } = current;
        return remaining;
      });
      void queryClient.cancelQueries({ queryKey: queryKeys.session(normalizedSessionId), exact: true });
      queryClient.removeQueries({ queryKey: queryKeys.session(normalizedSessionId), exact: true });
    },
    [queryClient],
  );
  const { selectDirectSessionMutation } = useChatSessionSelection({
    queryClient,
    chatWorkspaceCache,
    lang,
    describeError,
    syncSessionDetail,
    setSessionComposerErrors,
    latestDirectSessionSelectionRef,
    latestDirectSessionSelectionAtRef,
    directSessionSelectionGenerationRef,
    reselectDirectSessionRef,
    activeSessionId,
    setActiveSession,
    activeGroupRoomId,
    setActiveGroupRoomId,
    requestedSessionId,
    requestedRoomId,
    bootstrapActiveSessionId: activeSessionBootstrapQuery.data?.activeSessionId,
    sessions: sessionsQuery.data,
    setRightIndexPanel,
    setRightPaneCollapsed,
    setGroupRoomActionError,
  });
  const directSessionActiveSummary = useMemo(
    () => (activeSessionId ? sessionsQuery.data?.find((session) => session.id === activeSessionId) : undefined),
    [activeSessionId, sessionsQuery.data],
  );
  useEffect(() => {
    setGroupBackgroundSyncActive(Boolean(
      standardGroupRoomActive
      && isBusyPhase(activeGroupRoomQuery.data?.status),
    ));
  }, [activeGroupRoomQuery.data?.status, standardGroupRoomActive]);

  useEffect(() => {
    const pendingHandoff = loadPendingSelfEvolutionHandoff();
    if (!pendingHandoff || !sessionsQuery.data || sessionsQuery.data.length === 0) {
      return;
    }
    const matchedSession = sessionsQuery.data.find((item) => item.id === pendingHandoff.sessionId);
    const targetSessionId = matchedSession?.id || activeSessionId || sessionsQuery.data[0]?.id || "";
    if (!targetSessionId) {
      return;
    }
    if (activeSessionId !== targetSessionId) {
      setActiveSession(targetSessionId);
    }
    setSessionDrafts((current) => ({
      ...current,
      [targetSessionId]: pendingHandoff.content,
    }));
    setSessionComposerErrors((current) => ({
      ...current,
      [targetSessionId]: "",
    }));
    clearPendingSelfEvolutionHandoff();
  }, [activeSessionId, sessionsQuery.data, setActiveSession]);

  // Do not cancel foreign session detail queries on switch — that aborts in-flight
  // loads for recently visited tabs and forces empty provisional shells on return.
  // Clear stale composer errors for the newly selected session after a switch.
  useEffect(() => {
    const activeId = String(activeSessionId || "").trim();
    if (!activeId) {
      return;
    }
    setSessionComposerErrors((current) => {
      if (!current[activeId]) {
        return current;
      }
      return { ...current, [activeId]: "" };
    });
  }, [activeSessionId]);
  const {
    sessionDetailQuery,
    sessionLlmOptionsQuery,
    activeRootSessionId,
    childSessionsQuery,
  } = useChatWorkbenchSessionQueries({
    queryClient,
    activeSessionId: activeSessionId || "",
    secondaryChatDataEnabled,
    directSessionPanelActive,
    startupDetailSettledSessionId,
    chatLiveQueryPolicy,
    chatLiveQueryPolicyInput,
    sessions: sessionsQuery.data,
    directSessionActiveSummary,
  });
  useEffect(() => {
    if (!activeSessionId) {
      setStartupDetailSettledSessionId("");
      return;
    }
    if (
      sessionDetailQuery.isFetching
      || !sessionDetailQuery.data
      || sessionDetailQuery.data.id !== activeSessionId
    ) {
      return;
    }
    setStartupDetailSettledSessionId((current) => current === activeSessionId ? current : activeSessionId);
  }, [activeSessionId, sessionDetailQuery.data, sessionDetailQuery.isFetching]);
  useEffect(() => {
    if (
      !activeSessionId
      || !sessionsQuery.data
      || !sessionDetailQuery.isError
      || !isSessionNotFoundError(sessionDetailQuery.error)
    ) {
      return;
    }
    const nextActiveSessionId = sessionsQuery.data.find((session) => session.id !== activeSessionId)?.id || "";
    clearSessionTransientUiState(activeSessionId);
    forgetSessionDetailPaint(activeSessionId);
    removeSessionWorkspace(activeSessionId, nextActiveSessionId || null);
    if (nextActiveSessionId) {
      setActiveSession(nextActiveSessionId);
    }
    if (nextActiveSessionId) {
      setSessionComposerErrors((current) => ({
        ...current,
        [nextActiveSessionId]: "",
      }));
    }
    updateSessionSummaryCaches(queryClient, (sessions) =>
      sessions?.filter((session) => session.id !== activeSessionId),
    );
    queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations(), (conversations) =>
      removeDeletedSessionFromConversations(conversations, activeSessionId),
    );
    setGroupManageSessionIds((current) => current.filter((sessionId) => sessionId !== activeSessionId));
    if (requestedSessionId === activeSessionId) {
      const nextSearchParams = new URLSearchParams(location.search);
      if (nextActiveSessionId) {
        nextSearchParams.set("session", nextActiveSessionId);
      } else {
        nextSearchParams.delete("session");
      }
      const nextSearch = nextSearchParams.toString();
      navigate(`${location.pathname}${nextSearch ? `?${nextSearch}` : ""}`, { replace: true });
    }
    if (nextActiveSessionId) {
      void chatWorkspaceCache.refreshSessionRuntime(nextActiveSessionId);
    } else {
      void chatWorkspaceCache.refreshConversationIndex();
    }
  }, [
    activeSessionId,
    chatWorkspaceCache,
    clearSessionTransientUiState,
    queryClient,
    location.pathname,
    location.search,
    navigate,
    removeSessionWorkspace,
    requestedSessionId,
    sessionDetailQuery.error,
    sessionDetailQuery.isError,
    sessionsQuery.data,
    setActiveSession,
  ]);
  useEffect(() => {
    const directReady = Boolean(activeSessionId ? sessionDetailQuery.data : sessionsQuery.data);
    const groupReady = !standardGroupRoomActive || Boolean(activeGroupRoomQuery.data);
    if (sessionsQuery.data && directReady && groupReady) {
      setChatStartupDataReady(true);
    }
  }, [
    activeGroupRoomQuery.data,
    activeSessionId,
    standardGroupRoomActive,
    sessionDetailQuery.data,
    sessionsQuery.data,
  ]);
  useEffect(() => {
    if (!chatStartupDataReady || chatRouteStartupReadyLoggedRef.current) {
      return;
    }
    chatRouteStartupReadyLoggedRef.current = true;
    postBrowserTelemetry({
      phase: "navigation",
      eventCode: "browser.chat_route.startup_data_ready",
      message: "Chat route startup data is ready.",
      fields: {
        durationMs: Math.max(0, Date.now() - chatRouteMountStartedAtRef.current),
        activeSession: Boolean(activeSessionId),
        standardGroupRoomActive,
        runtimeReady: Boolean(runtimeQuery.data),
        sessionsReady: Boolean(sessionsQuery.data),
        conversationsReady: Boolean(conversationsQuery.data),
        teamsReady: Boolean(teamsQuery.data),
        sessionDetailReady: Boolean(activeSessionId ? sessionDetailQuery.data : true),
        groupRoomReady: Boolean(!standardGroupRoomActive || activeGroupRoomQuery.data),
      },
    });
  }, [
    activeGroupRoomQuery.data,
    activeSessionId,
    chatStartupDataReady,
    conversationsQuery.data,
    standardGroupRoomActive,
    runtimeQuery.data,
    sessionDetailQuery.data,
    sessionsQuery.data,
    teamsQuery.data,
  ]);
  useEffect(() => {
    setDirectSessionBackgroundSyncActive(Boolean(
      activeSessionId
      && directSessionPanelActive
      && isBusyPhase(sessionDetailQuery.data?.currentPhase || directSessionActiveSummary?.currentPhase || directSessionActiveSummary?.status),
    ));
  }, [
    activeSessionId,
    directSessionActiveSummary?.currentPhase,
    directSessionActiveSummary?.status,
    directSessionPanelActive,
    sessionDetailQuery.data?.currentPhase,
  ]);

  const {
    submitTurnMutation,
    editResubmitMutation,
    stopTurnMutation,
    sessionGuidanceMutation,
  } = useChatComposerTurnMutations({
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
  });

  const {
    createSessionMutation,
    createGroupRoomMutation,
    startGroupRoundMutation,
    stopGroupRoundMutation,
    sendProjectBusMessageMutation,
    revokeProjectBusMessageMutation,
    updateGroupRoomMutation,
    deleteGroupRoomMutation,
    resetGroupRoomMutation,
    deleteSessionMutation,
    clearSessionHistoryMutation,
    renameSessionMutation,
    addSessionToReviewMutation,
  } = useChatWorkspaceLifecycle({
    queryClient,
    chatWorkspaceCache,
    lang,
    t,
    describeError,
    syncSessionDetail,
    syncChatRoomDetail,
    clearSessionTransientUiState,
    removeSessionWorkspace,
    setActiveSession,
    activeGroupRoomId,
    setActiveGroupRoomId,
    setRightIndexPanel,
    setSelectedAgentId,
    setSessionFilter,
    setSessionComposerErrors,
    setGroupComposerOpen,
    setGroupTitleDraft,
    setGroupModeDraft,
    setGroupPurposeDraft,
    setGroupSelectedAgentIds,
    setGroupTopicDraft,
    setGroupRoomActionError,
    setGroupManageTitleDraft,
    setGroupManageSessionIds,
    setGroupManageModeDraft,
    setGroupManagePurposeDraft,
    setProjectBusDraft,
    editingSessionIdRef,
    setEditingSessionId,
    setEditingSessionTitle,
    suppressRenameBlurUntilRef,
  });

  const {
    renameAgentMutation,
    archiveAgentMutation,
  } = useChatAgentMutations({
    queryClient,
    chatWorkspaceCache,
    t,
    describeError,
    activeSessionId,
    selectedAgentId,
    sessions: sessionsQuery.data,
    sessionDetailAgentId: sessionDetailQuery.data?.agentId,
    setActiveSession,
    setSelectedAgentId,
    setAgentContextMenu,
    setSessionComposerErrors,
  });

  const {
    sessionReasoningEffortMutation,
    loadEarlierSessionMessagesMutation,
    resolveToolApprovalMutation,
    resolveSessionToolApprovalMutation,
    petActionMutation,
  } = useChatSessionDetailMutations({
    queryClient,
    chatWorkspaceCache,
    lang,
    describeError,
    activeSessionId,
    setSessionComposerErrors,
    setPetActionFeedback,
  });

  const activeGroupRoom = activeGroupRoomQuery.data;
  const teams = teamsQuery.data?.teams ?? [];
  const linkedTeamRoomIds = useMemo(() => {
    // Prefer explicit link fields; fall back to nested linkedChatRoom so valid team
    // rooms never land in 未归属群聊 when the flat id is briefly empty.
    const ids = new Set<string>();
    for (const team of teams) {
      const roomId = String(team.linkedChatRoomId || team.linkedChatRoom?.roomId || "").trim();
      if (roomId) {
        ids.add(roomId);
      }
    }
    return ids;
  }, [teams]);
  const activeGroupTeam = useMemo(() => {
    const roomId = String(activeGroupRoom?.roomId || activeGroupRoomId || "").trim();
    const configTeamId = String((activeGroupRoom?.config ?? {}).teamId ?? "").trim();
    return teams.find((team) => {
      const teamId = String(team.teamId ?? "").trim();
      const linkedRoomId = String(team.linkedChatRoomId ?? team.linkedChatRoom?.roomId ?? "").trim();
      return (configTeamId && teamId === configTeamId) || (roomId && linkedRoomId === roomId);
    }) ?? null;
  }, [activeGroupRoom?.config, activeGroupRoom?.roomId, activeGroupRoomId, teams]);
  const activeGroupTeamOwned = Boolean(activeGroupTeam);
  const availableGroupParticipants = useMemo(
    () => (activeGroupRoom?.participants ?? []).filter(isAvailableGroupParticipant),
    [activeGroupRoom?.participants],
  );
  const availableGroupParticipantCount = availableGroupParticipants.length;

  useEffect(() => {
    if (activeSessionId && sessionDetailQuery.data?.id === activeSessionId) {
      hydrateSession(activeSessionId, [], "agent");
    }
  }, [activeSessionId, hydrateSession, sessionDetailQuery.data?.id]);

  // C5: keep recent session ids warm (sticky paint + scroll memory lifetime ring).
  useEffect(() => {
    if (!activeSessionId) {
      return;
    }
    touchSessionKeepAlive(activeSessionId);
  }, [activeSessionId]);

  // T1: warm ConversationView after session intent is known (does not mount).
  useEffect(() => {
    if (!activeSessionId || groupPanelActive) {
      return;
    }
    let cancelled = false;
    const run = () => {
      if (!cancelled) {
        void prefetchConversationView();
      }
    };
    const idleRequest = (window as Window & {
      requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => number;
    }).requestIdleCallback;
    const handle = typeof idleRequest === "function"
      ? idleRequest(run, { timeout: 800 })
      : window.setTimeout(run, 120);
    return () => {
      cancelled = true;
      if (typeof idleRequest === "function") {
        (window as Window & { cancelIdleCallback?: (id: number) => void }).cancelIdleCallback?.(handle as number);
      } else {
        window.clearTimeout(handle as number);
      }
    };
  }, [activeSessionId, groupPanelActive]);

  // C: idle-prefetch a few neighbor session detail windows (Cursor list warm pattern).
  useEffect(() => {
    if (groupPanelActive || !sessionsQuery.data?.length) {
      return;
    }
    const neighborIds = resolveNeighborSessionIdsForPrefetch({
      sessions: sessionsQuery.data,
      activeSessionId,
    });
    if (!neighborIds.length) {
      return;
    }
    let cancelled = false;
    const run = () => {
      if (cancelled) {
        return;
      }
      for (const sessionId of neighborIds) {
        void prefetchSessionDetailWindow(queryClient, sessionId);
      }
    };
    const idleRequest = (window as Window & {
      requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => number;
    }).requestIdleCallback;
    const handle = typeof idleRequest === "function"
      ? idleRequest(run, { timeout: 1_500 })
      : window.setTimeout(run, 280);
    return () => {
      cancelled = true;
      if (typeof idleRequest === "function") {
        (window as Window & { cancelIdleCallback?: (id: number) => void }).cancelIdleCallback?.(handle as number);
      } else {
        window.clearTimeout(handle as number);
      }
    };
  }, [activeSessionId, groupPanelActive, queryClient, sessionsQuery.data]);

  useEffect(() => {
    if (!activeGroupRoom) {
      return;
    }
    const existingSessionIds = new Set((sessionsQuery.data ?? []).map((session) => session.id));
    setGroupManageSessionIds(
      activeGroupRoom.participants
        .map((participant) => participant.sessionId)
        .filter((sessionId) => existingSessionIds.has(sessionId)),
    );
    setGroupManageTitleDraft(activeGroupRoom.title || "");
    setGroupManageModeDraft(activeGroupRoom.mode || "round_robin");
    setGroupManagePurposeDraft(activeGroupRoom.purpose || "discussion");
  }, [activeGroupRoom, sessionsQuery.data]);


  const workspace = activeSessionId
    ? sessionWorkspaces[activeSessionId] ?? {
        openTabs: [],
        activeTab: "agent",
      }
    : { openTabs: [], activeTab: "agent" };

  const activeCliAgentRunId = cliAgentRunIdFromTabId(workspace.activeTab);
  const activeFilePath = workspace.activeTab !== "agent" && !activeCliAgentRunId ? workspace.activeTab : null;
  const fileContentQuery = useQuery({
    queryKey: queryKeys.fileContent(activeFilePath ?? ""),
    enabled: Boolean(activeFilePath),
    queryFn: () =>
      fetchJson<FileContent>(`/api/files/content?path=${encodeURIComponent(activeFilePath ?? "")}`),
  });

  const changedFiles = new Set(sessionDetailQuery.data?.changedFiles ?? []);

  const {
    locale,
    numberFormatter,
    compactNumberFormatter,
    formatTime,
    formatConversationIndexTime,
  } = useChatLocaleFormatters(lang);

  const runtime = runtimeQuery.data;
  const pet = petQuery.data;
  // Prefer live query data, but always re-read RQ cache for optimistic temp shells
  // (disabled queries often omit data even after setQueryData).
  const rawSessionDetail = resolveActiveSessionDetailForUi({
    activeSessionId,
    queryData: sessionDetailQuery.data,
    cachedDetail: queryClient.getQueryData<SessionDetail>(queryKeys.session(activeSessionId ?? "none")),
    summary: activeSessionId
      ? sessionsQuery.data?.find((session) => session.id === activeSessionId)
      : undefined,
  });
  // Codex/ChatGPT: paint sticky last-good transcript while provisional shell hydrates.
  const detail = resolveStickySessionDetailPaint({
    activeSessionId,
    detail: rawSessionDetail,
  });
  const sessionToolApprovalRuntimeActive = Boolean(
    activeSessionId
    && runtime?.workRuns?.active?.chat_turn?.sessionId === activeSessionId,
  );
  const sessionToolApprovalsQuery = useQuery<SessionToolApprovalRequest[]>({
    queryKey: queryKeys.sessionToolApprovals(activeSessionId ?? "none"),
    enabled: Boolean(activeSessionId && directSessionPanelActive && !isTempSessionId(activeSessionId)),
    queryFn: () => listPendingSessionToolApprovals(activeSessionId ?? ""),
    // Avoid 250ms thrash while busy (queues behind heavy session-detail under load).
    // Pending approvals still poll sub-second; busy-without-pending is lighter.
    refetchInterval: (query) => {
      if (!directSessionPanelActive) {
        return false;
      }
      const hasPending = (query.state.data?.length ?? 0) > 0;
      const busy = sessionToolApprovalRuntimeActive
        || isBusyPhase(detail?.currentPhase || directSessionActiveSummary?.currentPhase || directSessionActiveSummary?.status);
      if (hasPending) {
        return 750;
      }
      if (busy) {
        return 2_000;
      }
      return 4_000;
    },
    refetchIntervalInBackground: false,
  });
  const handleLoadEarlierSessionMessages = useCallback(() => {
    const beforeMessageIndex = detail?.messageWindow?.nextBeforeMessageIndex ?? 0;
    if (
      !activeSessionId
      || !detail?.messageWindow?.hasEarlier
      || !beforeMessageIndex
      || loadEarlierSessionMessagesMutation.isPending
    ) {
      return;
    }
    loadEarlierSessionMessagesMutation.mutate({
      sessionId: activeSessionId,
      beforeMessageIndex,
    });
  }, [
    activeSessionId,
    detail?.messageWindow?.hasEarlier,
    detail?.messageWindow?.nextBeforeMessageIndex,
    loadEarlierSessionMessagesMutation,
  ]);
  const activeTurnLayer = activeSessionId ? activeTurnLayersBySession[activeSessionId] : undefined;
  const activeTurnSettledByDetail = isActiveTurnSettledByDetail(activeTurnLayer, detail);
  const activeTurnMessage = useMemo(
    () => activeTurnSettledByDetail ? undefined : activeTurnLayerToConversationMessage(activeTurnLayer),
    [activeTurnLayer, activeTurnSettledByDetail],
  );
  useEffect(() => {
    if (!activeSessionId || !activeTurnLayer || !activeTurnSettledByDetail || !detail) {
      return;
    }
    const settledTurnId = activeTurnLayer.turnId;
    setActiveTurnLayersBySession((current) => {
      const currentLayer = current[activeSessionId];
      if (!isActiveTurnSettledByDetail(currentLayer, detail)) {
        return current;
      }
      return setActiveTurnLayerForSession(current, activeSessionId, undefined);
    });
    postBrowserTelemetry({
      phase: "session_stream",
      eventCode: "browser.session_stream.active_layer_reconciled",
      message: "Active turn layer was cleared after authoritative session detail committed the turn.",
      level: "info",
      fields: {
        sessionId: activeSessionId,
        turnId: settledTurnId,
        source: "session_detail_query",
        ledgerSeq: detail.ledgerSeq ?? 0,
      },
    });
  }, [activeSessionId, activeTurnLayer, activeTurnSettledByDetail, detail]);
  const handleConversationStreamingFramePaint = useCallback((metrics: ConversationStreamingFramePaintMetrics) => {
    const sessionId = String(metrics.sessionId || "").trim();
    if (!sessionId || sessionId !== activeSessionId) {
      return;
    }
    const now = Date.now();
    const lastLoggedAt = lastConversationStreamingFrameTelemetryAtRef.current[sessionId] ?? 0;
    if (now - lastLoggedAt < 1_000) {
      return;
    }
    const paintedAtMs = metrics.paintedAtMs || chatStreamPerformanceNowMs();
    const lastAssistantDeltaAppliedAtMs = lastAssistantDeltaAppliedAtRef.current[sessionId] ?? 0;
    const paintedActiveTurn = activeTurnLayersBySessionRef.current[sessionId];
    lastConversationStreamingFrameTelemetryAtRef.current = {
      ...lastConversationStreamingFrameTelemetryAtRef.current,
      [sessionId]: now,
    };
    postBrowserTelemetry({
      phase: "conversation_stream",
      eventCode: "browser.conversation_stream.frame_painted",
      message: "Conversation streaming frame was committed by the conversation view.",
      level: "info",
      fields: {
        sessionId,
        turnId: paintedActiveTurn?.turnId ?? "",
        streamingMessageCount: metrics.streamingMessageCount,
        renderedTextLength: metrics.renderedTextLength,
        scrollSignalLength: metrics.scrollSignal.length,
        activeTurnTextLength: activeTurnLayerTextLength(paintedActiveTurn),
        paintedAtMs: Math.round(paintedAtMs),
        lastAssistantDeltaAppliedAtMs: Math.round(lastAssistantDeltaAppliedAtMs),
        applyToPaintMs: lastAssistantDeltaAppliedAtMs
          ? Math.max(0, Math.round(paintedAtMs - lastAssistantDeltaAppliedAtMs))
          : 0,
      },
    });
  }, [activeSessionId]);
  const {
    cliAgentRunTabs,
    activeCliAgentRun,
    mountedCliAgentRuns,
    handleCliAgentTerminalSessionChange,
    closeCliAgentRun,
  } = useChatCliAgentTerminal({
    activeSessionId,
    activeCliAgentRunId,
    groupPanelActive,
    detailMessages: detail?.messages,
    lang,
    describeError,
    setActiveTab,
    refetchSessionDetail: () => sessionDetailQuery.refetch(),
  });
  const sessionDetailLoadingForActiveSession = isSessionDetailHardLoading({
    activeSessionId,
    detail: rawSessionDetail,
    isFetching: sessionDetailQuery.isFetching,
    isTempSession: isTempSessionId(activeSessionId),
  });
  const sessionTranscriptPending = shouldShowStickyTranscriptPending({
    activeSessionId,
    paintDetail: detail,
    liveDetail: rawSessionDetail,
    isFetching: sessionDetailQuery.isFetching,
    isTempSession: isTempSessionId(activeSessionId),
  });
  const runtimeActiveChatTurnSessionIds = new Set(
    [
      ...(runtime?.workRuns?.activeItems?.chat_turn ?? []),
      runtime?.workRuns?.active?.chat_turn,
    ]
      .map((run) => String(run?.sessionId ?? "").trim())
      .filter(Boolean),
  );
  const runtimeMatchesSelectedSession = runtimeMatchesSelectedChatSession({
    selectedSessionId: activeSessionId,
    activeRuntimeSessionId: activeSessionBootstrapQuery.data?.activeSessionId,
    activeWorkSessionIds: runtimeActiveChatTurnSessionIds,
  });
  const runtimeActiveChatTurnSessionId = runtimeActiveChatTurnSessionIds.values().next().value ?? "";
  const runtimeActiveSessionLabel = runtimeActiveChatTurnSessionId
    ? sessionsQuery.data?.find((session) => session.id === runtimeActiveChatTurnSessionId)?.title
      || runtime?.sessionTitle
      || runtimeActiveChatTurnSessionId
    : "";
  const runtimeMismatchLine = runtimeActiveChatTurnSessionId && !runtimeMatchesSelectedSession
    ? (lang === "zh"
      ? `运行器正在处理：${runtimeActiveSessionLabel}`
      : `Runtime is processing: ${runtimeActiveSessionLabel}`)
    : "";
  const lastContextComposition = detail?.lastContextComposition ?? null;
  const lastCacheComposition = detail?.lastCacheComposition ?? null;
  const lastLlmPayloadTrace = detail?.lastLlmPayloadTrace ?? null;
  const {
    activeSkillCommand,
    activeSkillName,
    activeSkillStatus,
    activeSkillStatusLabel,
    activeSkillShortHash,
    activeSkillSummary,
    activeSkillTitle,
    hasActiveSkill,
  } = buildChatActiveSkillViewModel({
    contract: (detail as SessionDetailWithActiveSkill | undefined)?.activeSkillContract,
    lang,
    numberFormatter,
    formatTime,
  });
  const activeSkillStatusStyle = activeSkillStatus === "stale"
    ? styles.activeSkillStatus_stale
    : activeSkillStatus === "missing"
      ? styles.activeSkillStatus_missing
      : styles.activeSkillStatus_active;
  const projectBusTimeline = projectAgentBusQuery.data;
  const projectBusEvents = projectBusTimeline?.events ?? [];
  const activeGroupRound = latestChatRoomRound(activeGroupRoom);
  const activeGroupRoomStatus = String(activeGroupRoom?.status ?? "").trim().toLowerCase();
  const groupRoundRunning = activeGroupRoomStatus === "running";
  const groupRoundStopping = activeGroupRoomStatus === "stopping";
  const groupRoundActive = groupRoundRunning || groupRoundStopping;
  const activeGroupParticipantById = useMemo(() => {
    const entries = (activeGroupRoom?.participants ?? []).map((participant) => [participant.participantId, participant] as const);
    return new Map(entries);
  }, [activeGroupRoom?.participants]);
  const groupManageSessionSet = useMemo(() => new Set(groupManageSessionIds), [groupManageSessionIds]);
  const activeGroupParticipantSessionSet = useMemo(
    () => new Set(availableGroupParticipants.map((participant) => participant.sessionId)),
    [availableGroupParticipants],
  );
  const expandedGroupAgentDetailsBySessionId = useMemo(() => {
    const entries = expandedGroupAgentSessionIds.map((sessionId, index) => {
      const query = expandedGroupAgentDetailQueries[index];
      return [sessionId, query] as const;
    });
    return new Map(entries);
  }, [expandedGroupAgentDetailQueries, expandedGroupAgentSessionIds]);
  useEffect(() => {
    if (!groupPanelActive) {
      if (expandedGroupAgentSessionIds.length) {
        setExpandedGroupAgentSessionIds([]);
      }
      return;
    }
    const nextExpanded = expandedGroupAgentSessionIds.filter((sessionId) => activeGroupParticipantSessionSet.has(sessionId));
    if (nextExpanded.length !== expandedGroupAgentSessionIds.length) {
      setExpandedGroupAgentSessionIds(nextExpanded);
    }
  }, [activeGroupParticipantSessionSet, expandedGroupAgentSessionIds, groupPanelActive]);
  const groupManageChanged = Boolean(
    standardGroupRoomActive
    &&
    activeGroupRoom
    && (
      groupManageTitleDraft.trim() !== (activeGroupRoom.title || "").trim()
      || groupManageModeDraft !== (activeGroupRoom.mode || "round_robin")
      || groupManagePurposeDraft !== (activeGroupRoom.purpose || "discussion")
      || groupManageSessionIds.length !== activeGroupParticipantSessionSet.size
      || groupManageSessionIds.some((sessionId) => !activeGroupParticipantSessionSet.has(sessionId))
    ),
  );
  const groupManageDisabled =
    !standardGroupRoomActive
    ||
    !activeGroupRoom
    || activeGroupTeamOwned
    || groupRoundActive
    || updateGroupRoomMutation.isPending
    || !groupManageTitleDraft.trim()
    || groupManageSessionIds.length < 2
    || !groupManageModeDraft
    || !groupManagePurposeDraft;
  const groupDeleteDisabled =
    !standardGroupRoomActive
    ||
    !activeGroupRoom
    || activeGroupTeamOwned
    || groupRoundActive
    || deleteGroupRoomMutation.isPending;
  const groupResetDisabled =
    !standardGroupRoomActive
    ||
    !activeGroupRoom
    || groupRoundActive
    || resetGroupRoomMutation.isPending
    || (activeGroupRoom?.rounds ?? []).length < 1;
  const groupStopDisabled =
    !standardGroupRoomActive
    || !activeGroupRoom
    || !groupRoundRunning
    || stopGroupRoundMutation.isPending;
  const sessionDetailErrorState = deriveSessionDetailQueryErrorState(detail, sessionDetailQuery.isError, {
    dataUpdatedAt: sessionDetailQuery.dataUpdatedAt,
    errorUpdatedAt: sessionDetailQuery.errorUpdatedAt,
    streamConnected: sessionStreamConnected,
  });
  const sessionsErrorState = deriveSessionListQueryErrorState(sessionsQuery.data, sessionsQuery.isError, {
    emptyNotFoundAsEmpty: true,
    error: sessionsQuery.error,
  });
  const sessionDetailErrorMessage = sessionDetailQuery.isError
    ? describeError(sessionDetailQuery.error, t("loadFailed"))
    : "";
  const invalidChildSessionLinkMessage = hasInvalidChildSessionLink(sessionDetailQuery.data ?? directSessionActiveSummary)
    ? (
      lang === "zh"
        ? "child_session_link_invalid: 子对话缺少 parentSessionId/rootSessionId，无法挂载到顶部 Agent 会话轨道。本轮已停止展示，请修复会话索引数据。"
        : "child_session_link_invalid: child session is missing parentSessionId/rootSessionId and cannot be mounted in the top Agent session strip. Fix the session index data."
    )
    : "";
  const sessionsErrorMessage = sessionsQuery.isError
    ? describeError(sessionsQuery.error, t("loadFailed"))
    : "";
  const cacheDetailViewModel = useMemo(
    () => buildChatCacheDetailViewModel({
      detail,
      lastCacheComposition,
      lastCacheDiagnostics: lastCacheComposition,
      lang,
      t,
      numberFormatter,
    }),
    [detail, lang, lastCacheComposition, numberFormatter, t],
  );
  const {
    providerCacheInputTokens,
    providerCachedInputTokens,
    cacheCalibrationReason,
    cacheComputedOverestimatedInputTokens,
    cacheProviderExtraCachedInputTokens,
    cacheCalibrationSummaryText,
    trueCacheDonutSegments,
    upperBoundCacheInputTokens,
    upperBoundCachedInputTokens,
    upperBoundCacheCompositionPercent,
    cachePromptCompositionTotalTokens,
    cachePromptDonutSegments,
    cacheCompositionPercent,
    averageCacheObservedTurnCount,
    cacheCompositionAverageValue,
    cacheDetailAvailable,
    cacheDetailDialogTitle,
    cacheDetailOpenLabel,
    cacheCompositionSummary,
    cacheCompositionTitle,
    cacheCompositionUpperBoundLabel,
    cacheCompositionAverageLabel,
  } = cacheDetailViewModel;
  const {
    cacheDetailOpen,
    openCacheDetail,
    closeCacheDetail,
  } = useChatCacheDetailDialog({
    cacheDetailAvailable,
    activeSessionId,
  });
  const pendingToolGovernanceApproval = useMemo(
    () => (detail?.pendingToolGovernanceRequests ?? []).find((request) => request.status === "pending_review") ?? null,
    [detail?.pendingToolGovernanceRequests],
  );
  const pendingSessionToolApproval = useMemo(
    () => (sessionToolApprovalsQuery.data ?? []).find((request) => request.status === "pending") ?? null,
    [sessionToolApprovalsQuery.data],
  );
  const sessionIdsNeedingApproval = useMemo(
    () => (
      activeSessionId
      && (pendingSessionToolApproval || pendingToolGovernanceApproval)
        ? [activeSessionId]
        : []
    ),
    [activeSessionId, pendingSessionToolApproval, pendingToolGovernanceApproval],
  );
  const runtimeRunningSessionIds = useMemo(
    () => collectRuntimeRunningSessionIds({
      activeChatTurnSessionId: runtime?.workRuns?.active?.chat_turn?.sessionId,
      activeChatTurnItems: runtime?.workRuns?.activeItems?.chat_turn,
    }),
    [runtime?.workRuns?.active?.chat_turn, runtime?.workRuns?.activeItems?.chat_turn],
  );
  const pendingToolApprovalLabels = useMemo(
    () => pendingSessionToolApproval
      ? [{
        id: pendingSessionToolApproval.toolName,
        label: toolApprovalDisplayName(pendingSessionToolApproval.toolName, lang),
      }]
      : toolApprovalLabels(pendingToolGovernanceApproval),
    [lang, pendingSessionToolApproval, pendingToolGovernanceApproval],
  );
  const pendingToolApprovalRawTitle = pendingToolApprovalLabels.map((item) => item.id).join("、");
  const pendingToolApprovalActionPreview = pendingSessionToolApproval
    ? toolApprovalActionPreview(pendingSessionToolApproval.argumentSummary, pendingSessionToolApproval.toolName)
    : pendingToolApprovalLabels.map((item) => item.label).join(" · ");
  const pendingToolApprovalScope = pendingSessionToolApproval
    ? (lang === "zh" ? "本次调用" : "this call")
    : toolApprovalScopeLabel(pendingToolGovernanceApproval?.grantScope, lang);
  const pendingToolApprovalRisk = toolApprovalRiskLabel(
    pendingSessionToolApproval?.risk ?? pendingToolGovernanceApproval?.riskLevel,
    lang,
  );
  const pendingToolApprovalPending = Boolean(
    pendingSessionToolApproval
      ? (
        resolveSessionToolApprovalMutation.isPending
        && resolveSessionToolApprovalMutation.variables?.request.requestId === pendingSessionToolApproval.requestId
      )
      : (
        pendingToolGovernanceApproval
        && resolveToolApprovalMutation.isPending
        && resolveToolApprovalMutation.variables?.request.requestId === pendingToolGovernanceApproval.requestId
      ),
  );
  const activeDraft = activeSessionId ? sessionDrafts[activeSessionId] ?? "" : "";
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
  const activeSessionAgent = activeAgentId ? (agentsQuery.data ?? []).find((agent) => agent.agentId === activeAgentId) : undefined;
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
  const activeAgentDisplay = detail
    ? sessionAgentDisplayInfo(detail, activeSessionAgent, lang, resolveModelLabel)
    : { name: pet?.name || "Agent", functionLabel: "", tone: "chat" as const, meta: "" };
  const activeAgentDisplayName = activeAgentDisplay.name;
  const activeAgentAvatarImageUrl = avatarImageUrlFrom(activeSessionAgent, detail);
  const activeAgentAvatarFallback = avatarInitials(detail?.agentCode, activeAgentDisplayName);
  const activeAgentStatusMessage = detail?.agentMissing
    ? detail.agentStatusMessage || (lang === "zh" ? "缺少有效 Agent，部分内容无法继续运行。" : "Missing valid Agent. Some content cannot keep running.")
    : "";
  const activeRuntimeNotices = useMemo<SessionRuntimeNotice[]>(() => {
    return (detail?.runtimeNotices ?? [])
      .filter((notice) => String(notice.message ?? "").trim())
      .slice(-1);
  }, [detail?.runtimeNotices]);
  const activeControlSignals = useMemo<ChatNextStateSignalSummary[]>(() => {
    const phase = detail?.currentPhase || directSessionActiveSummary?.currentPhase || directSessionActiveSummary?.status || "";
    return (detail?.nextStateSignals ?? [])
      .filter((signal) => shouldShowNextStateSignalInConversation(signal, phase, detail?.messages ?? []))
      .slice(-3)
      .reverse();
  }, [
    detail?.currentPhase,
    detail?.messages,
    detail?.nextStateSignals,
    directSessionActiveSummary?.currentPhase,
    directSessionActiveSummary?.status,
  ]);
  const latestControlSignal = activeControlSignals[0] ?? null;
  const latestControlSignalSummary = latestControlSignal?.summary?.trim() ?? "";
  const latestControlSignalKindLabel = (() => {
    if (!latestControlSignal) {
      return "";
    }
    const lowerSummary = latestControlSignalSummary.toLowerCase();
    const lowerKind = String(latestControlSignal.kind ?? "").toLowerCase();
    if (lowerSummary.includes("tool failed") || lowerKind.includes("tool")) {
      return lang === "zh" ? "工具失败" : "Tool failed";
    }
    if (lowerSummary.includes("provider") || lowerKind.includes("provider")) {
      return lang === "zh" ? "模型通道" : "Provider";
    }
    if (lowerSummary.includes("interrupt") || lowerKind.includes("interrupt")) {
      return lang === "zh" ? "已中断" : "Interrupted";
    }
    return latestControlSignalSummary || latestControlSignal.kind || "";
  })();
  const latestControlSignalLine = latestControlSignal
    ? activeControlSignals.length > 1
      ? `${latestControlSignalKindLabel} ${numberFormatter.format(activeControlSignals.length)}`
      : latestControlSignalKindLabel
    : "";
  const latestControlSignalTitle = latestControlSignal
    ? [
      t("nextStateSignalsLabel"),
      latestControlSignal.kind,
      latestControlSignal.source,
      latestControlSignal.relatedEventCode,
      latestControlSignal.turnId,
      latestControlSignal.createdAt ? formatTime(latestControlSignal.createdAt) : "",
      latestControlSignal.summary,
    ].filter(Boolean).join(" · ")
    : "";
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
    // Canonical terminalReason values (mature-agent style explicit stop).
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
  // When the turn is already terminal and no live activeTurn remains, do not
  // keep the stop button solely because phase/work-run lag behind.
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

  const {
    handleSubmitTurn,
    handleStopTurn,
    handleSubmitGuidance,
    handleEditUserMessage,
    handleCancelEditMessage,
    handleComposerChange,
    handleMentalModelEnabledChange,
    handleRuntimeStatusEnabledChange,
    handleAddComposerAttachments,
    handleRemoveComposerAttachment,
    handleAddComposerReference,
    handleRemoveComposerReference,
  } = useChatComposerSubmitActions({
    queryClient,
    lang,
    describeError,
    submitTurnMutation,
    editResubmitMutation,
    stopTurnMutation,
    sessionGuidanceMutation,
    setSessionDrafts,
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
    activePhase: detail?.currentPhase,
    activeAgentImageInputUnsupported,
    activeImageInputModelId,
    latestUserMessageId,
    activeTurnId: activeTurnLayer?.turnId,
    detail,
    setMentalModelEnabledForNextTurn,
    setRuntimeStatusEnabledForNextTurn,
  });
  const sessionLlmOptions = sessionLlmOptionsQuery.data;
  const sessionLlmControl = activeSessionId && sessionLlmOptions?.model ? {
    model: sessionLlmOptions.model,
    sessionId: activeSessionId,
    currentReasoningEffort: sessionLlmOptions?.currentReasoningEffort || detail?.reasoningEffort || "",
    // Do not allow switching effort while options failed/loading for this session.
    disabled: (
      sessionBusy
      || sessionLlmOptionsQuery.isLoading
      || sessionLlmOptionsQuery.isError
      || !sessionLlmOptions?.model
    ),
    pending: sessionReasoningEffortMutation.isPending,
    onReasoningEffortChange: (reasoningEffort: string) => {
      if (!activeSessionId || sessionLlmOptionsQuery.isError) {
        return;
      }
      sessionReasoningEffortMutation.mutate({
        sessionId: activeSessionId,
        reasoningEffort,
      });
    },
  } : undefined;

  useEffect(() => {
    if (!activeSessionId || !activeAgentImageInputUnsupported || !activeImageAttachments.length) {
      return;
    }
    setSessionImageAttachments((current) => clearSessionImageAttachments(current, activeSessionId));
  }, [activeAgentImageInputUnsupported, activeImageAttachments.length, activeSessionId]);


  const {
    petVitals,
    petPresetLabel,
    petAvatarPresetKey,
    petAvatarSymbol,
    petCompactLine,
    petInteractionLabels,
  } = buildChatPetCompanionViewModel({
    pet,
    petQueryError: petQuery.isError,
    petQueryErrorMessage: describeError(petQuery.error, t("loadFailed")),
    petActionPending: petActionMutation.isPending,
    lang,
    t,
    numberFormatter,
  });
  const petAvatarSkinStyle = styles[`petShowcaseAvatar_${petAvatarPresetKey}`] ?? styles.petShowcaseAvatar_default;
  const compression = runtimeMatchesSelectedSession ? runtime?.contextCompression : undefined;
  const {
    activeSurfaceTitle,
    sessionStateLabel,
    sessionStateLine,
    compactSessionStateLine,
    sessionStateValue,
    agentDirectSessionMismatch,
    agentPrimaryDirectSessionId,
    sessionBindingMismatchLine,
    currentTaskSummary,
    sessionCompactRows,
  } = buildChatSessionStateViewModel({
    lang,
    t,
    statusLabel,
    groupPanelActive,
    projectBusActive,
    activeSessionId,
    activeGroupRoomTitle: activeGroupRoom?.title,
    activeGroupRoomStatus: activeGroupRoom?.status,
    activeGroupRoomMode: activeGroupRoom?.mode,
    activeGroupRoomPurpose: activeGroupRoom?.purpose,
    activeGroupRoundSummary: activeGroupRound?.summary,
    availableGroupParticipantCount,
    projectBusActiveAgentCount: projectBusTimeline?.activeAgentCount ?? 0,
    detail,
    directSessionActiveSummary,
    runtimeMatchesSelectedSession,
    runtimeSessionState: runtime?.sessionState,
    runtimeSessionStateLine: runtime?.sessionStateLine,
    runtimeTaskSummary: runtime?.taskSummary,
    runtimeDefaultRoute: runtime?.defaultRoute,
    runtimeMismatchLine,
    sessionDetailBlockingError: sessionDetailErrorState.blockingError,
    sessionDetailErrorMessage,
    sessionDetailLoadingForActiveSession,
    activeAgentStatusMessage,
    latestControlSignalLine,
    latestControlSignalTitle,
    hasLatestControlSignal: Boolean(latestControlSignal),
  });
  useEffect(() => {
    const sample = groupPanelActive
      ? null
      : tokenSpeedSampleFromMessages(
        detail?.id ?? activeSessionId,
        detail?.messages,
        sessionStateValue,
        Date.now(),
      );
    setTokenSpeedTracker((previous) => updateTokenSpeedTracker(previous, sample));
  }, [activeSessionId, detail?.id, detail?.messages, groupPanelActive, sessionStateValue]);
  const { tokenStatusMetrics } = useMemo(
    () => buildChatTokenStatusViewModel({
      detail,
      lastCacheComposition,
      lastContextComposition,
      compression,
      runtimeMatchesSelectedSession,
      cache: {
        cacheDetailAvailable,
        cacheCompositionPercent,
        providerCachedInputTokens,
        providerCacheInputTokens,
        cacheCompositionSummary,
        cacheDetailOpenLabel,
        cacheCompositionTitle,
      },
      tokenSpeedTracker,
      activeSessionId,
      groupPanelActive,
      sessionStateValue,
      sessionStateLabel,
      sessionStateLine,
      lang,
      t,
      numberFormatter,
      compactNumberFormatter,
      locale,
      formatTime,
    }),
    [
      activeSessionId,
      cacheCompositionPercent,
      cacheCompositionSummary,
      cacheCompositionTitle,
      cacheDetailAvailable,
      cacheDetailOpenLabel,
      compactNumberFormatter,
      compression,
      detail,
      groupPanelActive,
      lang,
      lastCacheComposition,
      lastContextComposition,
      locale,
      numberFormatter,
      providerCacheInputTokens,
      providerCachedInputTokens,
      runtimeMatchesSelectedSession,
      sessionStateLabel,
      sessionStateLine,
      sessionStateValue,
      t,
      tokenSpeedTracker,
    ],
  );
  const {
    mental,
    mentalCognitiveStateValue,
    mentalCognitiveStateLabel,
    mentalSourceLabel,
    mentalStateLabel,
    mentalSummary,
    mentalWhisper,
    mentalConfidence,
    mentalRelativeTime,
    mentalCompactLine,
  } = buildChatMentalStateViewModel({
    // Prefer the selected session's last assistant snapshot over global runtime mood.
    mental: latestMentalSnapshot(detail?.messages) ?? runtime?.mentalState,
    lang,
    t,
    locale,
  });

  const agentsById = useMemo(() => {
    return new Map((agentsQuery.data ?? []).map((agent) => [agent.agentId, agent]));
  }, [agentsQuery.data]);

  const agentsByCode = useMemo(() => {
    const map = new Map<string, AgentInstance>();
    for (const agent of agentsQuery.data ?? []) {
      const code = String(agent.agentCode ?? "").trim();
      if (code) {
        map.set(code, agent);
      }
    }
    return map;
  }, [agentsQuery.data]);

  const resolveConversationTurnAvatar = useCallback((message: ConversationMessage): TurnAvatarResolution | undefined => {
    if (!isAgentInboxMessage(message)) {
      return undefined;
    }
    const metadata = message.metadata;
    const sourceAgentId = conversationMetadataText(metadata, "sourceAgentId");
    const sourceAgentCode = conversationMetadataText(metadata, "sourceAgentCode");
    const sourceAgentName = conversationMetadataText(metadata, "sourceAgentName");
    const agent =
      (sourceAgentId ? agentsById.get(sourceAgentId) : undefined)
      ?? (sourceAgentCode ? agentsByCode.get(sourceAgentCode) : undefined);
    return {
      imageUrl: avatarImageUrlFrom(agent),
      fallback: avatarInitials(sourceAgentCode, sourceAgentName),
    };
  }, [agentsByCode, agentsById]);

  const chatMentionTargets = useMemo(() => {
    return buildChatMentionTargets(agentsQuery.data ?? []);
  }, [agentsQuery.data]);

  const allVisibleSessions = useMemo(
    () => mergeVisibleDirectSessions(sessionsQuery.data, childSessionsQuery.data),
    [childSessionsQuery.data, sessionsQuery.data],
  );

  const sessionsById = useMemo(
    () => buildSessionsByIdMap(allVisibleSessions),
    [allVisibleSessions],
  );

  // Mark completed/unread activity as seen when the operator opens the session.
  // Blue dots clear after read; a later stamp (new turn) can show them again.
  useEffect(() => {
    if (!activeSessionId) {
      return;
    }
    const session =
      sessionsById.get(activeSessionId)
      || directSessionActiveSummary
      || (detail?.id === activeSessionId ? detail : undefined);
    if (!session) {
      return;
    }
    const stamp = sessionActivityStamp({
      id: activeSessionId,
      updatedAt: session.updatedAt,
      lastActive: session.lastActive,
      lastTurnStatus: session.lastTurnStatus,
    });
    if (!stamp) {
      return;
    }
    markSessionActivitySeen(activeSessionId, stamp);
  }, [
    activeSessionId,
    detail,
    directSessionActiveSummary,
    sessionsById,
  ]);

  const visibleChatAgents = useMemo(() => {
    return visibleDirectoryAgents(agentsQuery.data ?? [], allVisibleSessions);
  }, [agentsQuery.data, allVisibleSessions]);
  const activeSessionAgentId = useMemo(
    () => resolveActiveSessionAgentId({
      detailAgentId: sessionDetailQuery.data?.agentId,
      summaryAgentId: directSessionActiveSummary?.agentId,
      activeSessionId: activeSessionId || "",
      sessionsById,
    }),
    [activeSessionId, directSessionActiveSummary?.agentId, sessionDetailQuery.data?.agentId, sessionsById],
  );
  useEffect(() => {
    if (!activeSessionAgentId) {
      return;
    }
    setSelectedAgentId((current) => (
      current === activeSessionAgentId ? current : activeSessionAgentId
    ));
  }, [activeSessionAgentId]);
  const selectedChatAgentId = selectedAgentId || activeSessionAgentId || visibleChatAgents[0]?.agentId || "";
  const selectedAgentSessionsQuery = useQuery({
    queryKey: ["sessions", "agent", selectedChatAgentId],
    queryFn: () => fetchJson<SessionQueryResponse>(
      `/api/sessions/query?agentId=${encodeURIComponent(selectedChatAgentId)}&limit=100`,
    ),
    enabled: secondaryChatDataEnabled && Boolean(selectedChatAgentId),
    refetchInterval: chatLiveQueryPolicy.sessionsRefetchInterval,
    refetchIntervalInBackground: chatLiveQueryPolicy.directRefetchIntervalInBackground,
  });

  const contextMenuSession = useMemo(() => {
    if (!sessionContextMenu) {
      return undefined;
    }
    return sessionsById.get(sessionContextMenu.sessionId) ?? sessionContextMenu.session;
  }, [sessionContextMenu, sessionsById]);
  const contextMenuSessionId = sessionContextMenu?.sessionId ?? "";

  const rightIndexSessions = useMemo(() => {
    return allVisibleSessions.filter((session) => !isRepresentedInAgentSessionTabs(session));
  }, [allVisibleSessions]);

  const selectedAgentVisibleSessions = useMemo(
    () => filterSessionsForSelectedAgent(allVisibleSessions, selectedChatAgentId),
    [allVisibleSessions, selectedChatAgentId],
  );

  const agentSessionTabs = useMemo(
    () => buildAgentSessionTabs({
      sessions: [...(selectedAgentSessionsQuery.data?.items ?? []), ...selectedAgentVisibleSessions],
      selectedChatAgentDirectSessionId: agentsById.get(selectedChatAgentId)?.directSessionId,
    }),
    [agentsById, selectedAgentSessionsQuery.data?.items, selectedAgentVisibleSessions, selectedChatAgentId],
  );

  const groupCandidateAgents = useMemo(() => {
    return (agentsQuery.data ?? []).filter((agent) => {
      return (
        String(agent.kind ?? "").trim() === "persistent"
        && String(agent.status ?? "").trim() !== "archived"
        && String(agent.directSessionId ?? "").trim()
      );
    });
  }, [agentsQuery.data]);

  const readyChatRoomModes = useMemo(() => {
    const modes = (chatRoomModesQuery.data ?? []).filter((mode) => String(mode.status ?? "").trim() === "ready");
    return modes.length ? modes : [{ id: "round_robin", label: "Round robin", status: "ready" }];
  }, [chatRoomModesQuery.data]);
  const availableChatRoomPurposes = useMemo(() => {
    const purposes = chatRoomPurposesQuery.data ?? [];
    return purposes.length
      ? purposes
      : [
          { id: "chat", label: "Chat", description: "" },
          { id: "discussion", label: "Discussion", description: "" },
          { id: "meeting", label: "Meeting", description: "" },
          { id: "medical_triage", label: "Medical triage", description: "" },
        ];
  }, [chatRoomPurposesQuery.data]);

  const activeGroupTeamMemberByAgentId = useMemo(() => {
    return new Map(
      (activeGroupTeam?.members ?? [])
        .map((member) => [String(member.agentId ?? "").trim(), member] as const)
        .filter(([agentId]) => Boolean(agentId)),
    );
  }, [activeGroupTeam?.members]);
  const groupParticipantIdentity = useCallback(
    (
      participant: ChatRoomParticipant | undefined,
      fallback: { agentId?: string; agentCode?: string; title?: string; participantId?: string; agentAvatarImageUrl?: string } = {},
    ) => {
      const agentId = String(participant?.agentId || fallback.agentId || "").trim();
      const participantLike = participant ?? {
        participantId: String(fallback.participantId || agentId || "agent").trim(),
        kind: "session_agent",
        agentId,
        agentCode: String(fallback.agentCode || "").trim(),
        agentAvatarImageUrl: String(fallback.agentAvatarImageUrl || "").trim(),
        sessionId: "",
        title: String(fallback.title || fallback.participantId || agentId || "Agent").trim(),
        enabled: true,
        status: "",
      };
      const participantAgent = agentId ? agentsById.get(agentId) : undefined;
      const display = participantAgentDisplayInfo(participantLike, participantAgent, lang, resolveModelLabel);
      const member = agentId ? activeGroupTeamMemberByAgentId.get(agentId) : undefined;
      const participantTeamRole = String(participant?.teamMemberPurpose || participant?.teamRole || "").trim();
      const role = String(participantTeamRole || member?.purpose || member?.role || display.functionLabel || "").trim();
      const name = String(display.name || fallback.title || fallback.participantId || "Agent").trim();
      const compactRole = compactAgentRoleLabel(role || display.functionLabel);
      return {
        ...display,
        name,
        functionLabel: role || display.functionLabel,
        compactRole,
        avatarImageUrl: avatarImageUrlFrom(participantAgent, participantLike, fallback),
        identityLabel: formatAgentIdentityWithRole(name, compactRole, fallback.participantId || "Agent"),
        fullIdentityLabel: [
          formatAgentIdentityWithRole(name, role || display.functionLabel, fallback.participantId || "Agent"),
          display.modelLabel,
        ].filter(Boolean).join(" · "),
      };
    },
    [activeGroupTeamMemberByAgentId, agentsById, lang, resolveModelLabel],
  );
  const {
    filteredConversations,
    filteredStandaloneGroupConversations,
    filteredTeams,
    groupedConversations,
    searchHasTerm,
  } = useConversationIndexModel({
    agents: agentsQuery.data,
    conversations: conversationsQuery.data,
    lang,
    linkedTeamRoomIds,
    rawSessions: rawSessionsQuery.data,
    rightIndexSessions,
    sessionFilter,
    sessionsById,
    teams,
  });
  const groupedGroupConversations = useMemo(() => {
    return groupedConversations
      .map((group) => ({ ...group, items: group.items.filter((conversation) => conversation.type === "group_room") }))
      .filter((group) => group.items.length > 0);
  }, [groupedConversations]);
  const groupedGroupConversationCount = useMemo(
    () => groupedGroupConversations.reduce((count, group) => count + group.items.length, 0),
    [groupedGroupConversations],
  );
  const {
    sessionIndexHasMore,
    sessionIndexLoadMoreLabel,
    sessionIndexFullyLoadedLabel,
    sessionIndexProgressLabel,
    sessionIndexProgressVisible,
  } = resolveSessionIndexProgressModel({
    lang,
    loadedCount: rawSessionsQuery.loadedCount,
    totalEstimate: rawSessionsQuery.totalEstimate,
    hasMore: rawSessionsQuery.hasMore,
    isLoadingMore: rawSessionsQuery.isLoadingMore,
    numberFormatter,
  });

  function toggleConversationGroup(groupKey: ConversationIndexDynamicGroupKey) {
    setCollapsedConversationGroups((current) => ({
      ...current,
      [groupKey]: !(current[groupKey] ?? defaultConversationGroupCollapsed(groupKey)),
    }));
  }

  const handlePrefetchDirectSession = useCallback((sessionId: string) => {
    void prefetchSessionDetailWindow(queryClient, sessionId);
  }, [queryClient]);

  const {
    handlePetInteraction,
    handleCreateSession,
    handleOpenProjectAgentBus,
    handleOpenDirectSession,
    handleOpenAgent,
    handleOpenMentionTarget,
    handleOpenGroupRoom,
    handleToggleGroupManageSession,
    handleToggleGroupComposer,
    handleToggleGroupAgent,
    handleCreateGroupRoom,
    handleStartGroupRound,
    handleStopGroupRound,
    handleSendProjectBusMessage,
    handleRevokeProjectBusMessage,
    handleApplyGroupRoomManagement,
    handleDeleteActiveGroupRoom,
    handleResetActiveGroupRoom,
    handleDeleteSession,
    handleClearSessionHistory,
    handleAddSessionToReview,
  } = useChatWorkspaceActions({
    lang,
    t,
    navigate,
    queryClient,
    chatWorkspaceCache,
    latestDirectSessionSelectionRef,
    latestDirectSessionSelectionAtRef,
    reselectDirectSessionRef,
    activeSessionId,
    setActiveSession,
    activeGroupRoomId,
    setActiveGroupRoomId,
    setRightIndexPanel,
    setRightPaneCollapsed,
    setSelectedAgentId,
    setSessionFilter,
    setSessionComposerErrors,
    setSessionContextMenu,
    setGroupRoomActionError,
    setGroupComposerOpen,
    setGroupTitleDraft,
    groupTitleDraft,
    groupModeDraft,
    groupPurposeDraft,
    groupSelectedAgentIds,
    setGroupSelectedAgentIds,
    groupTopicDraft,
    projectBusDraft,
    projectBusInterruptTargets,
    setGroupManageSessionIds,
    groupManageTitleDraft,
    groupManageSessionIds,
    groupManageModeDraft,
    groupManagePurposeDraft,
    selectedChatAgentId,
    standardGroupRoomActive,
    activeGroupTeamOwned,
    groupRoundActive,
    groupRoundRunning,
    groupManageDisabled,
    groupDeleteDisabled,
    groupResetDisabled,
    activeGroupRoom,
    setPetActionFeedback,
    createSessionMutation,
    createGroupRoomMutation,
    startGroupRoundMutation,
    stopGroupRoundMutation,
    sendProjectBusMessageMutation,
    revokeProjectBusMessageMutation,
    updateGroupRoomMutation,
    deleteGroupRoomMutation,
    resetGroupRoomMutation,
    deleteSessionMutation,
    clearSessionHistoryMutation,
    addSessionToReviewMutation,
    petActionMutation,
  });

  const {
    beginRenameSession,
    openSessionAgentConfig,
    cancelRenameSession,
    openSessionContextMenu,
    submitRenameSession,
  } = useChatSessionRenameMenu({
    t,
    navigate,
    editingSessionTitle,
    setEditingSessionId,
    setEditingSessionTitle,
    setSessionContextMenu,
    setSessionComposerErrors,
    renameSession: (variables) => renameSessionMutation.mutate(variables),
    suppressRenameBlurUntilRef,
  });

  const {
    handleCreateAgent,
    openAgentContextMenu,
    handleOpenAgentLatestSession,
    handleCreateAgentSession,
    handleOpenAgentConfig,
    handleRenameAgent,
    handleArchiveAgent,
    agentRenameDraft,
    setAgentRenameDraftName,
    cancelAgentRename,
    submitAgentRename,
  } = useChatAgentDirectoryActions({
    lang,
    navigate,
    createSessionPending: createSessionMutation.isPending,
    renameAgentPending: renameAgentMutation.isPending,
    archiveAgentPending: archiveAgentMutation.isPending,
    createSession: (variables) => createSessionMutation.mutate(variables),
    renameAgent: (variables) => renameAgentMutation.mutate(variables),
    archiveAgent: (variables) => archiveAgentMutation.mutate(variables),
    openDirectSession: handleOpenDirectSession,
    openAgent: handleOpenAgent,
    setAgentContextMenu,
    setSessionContextMenu,
    setSessionComposerErrors,
    setAgentCreateWizardOpen,
    renameAgentEmptyMessage: t("renameAgentEmpty"),
  });

  const toggleFeaturePreset = useCallback((key: FeaturePresetKey) => {
    setFeaturePresetState((current) => ({
      ...current,
      [key]: !current[key],
    }));
  }, []);

  const {
    contextMenuDeletePending,
    contextMenuAddToReviewPending,
    contextMenuClearHistoryPending,
    contextMenuClearHistoryVisible,
    contextMenuDeleteDisabled,
    contextMenuAddToReviewDisabled,
    contextMenuClearHistoryDisabled,
  } = resolveSessionContextMenuPendingFlags({
    contextMenuSession,
    deleteSession: {
      isPending: deleteSessionMutation.isPending,
      sessionId: String(deleteSessionMutation.variables?.sessionId || "").trim() || undefined,
    },
    addToReview: {
      isPending: addSessionToReviewMutation.isPending,
      sessionId: String(addSessionToReviewMutation.variables?.sessionId || "").trim() || undefined,
    },
    clearHistory: {
      isPending: clearSessionHistoryMutation.isPending,
      sessionId: String(clearSessionHistoryMutation.variables?.sessionId || "").trim() || undefined,
    },
  });
  const conversationIndexLoading = shouldShowConversationIndexLoading({
    bootstrapIsLoading: activeSessionBootstrapQuery.isLoading,
    conversationsHasData: Boolean(conversationsQuery.data),
    conversationsIsLoading: conversationsQuery.isLoading,
    sessionsHasData: Boolean(sessionsQuery.data),
    sessionsIsLoading: sessionsQuery.isLoading,
  });
  const contextMenuAgentArchivePending = resolveAgentContextMenuArchivePending({
    agentContextMenu,
    archiveAgent: {
      isPending: archiveAgentMutation.isPending,
      agentId: String(archiveAgentMutation.variables?.agentId || "").trim() || undefined,
    },
  });
  const conversationIndexPanel = (
    <ChatWorkbenchConversationIndexPanel
      styles={styles}
      loadingLabel={t("loadingSession")}
      emptyTitle={sessionFilter.trim() ? t("noSessionMatches") : t("noSessionsYet")}
      sessionsErrorMessage={sessionsErrorMessage}
      sessionComposerSessionsError={sessionComposerErrors.__sessions__}
      sessionsTransientError={Boolean(sessionsErrorState.transientError)}
      sessionsBlockingError={Boolean(sessionsErrorState.blockingError)}
      conversationIndexLoading={conversationIndexLoading}
      isEmpty={
        filteredConversations.length === 0
        && (agentsQuery.data?.length ?? 0) === 0
        && filteredTeams.length === 0
        && filteredStandaloneGroupConversations.length === 0
      }
      selectedChatAgentId={selectedChatAgentId}
      activeSessionId={activeSessionId}
      activeGroupRoomId={activeGroupRoomId}
      agents={agentsQuery.data ?? []}
      avatarInitials={avatarInitials}
      filterText={sessionFilter}
      formatConversationIndexTime={formatConversationIndexTime}
      lang={lang}
      resolveModelLabel={resolveModelLabel}
      runtimeRunningSessionIds={runtimeRunningSessionIds}
      allVisibleSessions={allVisibleSessions}
      sessionIdsNeedingApproval={sessionIdsNeedingApproval}
      statusLabel={statusLabel}
      teams={teams}
      onOpenAgentContextMenu={openAgentContextMenu}
      onOpenAgentFromDirectory={(agent, latestSession) => {
        const agentId = String(agent.agentId || "").trim();
        if (agentId) {
          setSelectedAgentId(agentId);
        }
        if (latestSession?.id) {
          handleOpenDirectSession(latestSession.id);
          return;
        }
        if (agent.directSessionId) {
          handleOpenAgent(agent);
          return;
        }
        handleCreateAgentSession(agent);
      }}
      onOpenGroupRoom={handleOpenGroupRoom}
      agentContextMenu={agentContextMenu}
      contextMenuAgentArchivePending={contextMenuAgentArchivePending}
      createSessionPending={createSessionMutation.isPending}
      renameAgentPending={renameAgentMutation.isPending}
      onArchiveAgent={handleArchiveAgent}
      onCreateAgentSession={handleCreateAgentSession}
      onOpenAgentConfig={handleOpenAgentConfig}
      onOpenAgentLatestSession={handleOpenAgentLatestSession}
      onRenameAgent={handleRenameAgent}
      onDismissAgentContextMenu={() => setAgentContextMenu(null)}
      agentRenameDraft={agentRenameDraft}
      onCancelAgentRename={cancelAgentRename}
      onChangeAgentRenameDraft={setAgentRenameDraftName}
      onSubmitAgentRename={submitAgentRename}
      addToReviewSucceededLabel={t("addSessionToReviewSucceeded")}
      agentsById={agentsById}
      avatarImageUrlFrom={avatarImageUrlFrom}
      buildSessionReferencePayload={buildSessionReferencePayload}
      collapsedConversationGroups={collapsedConversationGroups}
      contextMenuSessionId={contextMenuSessionId}
      conversationGroupLabel={conversationGroupLabel}
      deleteBusyLabel={t("deleteSessionBusy")}
      editingSessionId={editingSessionId}
      editingSessionTitle={editingSessionTitle}
      groupedGroupConversationCount={groupedGroupConversationCount}
      filteredStandaloneGroupConversations={filteredStandaloneGroupConversations}
      filteredTeams={filteredTeams}
      groupPanelActive={groupPanelActive}
      groupedGroupConversations={groupedGroupConversations}
      isBusyPhase={isBusyPhase}
      renameSessionPending={renameSessionMutation.isPending}
      renameSessionId={renameSessionMutation.variables?.sessionId ?? ""}
      searchHasTerm={searchHasTerm}
      sessionComposerErrors={sessionComposerErrors}
      sessionsById={sessionsById}
      t={t}
      onCancelRenameSession={cancelRenameSession}
      onOpenSessionContextMenu={openSessionContextMenu}
      onDragSessionReference={startSessionReferenceDrag}
      onOpenDirectSession={handleOpenDirectSession}
      onPrefetchDirectSession={handlePrefetchDirectSession}
      onRenameTitleChange={setEditingSessionTitle}
      onSubmitRenameSession={submitRenameSession}
      onToggleConversationGroup={toggleConversationGroup}
      sessionIndexHasMore={sessionIndexHasMore}
      sessionIndexProgressVisible={sessionIndexProgressVisible}
      sessionIndexLoadMoreLabel={sessionIndexLoadMoreLabel}
      sessionIndexFullyLoadedLabel={sessionIndexFullyLoadedLabel}
      sessionIndexProgressLabel={sessionIndexProgressLabel}
      sessionIndexLoadingMore={rawSessionsQuery.isLoadingMore}
      onLoadMoreSessions={() => rawSessionsQuery.loadMore()}
      sessionContextMenu={sessionContextMenu}
      contextMenuSession={contextMenuSession}
      contextMenuAddToReviewDisabled={contextMenuAddToReviewDisabled}
      contextMenuAddToReviewPending={contextMenuAddToReviewPending}
      contextMenuClearHistoryDisabled={contextMenuClearHistoryDisabled}
      contextMenuClearHistoryPending={contextMenuClearHistoryPending}
      contextMenuClearHistoryVisible={contextMenuClearHistoryVisible}
      contextMenuDeleteDisabled={contextMenuDeleteDisabled}
      onAddSessionToReview={handleAddSessionToReview}
      onClearSessionHistory={handleClearSessionHistory}
      onDeleteSession={handleDeleteSession}
      onOpenSessionAgentConfig={openSessionAgentConfig}
      onBeginRenameSession={beginRenameSession}
      onDismissSessionContextMenu={() => setSessionContextMenu(null)}
    />
  );

  return (
    <ChatSessionWorkbenchShell
      layoutRef={layoutRef}
      className={chatLayoutClassName}
      style={layoutStyle}
      responsiveMode={responsiveLayout.mode}
      statusRailCollapsed={statusRailCollapsed}
      overlay={(
        <ChatWorkbenchOverlayBackdrop
          open={responsiveOverlayOpen}
          className={styles.overlayBackdrop}
          closeLabel={lang === "zh" ? "关闭侧栏" : "Close side panel"}
          onClose={closeResponsiveOverlayPane}
        />
      )}
      statusRail={(
      <ChatWorkbenchStatusRailHost
        chrome={{
          statusRailClassName, statusRailCollapsed, statusRailOverlayOpen, standardGroupRoomActive, lang, t, numberFormatter, statusLabel, formatTime, activeSessionId, resolveModelLabel, renderAgentAvatar, avatarInitials, agentRoleClass, avatarImageUrlFrom, agentsById,
          sessions: sessionsQuery.data, onOpenDirectSession: handleOpenDirectSession, onPrefetchDirectSession: handlePrefetchDirectSession,
        }}
        group={{
          activeGroupRoom, activeGroupTeamOwned, activeGroupTeam, availableGroupParticipantCount, groupManageChanged, groupManageDisabled, groupDeleteDisabled, groupResetDisabled, groupRoundActive, groupRoundRunning, groupRoomActionError, setGroupRoomActionError, groupManageTitleDraft, setGroupManageTitleDraft, groupManageModeDraft, setGroupManageModeDraft, groupManagePurposeDraft, setGroupManagePurposeDraft, readyChatRoomModes, availableChatRoomPurposes, chatRoomModeLabel, chatRoomPurposeLabel, groupManageSessionIds, groupManageSessionSet,
          updateGroupRoomPending: updateGroupRoomMutation.isPending, deleteGroupRoomPending: deleteGroupRoomMutation.isPending, resetGroupRoomPending: resetGroupRoomMutation.isPending,
          onOpenTeam: (teamId) => navigate(teamWorkspaceRoute(teamId)), onApplyGroupRoomManagement: handleApplyGroupRoomManagement, onDeleteActiveGroupRoom: handleDeleteActiveGroupRoom, onResetActiveGroupRoom: handleResetActiveGroupRoom, onToggleGroupManageSession: handleToggleGroupManageSession,
        }}
        session={{ activeSurfaceTitle, sessionStateValue, sessionStateLabel, sessionStateLine, compactSessionStateLine, agentDirectSessionMismatch, agentPrimaryDirectSessionId, sessionBindingMismatchLine, sessionCompactRows }}
        skill={{ activeSkillSummary: hasActiveSkill, activeSkillStatusStyle, activeSkillTitle, activeSkillName, activeSkillCommand, activeSkillStatusLabel, activeSkillShortHash }}
        prefs={{ mentalModelEnabledForNextTurn, runtimeStatusEnabledForNextTurn, onMentalModelEnabledChange: handleMentalModelEnabledChange, onRuntimeStatusEnabledChange: handleRuntimeStatusEnabledChange, featurePresetState, onToggleFeaturePreset: toggleFeaturePreset }}
        tokens={{ cacheDetailAvailable, cacheDetailOpen, cacheDetailOpenLabel, tokenStatusMetrics, onOpenCacheDetail: openCacheDetail, promptSnapshot: detail?.agentPromptSnapshot, promptAssembly: detail?.lastPromptAssembly, lastLlmPayloadTrace }}
        mental={{ mentalCompactLine, mentalSourceLabel, mentalCognitiveStateValue, mentalStateLabel, mentalSummary, mentalWhisper, mentalCognitiveStateLabel, mentalConfidence, mentalRelativeTime, mental }}
        pet={{ pet, petPresetLabel, petCompactLine, petAvatarSkinStyle, petAvatarSymbol, petVitals, petInteractionLabels, petActionPending: petActionMutation.isPending, petActionFeedback, onPetInteraction: handlePetInteraction }}
      />
      )}
      leftResizeHandle={(
        <ChatWorkbenchLeftResizeHandle
          leftVisible={responsiveLayout.leftVisible}
          conversationIndexCollapsed={conversationIndexCollapsed}
          leftActive={dragState?.side === "left"}
          leftWidth={leftPanelWidth}
          leftMin={MIN_LEFT_PANEL_WIDTH}
          leftMax={MAX_LEFT_PANEL_WIDTH}
          leftClassName={styles.resizeHandleLeft}
          resizeLeftLabel={t("resizeLeftPanel")}
          collapseLeftLabel={lang === "zh" ? "收起会话列" : "Collapse conversation column"}
          expandLeftLabel={lang === "zh" ? "展开会话列" : "Expand conversation column"}
          onToggleLeft={() => setLeftRailCollapsed((current) => !current)}
          onLeftPointerDown={(event) => handleResizeStart("left", event)}
          onLeftKeyDown={(event) => handleResizeKeyDown("left", event)}
        />
      )}
      center={(
      <ChatWorkbenchCenterColumn
        className={centerPaneClassName}
        surfaceClassName={styles.centerSurface}
        tabStrip={(
          <ChatWorkbenchCenterTabStrip
            strip={{
              styles,
              lang,
              agentSessionLabel: t("agentSession"),
              chatReturnTarget,
              chatReturnLabel,
              groupPanelActive,
              projectBusActive,
              showSessionTabs: Boolean(selectedChatAgentId || agentSessionTabs.length > 0 || cliAgentRunTabs.length > 0),
              showAgentFallbackTab: true,
              workspaceActiveTab: workspace.activeTab,
              leftOverlayVisible: responsiveLayout.leftVisible,
              rightOverlayVisible: responsiveLayout.rightVisible,
              conversationIndexOverlayOpen,
              statusRailOverlayOpen,
              onActivateAgentFallbackTab: () => {
                activeSessionId && setActiveTab(activeSessionId, "agent");
              },
              onToggleLeftOverlay: () => setResponsiveOverlayPane((current) => current === "left" ? null : "left"),
              onToggleRightOverlay: () => setResponsiveOverlayPane((current) => current === "right" ? null : "right"),
            }}
            sessionTabs={{
              activeSessionId: activeSessionId,
              activeCliAgentRunId: activeCliAgentRunId,
              agentsById: agentsById,
              buildSessionReferencePayload: buildSessionReferencePayload,
              contextMenuSessionId: contextMenuSessionId,
              cliAgentRuns: cliAgentRunTabs,
              createPending: createSessionMutation.isPending,
              createDisabled: !selectedChatAgentId,
              deletePendingSessionId:
                  deleteSessionMutation.isPending
                    ? String(deleteSessionMutation.variables?.sessionId || "").trim()
                    : "",
              editingSessionId: editingSessionId,
              editingSessionTitle: editingSessionTitle,
              lang: lang,
              renamePending: renameSessionMutation.isPending,
              renameSessionId: renameSessionMutation.variables?.sessionId ?? "",
              resolveModelLabel: resolveModelLabel,
              sessions: agentSessionTabs,
              runtimeRunningSessionIds: runtimeRunningSessionIds,
              sessionIdsNeedingApproval: sessionIdsNeedingApproval,
              statusLabel: statusLabel,
              t: t,
              workspaceActiveTab: workspace.activeTab,
              onCancelRename: cancelRenameSession,
              onContextMenu: openSessionContextMenu,
              onDragReference: startSessionReferenceDrag,
              onOpenCliAgentRun: (runId) => {
                  if (activeSessionId) {
                    setActiveTab(activeSessionId, cliAgentRunTabId(runId));
                  }
                },
              onCloseCliAgentRun: (runId) => {
                  const run = cliAgentRunTabs.find((item) => item.id === runId);
                  if (run) {
                    void closeCliAgentRun(run);
                  }
                },
              onCreateSession: handleCreateSession,
              onDeleteSession: handleDeleteSession,
              onOpenDirectSession: handleOpenDirectSession,
              onPrefetchDirectSession: handlePrefetchDirectSession,
              onRenameTitleChange: setEditingSessionTitle,
              onSetActiveTab: setActiveTab,
              onSubmitRename: submitRenameSession,
            }}
            fileTabs={{
              activeTab: workspace.activeTab,
              closePreviewTabLabel: t("closePreviewTab"),
              hidden: groupPanelActive,
              openTabs: workspace.openTabs,
              onCloseTab: (tabPath) => {
                  activeSessionId && closePreviewTab(activeSessionId, tabPath);
                },
              onOpenTab: (tabPath) => {
                  activeSessionId && setActiveTab(activeSessionId, tabPath);
                },
            }}
          />
        )}
        surface={(
          <ChatWorkbenchCenterSessionSurface
            groupPanelActive={groupPanelActive}
            terminal={{
              runs: mountedCliAgentRuns,
              activeCliAgentRunId,
              activeSessionId,
              lang,
              TerminalPanel: CliAgentRunTerminalPanel,
              onTerminalSessionChange: handleCliAgentTerminalSessionChange,
            }}
            group={{
            lang: lang,
            projectBusActive: projectBusActive,
            standardGroupRoomActive: standardGroupRoomActive,
            activeGroupRoom: activeGroupRoom,
            activeGroupRoomId: activeGroupRoomId,
            availableGroupParticipantCount: availableGroupParticipantCount,
            activeGroupParticipantById: activeGroupParticipantById,
            projectBusTimeline: projectBusTimeline,
            projectBusEvents: projectBusEvents,
            projectBusDraft: projectBusDraft,
            projectBusInterruptTargets: projectBusInterruptTargets,
            groupTopicDraft: groupTopicDraft,
            groupRoomActionError: groupRoomActionError,
            groupRoundActive: groupRoundActive,
            groupRoundStopping: groupRoundStopping,
            groupStopDisabled: groupStopDisabled,
            expandedGroupMessageIds: expandedGroupMessageIds,
            chatMentionTargets: chatMentionTargets,
            userDisplayName: runtime?.userName || (lang === "zh" ? "我" : "Me"),
            projectBusRefreshing: projectAgentBusQuery.isFetching,
            projectBusRefreshError: projectAgentBusQuery.isError ? describeError(projectAgentBusQuery.error, t("loadFailed")) : "",
            projectBusSendPending: sendProjectBusMessageMutation.isPending,
            projectBusRevokePending: revokeProjectBusMessageMutation.isPending,
            groupRoomRefreshing: activeGroupRoomQuery.isFetching,
            groupRoomRefreshError: activeGroupRoomQuery.isError ? describeError(activeGroupRoomQuery.error, t("loadFailed")) : "",
            startGroupRoundPending: startGroupRoundMutation.isPending,
            stopGroupRoundPending: stopGroupRoundMutation.isPending,
            formatTime: formatTime,
            statusLabel: statusLabel,
            groupParticipantIdentity: groupParticipantIdentity,
            renderAgentAvatar: renderAgentAvatar,
            avatarInitials: avatarInitials,
            onProjectBusDraftChange: setProjectBusDraft,
            onProjectBusInterruptTargetsChange: setProjectBusInterruptTargets,
            onGroupTopicDraftChange: setGroupTopicDraft,
            onRefreshProjectBus: () => { void projectAgentBusQuery.refetch(); },
            onRefreshGroupRoom: () => { if (activeGroupRoomId) void activeGroupRoomQuery.refetch(); },
            onSendProjectBusMessage: handleSendProjectBusMessage,
            onRevokeProjectBusMessage: handleRevokeProjectBusMessage,
            onStartGroupRound: handleStartGroupRound,
            onStopGroupRound: handleStopGroupRound,
            onOpenMentionTarget: handleOpenMentionTarget,
            onToggleExpandedGroupMessage: (messageId) =>
                setExpandedGroupMessageIds((current) =>
                  current.includes(messageId)
                    ? current.filter((id) => id !== messageId)
                    : [...current, messageId],
                ),
            }}
            session={{
            activeCliAgentRunAvailable: Boolean(activeCliAgentRun),
            activeCliAgentRunId: activeCliAgentRunId,
            activeSessionId: activeSessionId,
            blockingErrorMessage: sessionDetailErrorMessage,
            cliAgentRunEmptyLabel: lang === "zh" ? "这个 CLI 工具页还没有可显示的运行记录。" : "This CLI tool page has no run to display.",
            conversation: detail ? {
                sessionId: activeSessionId ?? detail.id,
                title: detail.title,
                phase: detail.currentPhase,
                messages: detail.messages,
                activeTurnMessage,
                transcriptPending: sessionTranscriptPending,
                hasEarlierMessages: Boolean(detail.messageWindow?.hasEarlier),
                earlierMessagesLoading: loadEarlierSessionMessagesMutation.isPending,
                onStreamingFramePaint: handleConversationStreamingFramePaint,
                assistantDisplayName: activeAgentDisplayName,
                assistantAvatarImageUrl: activeAgentAvatarImageUrl,
                assistantAvatarFallback: activeAgentAvatarFallback,
                resolveTurnAvatar: resolveConversationTurnAvatar,
                userDisplayName: resolveChatUserDisplayName(runtime?.userName),
                userAvatarPreset: runtime?.userProfile?.avatarPreset,
                userAvatarImageUrl: runtime?.userProfile?.avatarImageUrl,
                taskSummary: currentTaskSummary,
                changedFiles: detail.changedFiles ?? [],
                defaultFileContext: detail.defaultFileContext,
                showHeader: false,
                showSessionOverview: false,
                // Historical mental snapshots are conversation evidence; next-turn toggle only affects submit.
                showMentalSnapshots: true,
                composer: conversationComposer,
                permissionControl: activeSessionAgent ? {
                  value: activeSessionAgent.permissionPreset || "request_approval",
                  disabled: (
                    agentPermissionPresetMutation.isPending
                    || activeSessionAgent.configSchemaVersion < 2
                    || activeSessionAgent.configRevision < 1
                    || !activeSessionAgent.configHash
                  ),
                  pending: (
                    agentPermissionPresetMutation.isPending
                    && agentPermissionPresetMutation.variables?.agentId === activeSessionAgent.agentId
                  ),
                  agentName: activeAgentDisplayName,
                  onChange: (permissionPreset) => {
                    if (
                      !activeSessionId
                      || agentPermissionPresetMutation.isPending
                      || activeSessionAgent.configSchemaVersion < 2
                      || activeSessionAgent.configRevision < 1
                      || !activeSessionAgent.configHash
                    ) {
                      return;
                    }
                    agentPermissionPresetMutation.mutate({
                      agentId: activeSessionAgent.agentId,
                      sessionId: activeSessionId,
                      permissionPreset,
                      expectedConfigRevision: activeSessionAgent.configRevision,
                    });
                  },
                } : undefined,
                llmControl: sessionLlmControl,
                slashCommandSuggestions,
                cancelComposerModeLabel: t("cancelEditMessage"),
                turnError: detail.lastTurnError,
                stopLabel: t("stop"),
                stopPendingLabel: t("stopPending"),
                safeGuidanceLabel: t("safeGuidance"),
                safeGuidancePendingLabel: t("safeGuidancePending"),
                interruptGuidanceLabel: t("interruptGuidance"),
                interruptGuidancePendingLabel: t("interruptGuidancePending"),
                editUserMessageLabel: t("editAndResendMessage"),
                onComposerChange: handleComposerChange,
                onAddComposerAttachments: handleAddComposerAttachments,
                onRemoveComposerAttachment: handleRemoveComposerAttachment,
                onAddComposerReference: handleAddComposerReference,
                onRemoveComposerReference: handleRemoveComposerReference,
                onEditUserMessage: handleEditUserMessage,
                onCancelComposerMode: resolvedEditTarget ? handleCancelEditMessage : undefined,
                onLoadEarlierMessages: handleLoadEarlierSessionMessages,
                onSubmit: handleSubmitTurn,
                onStop: handleStopTurn,
                onSafeGuidance: () => handleSubmitGuidance("safe"),
                onInterruptGuidance: () => handleSubmitGuidance("interrupt"),
              } : null,
            conversationFocused: statusRailCollapsed,
            filePreview: {
                changed: fileContentQuery.data ? changedFiles.has(fileContentQuery.data.path) : false,
                errorMessage: fileContentQuery.isError ? describeError(fileContentQuery.error, t("loadFailed")) : "",
                file: fileContentQuery.data,
                loadingLabel: t("loadingFilePreview"),
                sourceLabel: detail?.title ?? t("currentSession"),
              },
            hasBlockingError: sessionDetailErrorState.blockingError,
            hasTransientError: sessionDetailErrorState.transientError,
            invalidChildSessionLinkMessage: invalidChildSessionLinkMessage,
            lang: lang,
            loadingSessionLabel: t("loadingSession"),
            noSessionsLabel: t("noSessionsYet"),
            notices: activeRuntimeNotices,
            sessionsPending: sessionsQuery.isPending,
            toolApproval: pendingSessionToolApproval || pendingToolGovernanceApproval ? {
                pending: pendingToolApprovalPending,
                rawTitle: pendingToolApprovalRawTitle,
                riskLabel: pendingToolApprovalRisk,
                scopeLabel: pendingToolApprovalScope,
                toolLabels: pendingToolApprovalLabels,
                actionPreview: pendingToolApprovalActionPreview,
                sessionGrantScope: pendingSessionToolApproval?.sessionGrantScope,
                toolName: pendingSessionToolApproval?.toolName || pendingToolApprovalLabels[0]?.id,
              } : null,
            transientErrorMessage: sessionDetailErrorMessage,
            workspaceActiveTab: workspace.activeTab,
            onApproveToolApproval: () => {
                if (pendingSessionToolApproval) {
                  resolveSessionToolApprovalMutation.mutate({
                    request: pendingSessionToolApproval,
                    decision: "accept",
                  });
                  return;
                }
                if (!pendingToolGovernanceApproval) {
                  return;
                }
                resolveToolApprovalMutation.mutate({ request: pendingToolGovernanceApproval, decision: "approve" });
              },
            onApproveToolForSession:
                pendingSessionToolApproval
                && pendingSessionToolApproval.approval !== "always"
                && (
                  pendingSessionToolApproval.availableDecisions.includes("acceptAlways")
                  || pendingSessionToolApproval.availableDecisions.includes("acceptForSession")
                )
                ? () => {
                  const decision = pendingSessionToolApproval.availableDecisions.includes("acceptAlways")
                    ? "acceptAlways"
                    : "acceptForSession";
                  resolveSessionToolApprovalMutation.mutate({
                    request: pendingSessionToolApproval,
                    decision,
                  });
                }
                : undefined,
            onRejectToolApproval: () => {
                if (pendingSessionToolApproval) {
                  resolveSessionToolApprovalMutation.mutate({
                    request: pendingSessionToolApproval,
                    decision: "decline",
                  });
                  return;
                }
                if (!pendingToolGovernanceApproval) {
                  return;
                }
                resolveToolApprovalMutation.mutate({ request: pendingToolGovernanceApproval, decision: "reject" });
              },
            }}
          />
        )}
      />
      )}
      rightResizeHandle={(
        <ChatWorkbenchRightResizeHandle
          rightVisible={responsiveLayout.rightVisible}
          statusRailCollapsed={statusRailCollapsed}
          rightActive={dragState?.side === "right"}
          rightWidth={rightPanelWidth}
          rightMin={MIN_RIGHT_PANEL_WIDTH}
          rightMax={MAX_RIGHT_PANEL_WIDTH}
          rightClassName={styles.resizeHandleRight}
          resizeRightLabel={t("resizeRightPanel")}
          collapseRightLabel={lang === "zh" ? "收起状态栏" : "Collapse status rail"}
          expandRightLabel={lang === "zh" ? "展开状态栏" : "Expand status rail"}
          onToggleRight={() => setRightPaneCollapsed((current) => !current)}
          onRightPointerDown={(event) => handleResizeStart("right", event)}
          onRightKeyDown={(event) => handleResizeKeyDown("right", event)}
        />
      )}
      conversationIndex={(
      <ChatWorkbenchConversationIndexRailHost
        conversationIndexPaneClassName={conversationIndexPaneClassName}
        conversationIndexCollapsed={conversationIndexCollapsed}
        conversationIndexOverlayOpen={conversationIndexOverlayOpen}
        lang={lang}
        locale={locale}
        t={t}
        currentSessionLabel={t("currentSession")}
        standardGroupRoomActive={standardGroupRoomActive}
        rightIndexPanel={rightIndexPanel}
        setRightIndexPanel={setRightIndexPanel}
        sessionFilter={sessionFilter}
        setSessionFilter={setSessionFilter}
        availableGroupParticipantCount={availableGroupParticipantCount}
        availableGroupParticipants={availableGroupParticipants}
        activeGroupRoom={activeGroupRoom}
        expandedGroupAgentSessionIds={expandedGroupAgentSessionIds}
        setExpandedGroupAgentSessionIds={setExpandedGroupAgentSessionIds}
        expandedGroupAgentDetailsBySessionId={expandedGroupAgentDetailsBySessionId}
        sessionsById={sessionsById}
        agentsById={agentsById}
        numberFormatter={numberFormatter}
        conversationIndexPanel={conversationIndexPanel}
        groupComposerOpen={groupComposerOpen}
        createGroupRoomPending={createGroupRoomMutation.isPending}
        createAgentButtonRef={agentCreateTriggerRef}
        onCreateAgent={handleCreateAgent}
        onToggleGroupComposer={handleToggleGroupComposer}
        groupTitleDraft={groupTitleDraft}
        setGroupTitleDraft={setGroupTitleDraft}
        groupModeDraft={groupModeDraft}
        setGroupModeDraft={setGroupModeDraft}
        groupPurposeDraft={groupPurposeDraft}
        setGroupPurposeDraft={setGroupPurposeDraft}
        readyChatRoomModes={readyChatRoomModes}
        availableChatRoomPurposes={availableChatRoomPurposes}
        chatRoomModesPending={chatRoomModesQuery.isPending}
        chatRoomPurposesPending={chatRoomPurposesQuery.isPending}
        groupCandidateAgents={groupCandidateAgents}
        agentsPending={agentsQuery.isPending}
        groupSelectedAgentIds={groupSelectedAgentIds}
        onToggleGroupAgent={handleToggleGroupAgent}
        onCreateGroupRoom={handleCreateGroupRoom}
        projectBusActive={projectBusActive}
        onOpenProjectAgentBus={handleOpenProjectAgentBus}
        onOpenDirectSession={handleOpenDirectSession}
        onPrefetchDirectSession={handlePrefetchDirectSession}
        resolveModelLabel={resolveModelLabel}
        statusLabel={statusLabel}
        describeError={describeError}
        renderAgentAvatar={renderAgentAvatar}
        avatarInitials={avatarInitials}
        agentRoleClass={agentRoleClass}
        avatarImageUrlFrom={avatarImageUrlFrom}
        groupParticipantIdentity={groupParticipantIdentity}
        latestMentalSnapshot={latestMentalSnapshot}
        chatRoomModeLabel={chatRoomModeLabel}
        chatRoomPurposeLabel={chatRoomPurposeLabel}
      />
      )}
    >
      <ChatWorkbenchSecondaryDialogs
        cacheDetail={
          cacheDetailOpen
            ? {
                available: cacheDetailAvailable,
                averageCacheObservedTurnCount,
                cacheCompositionAverageLabel,
                cacheCompositionAverageValue,
                cacheCompositionPercent,
                cacheCompositionTitle,
                cacheCompositionUpperBoundLabel,
                cacheComputedOverestimatedInputTokens,
                cacheDetailDialogTitle,
                cachePromptCompositionTotalTokens,
                cachePromptDonutSegments,
                cacheProviderExtraCachedInputTokens,
                cacheCalibrationReason,
                cacheCalibrationSummaryText,
                closeLabel: lang === "zh" ? "关闭缓存详情" : "Close cache details",
                lang,
                missingSegmentLabel: cacheCompositionSegmentLabel("missing", "missing", t),
                numberFormatter,
                onClose: closeCacheDetail,
                previousCacheHitLabel: t("previousCacheHit"),
                providerCachedInputTokens,
                providerCacheInputTokens,
                trueCacheDonutSegments,
                upperBoundCachedInputTokens,
                upperBoundCacheCompositionPercent,
                upperBoundCacheInputTokens,
              }
            : null
        }
        agentCreate={{
          open: agentCreateWizardOpen,
          triggerRef: agentCreateTriggerRef,
          triggerId: "chat-agent-create-trigger",
          onClose: () => setAgentCreateWizardOpen(false),
          onCreated: (agent) => {
            setSelectedAgentId(agent.agentId);
            setRightIndexPanel("conversations");
          },
          onStartConversation: async (agent) => {
            if (!agent.directSessionId) return false;
            handleOpenAgent(agent);
            return true;
          },
          onOpenAdvancedConfig: (agent) => {
            setAgentCreateWizardOpen(false);
            navigate(`/agents?agent=${encodeURIComponent(agent.agentId)}&pane=config&returnTo=${encodeURIComponent("/chat")}`);
          },
        }}
      />
    </ChatSessionWorkbenchShell>
  );
}
