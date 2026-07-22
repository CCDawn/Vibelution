import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Apple,
  ArrowLeft,
  ArrowUpRight,
  Check,
  ChevronRight,
  HeartHandshake,
  MessageCircleHeart,
  Plus,
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

import { fetchJson } from "../api/client";
import { createChatWorkspaceCache } from "./chatWorkspaceCache";
import {
  listProjectAgentBusTimeline,
} from "../api/projectAgentBus";
import { queryKeys } from "../api/queryKeys";
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
} from "../api/types";
import type { ConversationStreamingFramePaintMetrics } from "../components/conversation/conversationStreamingMetrics";
import { shouldShowNextStateSignalInConversation } from "../components/conversation/conversationNextStateSignal";
import type { TurnAvatarResolution } from "../components/conversation/conversationTurnAvatar";
import { isAgentInboxMessage } from "../components/conversation/conversationMessagePredicates";
import { VButton, VContextualHint, VInput, VNativeInput, VNativeSelect, VStateSurface, VTooltip, type VButtonProps } from "../components/vui";
import { collectBrowserPageSnapshot, postBrowserTelemetry } from "../app/browserTelemetry";
import { getPageInstanceId } from "../app/pageInstance";
import { resolvePollingInterval, usePageVisibility, useStartupWarmup } from "../app/pollingPolicy";
import type { TranslationKey } from "../i18n/dictionary";
import { PaneCollapseHandle } from "../components/layout/PaneCollapseHandle";
import { useAppI18n } from "../i18n/useAppI18n";
import { useChatWorkbenchStore } from "../store/chatWorkbenchStore";
import {
  deriveSessionDetailQueryErrorState,
  deriveSessionListQueryErrorState,
  mergeSessionDetailMessageWindow,
  mergeSessionDetailIntoSummaries,
} from "./chatSessionState";
import {
  SESSION_INDEX_PAGE_SIZE,
  updateSessionSummaryCaches,
  useSessionIndexQuery,
} from "./chatSessionIndexQuery";
import {
  ACTIVE_BACKGROUND_SYNC_POLL_MS,
  ACTIVE_INDEX_POLL_MS,
  resolveChatLiveQueryPolicy,
} from "./chatLiveQueryPolicy";
import {
  latestUserMessageId as deriveLatestUserMessageId,
  resolveComposerDraftValue,
  resolveLatestEditTarget,
} from "./chatComposerState";
import {
  resolveChatUserDisplayName,
} from "./chatCompactPanel";
import {
  tokenSpeedSampleFromMessages,
  updateTokenSpeedTracker,
  type TokenSpeedTrackerState,
} from "./chatTokenSpeed";
import {
  browserDesktopNotificationBridge,
  createDesktopConversationNotifier,
} from "./chatDesktopNotifications";
import {
  clearPendingSelfEvolutionHandoff,
  loadPendingSelfEvolutionHandoff,
} from "./selfEvolutionHandoff";
import {
  agentDisplayInfo,
  participantAgentDisplayInfo,
  sessionAgentDisplayInfo,
} from "./agentDisplay";
import { AgentSessionTabStrip, type CliAgentRunTab } from "./AgentSessionTabStrip";
import { AgentConversationDirectory, isVisibleDirectoryAgent } from "./AgentConversationDirectory";
import type { AgentContextMenuState } from "./AgentContextMenu";
import { ConversationIndexTree } from "./ConversationIndexTree";
import {
  DEFAULT_COLLAPSED_CONVERSATION_GROUPS,
  defaultConversationGroupCollapsed,
  conversationGroupLabel,
  hasInvalidChildSessionLink,
  isRepresentedInAgentSessionTabs,
  isVisibleDirectSession,
  rootSessionIdFor,
  sessionToConversationSummary,
  useConversationIndexModel,
  type ConversationIndexDynamicGroupKey,
} from "./conversationIndexModel";
import {
  activeTurnLayerToConversationMessage,
  activeTurnLayerTextLength,
  isActiveTurnSettledByDetail,
  setActiveTurnLayerForSession,
  type ActiveTurnLayerState,
} from "./chatActiveTurnLayer";
import {
  isChildSession,
  isAgentRootSession,
} from "./DirectSessionIndexItem";
import { agentCenterConfigRoute, safeAgentCenterReturnToPath } from "./agentCenterRoutes";
import {
  buildChatMentionTargets,
  type ChatMentionTarget,
} from "./chatMentionTokens";
import {
  buildConversationComposerBridgeState,
} from "./chat/ChatConversationComposerBridge";
import { ChatFileWorkspaceTabs } from "./chat/ChatFileWorkspaceTabs";
import { ConversationIndexLoadingShell } from "./chat/ChatLoadingShell";
import { ChatSessionWorkspacePanel } from "./chat/ChatSessionWorkspacePanel";
import { ChatConversationIndexRail } from "./chat/ChatConversationIndexRail";
import { ChatStatusRail } from "./chat/ChatStatusRail";
import {
  chatStreamPerformanceNowMs,
  describeChatRouteError as describeError,
  isBusyPhase,
  isRunningPhase,
  isStoppingPhase,
  shouldSuppressComposerErrorForTurnError,
} from "./chat/chatCodingRouteViewModel";
import { useChatWorkbenchLayout } from "./chat/useChatWorkbenchLayout";
import {
  useChatComposerSubmitActions,
  useChatComposerTurnMutations,
} from "./chat/useChatComposerSubmit";
import {
  nextSessionStreamGraceWindow,
  resolveSessionStreamRouteSettling,
  resolveSessionStreamRouteSwitchGraceActive,
  resolveSessionStreamRouteTargetMatches,
  resolveSessionStreamShouldConnect,
  type SessionStreamDecisionSnapshot,
} from "./chat/chatSessionStreamConnect";
import { useSessionDetailStream } from "./chat/useSessionDetailStream";
import { useGroupRoomStream } from "./chat/useGroupRoomStream";
import { useChatSessionSelection } from "./chat/useChatSessionSelection";
import { useChatWorkspaceLifecycle } from "./chat/useChatWorkspaceLifecycle";
import { useChatSessionDetailMutations } from "./chat/useChatSessionDetailMutations";
import { useChatWorkspaceActions } from "./chat/useChatWorkspaceActions";
import { ChatGroupCenterSurface } from "./chat/ChatGroupCenterSurface";
import { ChatCliAgentTerminalStack } from "./chat/ChatCliAgentTerminalStack";
import {
  useChatSessionRenameMenu,
  type SessionContextMenuState,
} from "./chat/useChatSessionRenameMenu";
import { useChatCliAgentTerminal } from "./chat/useChatCliAgentTerminal";
import { buildChatCacheDetailViewModel } from "./chat/chatCacheDetailModel";
import { useChatCacheDetailDialog } from "./chat/useChatCacheDetailDialog";
import { buildChatTokenStatusViewModel } from "./chat/chatTokenStatusModel";
import {
  buildAgentSessionTabs,
  buildChatActiveSkillViewModel,
  buildChatMentalStateViewModel,
  buildChatPetCompanionViewModel,
  buildChatSessionStateViewModel,
  type ActiveSkillContract,
} from "./chat/chatSessionSurfaceModel";
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
} from "./chat/chatRoutePresentation";
import {
  SESSION_DETAIL_INITIAL_MESSAGE_LIMIT,
  SESSION_DETAIL_HISTORY_PAGE_SIZE,
  fetchSessionDetailWindow,
  isSessionNotFoundError,
  isForeignSessionDetailQueryKey,
  latestVisibleTurnErrorMessage,
  removeDeletedSessionFromConversations,
  mergeSessionDetailIntoConversations,
  resolveSessionDetailPlaceholder,
  sessionDetailSnapshotKey,
  isStaleLedgerUpdate,
  latestMentalSnapshot,
  latestChatRoomRound,
} from "./chat/chatSessionDetailHelpers";

import {
  cliAgentRunIdFromTabId,
  cliAgentRunTabId,
} from "./chat/cliAgentRunModel";
import {
  CHAT_FEATURE_PRESETS,
  DEFAULT_CHAT_FEATURE_PRESETS,
  chatFeaturePresetShortLabel,
  type FeaturePresetKey,
} from "./chat/chatFeaturePresets";
import {
  toolApprovalLabels,
  toolApprovalRiskLabel,
  toolApprovalScopeLabel,
} from "./chat/toolApprovalLabels";
import { postSubmitTelemetry } from "./chat/chatSubmitTelemetry";
import {
  buildSessionReferencePayload,
  clearSessionImageAttachments,
  clearSessionReferenceAttachments,
  readStoredMentalModelToggle,
  startSessionReferenceDrag,
  type ComposerImageAttachment,
} from "./chat/chatComposerSubmitModel";
import styles from "./ChatCodingRoute.styles";

export type { CliAgentRunView, CliAgentTerminalSession } from "./chat/cliAgentRunModel";
export { canInputTerminal } from "./chat/cliAgentRunModel";

const CliAgentRunTerminalPanel = lazy(() =>
  import("./chat/CliAgentRunTerminalPanel").then((module) => ({
    default: module.CliAgentRunTerminalPanel,
  })),
);

/** Secondary-lazy: open only when creating an Agent (keeps wizard graph out of Chat shell). */
const AgentCreateWizardDialog = lazy(() =>
  import("./agent-create/AgentCreateWizardDialog").then((module) => ({
    default: module.AgentCreateWizardDialog,
  })),
);

/** Secondary-lazy: cache donut dialog opens from status rail action. */
const CacheDetailDialog = lazy(() =>
  import("./chat/CacheDetailDialog").then((module) => ({
    default: module.CacheDetailDialog,
  })),
);

/** Secondary-lazy: session row context menu. */
const SessionContextMenu = lazy(() =>
  import("./SessionContextMenu").then((module) => ({
    default: module.SessionContextMenu,
  })),
);

/** Secondary-lazy: Agent directory row context menu. */
const AgentContextMenu = lazy(() =>
  import("./AgentContextMenu").then((module) => ({
    default: module.AgentContextMenu,
  })),
);

type SessionDetailWithActiveSkill = SessionDetail & {
  activeSkillContract?: ActiveSkillContract | null;
};

type PetInteractionAction = "feed" | "talk" | "care";

type RightIndexPanel = "conversations" | "members";


export function ChatCodingRoute() {
  const { lang, t, statusLabel } = useAppI18n();
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
  const [editingSessionTitle, setEditingSessionTitle] = useState("");
  const [sessionContextMenu, setSessionContextMenu] = useState<SessionContextMenuState | null>(null);
  const [agentContextMenu, setAgentContextMenu] = useState<AgentContextMenuState | null>(null);
  const [activeTurnLayersBySession, setActiveTurnLayersBySession] = useState<Record<string, ActiveTurnLayerState>>({});

  const [tokenSpeedTracker, setTokenSpeedTracker] = useState<TokenSpeedTrackerState | null>(null);
  const [petActionFeedback, setPetActionFeedback] = useState("");
  const [mentalModelEnabledForNextTurn, setMentalModelEnabledForNextTurn] = useState<boolean>(
    () => readStoredMentalModelToggle() ?? false,
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
  const chatReturnTarget = useMemo(() => {
    return safeAgentCenterReturnToPath(new URLSearchParams(location.search).get("returnTo"));
  }, [location.search]);
  const chatReturnLabel = useMemo(() => {
    const raw = String(new URLSearchParams(location.search).get("returnLabel") || "").trim();
    if (!raw || raw.length > 80) {
      return lang === "zh" ? "返回来源" : "Back";
    }
    return raw;
  }, [lang, location.search]);
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
    function closeSessionContextMenu() {
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
    routeTargetMatches: sessionStreamRouteTargetMatches,
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
  useEffect(() => {
    if (!standardGroupRoomActive && rightIndexPanel === "members") {
      setRightIndexPanel("conversations");
    }
  }, [standardGroupRoomActive, rightIndexPanel]);

  const runtimeQuery = useQuery({
    queryKey: queryKeys.runtimeSummary(),
    queryFn: () => fetchJson<RuntimeSummary>("/api/runtime/summary"),
    enabled: secondaryChatDataEnabled,
    refetchInterval: resolvePollingInterval(chatPollingVisible, 5_000),
    refetchIntervalInBackground: chatStartupWarmupActive,
  });
  const petQuery = useQuery({
    queryKey: queryKeys.petSummary(),
    queryFn: () => fetchJson<PetSummary>("/api/pet/summary"),
    enabled: secondaryChatDataEnabled,
    refetchInterval: resolvePollingInterval(chatPollingVisible, 10_000),
    refetchIntervalInBackground: chatStartupWarmupActive,
  });
  const configSummaryQuery = useQuery({
    queryKey: queryKeys.configPublic(),
    queryFn: () => fetchJson<ConfigSummary>("/api/config/public"),
    staleTime: 30_000,
  });
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const activeSessionBootstrapQuery = useQuery({
    queryKey: ["sessions", "active-bootstrap"],
    queryFn: ({ signal }) => fetchJson<{ activeSessionId: string }>("/api/sessions/active", { signal }),
    staleTime: 5_000,
  });
  // Prefer URL targets immediately; otherwise wait for active-session bootstrap (empty id still settles).
  const sessionIndexQueryEnabled =
    Boolean(requestedSessionId || requestedRoomId)
    || activeSessionBootstrapQuery.isFetched;
  const modelLabelsById = useMemo(
    () => new Map(Object.entries(configSummaryQuery.data?.modelLabels ?? {})),
    [configSummaryQuery.data?.modelLabels],
  );
  const modelImageInputSupportById = useMemo(
    () => new Map(Object.entries(configSummaryQuery.data?.modelImageInputSupport ?? {})),
    [configSummaryQuery.data?.modelImageInputSupport],
  );
  const resolveModelLabel = useCallback(
    (modelId: string) => modelLabelsById.get(modelId),
    [modelLabelsById],
  );
  const rawSessionsQuery = useSessionIndexQuery({
    queryClient,
    queryText: sessionQueryText,
    enabled: sessionIndexQueryEnabled,
    refetchInterval: chatLiveQueryPolicy.sessionsRefetchInterval,
    refetchIntervalInBackground: chatLiveQueryPolicy.directRefetchIntervalInBackground,
  });
  const visibleSessionsData = useMemo(
    () => rawSessionsQuery.data?.filter(isVisibleDirectSession),
    [rawSessionsQuery.data],
  );
  const sessionsQuery = useMemo(
    () => ({
      ...rawSessionsQuery,
      data: visibleSessionsData,
    }),
    [rawSessionsQuery, visibleSessionsData],
  );
  const conversationsQuery = useQuery({
    queryKey: queryKeys.conversations(),
    queryFn: () => fetchJson<ConversationSummary[]>("/api/conversations"),
    enabled: secondaryChatDataEnabled,
    refetchInterval: chatLiveQueryPolicy.conversationsRefetchInterval,
    refetchIntervalInBackground: chatLiveQueryPolicy.sharedRefetchIntervalInBackground,
  });
  const teamsQuery = useQuery({
    queryKey: queryKeys.teams(),
    queryFn: () => fetchJson<TeamListPayload>("/api/teams"),
    enabled: secondaryChatDataEnabled,
    refetchInterval: resolvePollingInterval(chatPollingVisible, directSessionPanelActive ? false : ACTIVE_INDEX_POLL_MS),
    refetchIntervalInBackground: chatStartupWarmupActive,
  });
  const agentsQuery = useQuery({
    queryKey: queryKeys.agents(),
    queryFn: () => fetchJson<AgentInstance[]>("/api/agents?detail=summary"),
    enabled: secondaryChatDataEnabled || groupComposerOpen || standardGroupRoomActive,
  });
  const skillsQuery = useQuery({
    queryKey: queryKeys.skills(),
    queryFn: () => fetchJson<SkillLibraryPayload>("/api/skills"),
    enabled: secondaryChatDataEnabled && Boolean(activeSessionId),
    staleTime: 60_000,
  });
  const slashCommandSuggestions = skillsQuery.data?.skills ?? [];
  const chatRoomModesQuery = useQuery({
    queryKey: queryKeys.chatRoomModes(),
    queryFn: () => fetchJson<ChatRoomMode[]>("/api/chat-rooms/modes"),
    enabled: groupComposerOpen || standardGroupRoomActive,
  });
  const chatRoomPurposesQuery = useQuery({
    queryKey: queryKeys.chatRoomPurposes(),
    queryFn: () => fetchJson<ChatRoomPurpose[]>("/api/chat-rooms/purposes"),
    enabled: groupComposerOpen || standardGroupRoomActive,
  });
  const activeGroupRoomQuery = useQuery({
    queryKey: queryKeys.chatRoom(activeGroupRoomId || "none"),
    queryFn: () => fetchJson<ChatRoomDetail>(`/api/chat-rooms/${activeGroupRoomId}`),
    enabled: standardGroupRoomActive,
    refetchInterval: standardGroupRoomActive
      ? resolvePollingInterval(
          chatPollingVisible,
          groupStreamConnected ? false : 3_000,
          { backgroundMs: groupBackgroundSyncActive && !groupStreamConnected ? ACTIVE_BACKGROUND_SYNC_POLL_MS : false },
        )
      : false,
    refetchIntervalInBackground: chatStartupWarmupActive || groupBackgroundSyncActive,
  });
  const projectAgentBusQuery = useQuery({
    queryKey: queryKeys.projectAgentBus(),
    queryFn: ({ signal }) => listProjectAgentBusTimeline(undefined, { signal }),
    enabled: projectBusActive,
    refetchInterval: projectBusActive ? resolvePollingInterval(chatPollingVisible, 3_000) : false,
    refetchIntervalInBackground: chatStartupWarmupActive,
  });
  const expandedGroupAgentDetailQueries = useQueries({
    queries: expandedGroupAgentSessionIds.map((sessionId) => ({
      queryKey: queryKeys.session(sessionId || "none"),
      queryFn: () => fetchSessionDetailWindow(sessionId, { messageLimit: 20 }),
      enabled: standardGroupRoomActive && Boolean(sessionId),
      refetchInterval: standardGroupRoomActive && sessionId
        ? resolvePollingInterval(
            chatPollingVisible,
            3_000,
            { backgroundMs: groupBackgroundSyncActive && !groupStreamConnected ? ACTIVE_BACKGROUND_SYNC_POLL_MS : false },
          )
        : false,
      refetchIntervalInBackground: chatStartupWarmupActive || groupBackgroundSyncActive,
    })),
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

  useEffect(() => {
    const activeId = String(activeSessionId || "").trim();
    if (!activeId) {
      return;
    }
    void queryClient.cancelQueries({
      predicate: (query) => isForeignSessionDetailQueryKey(query.queryKey, activeId),
    });
  }, [activeSessionId, queryClient]);
  const sessionDetailQuery = useQuery({
    queryKey: queryKeys.session(activeSessionId ?? "none"),
    enabled: Boolean(activeSessionId),
    queryFn: ({ signal }) => fetchSessionDetailWindow(activeSessionId, { signal }),
    structuralSharing: (previous, next) =>
      mergeSessionDetailMessageWindow(previous as SessionDetail | undefined, next as SessionDetail),
    placeholderData: () =>
      resolveSessionDetailPlaceholder({
        activeSessionId,
        cachedDetail: queryClient.getQueryData<SessionDetail>(queryKeys.session(activeSessionId ?? "none")),
        summary: activeSessionId
          ? sessionsQuery.data?.find((session) => session.id === activeSessionId)
          : undefined,
      }),
    refetchInterval: startupDetailSettledSessionId === activeSessionId
      ? chatLiveQueryPolicy.sessionDetailRefetchInterval
      : false,
    refetchIntervalInBackground: chatLiveQueryPolicy.directRefetchIntervalInBackground,
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
  const sessionLlmOptionsQuery = useQuery({
    queryKey: queryKeys.sessionLlmOptions(activeSessionId ?? "none"),
    enabled: secondaryChatDataEnabled && Boolean(activeSessionId),
    queryFn: () => fetchJson<SessionLlmOptions>(
      `/api/sessions/${encodeURIComponent(activeSessionId ?? "")}/llm-options`,
    ),
    staleTime: 30_000,
  });
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
  const activeRootSessionId = rootSessionIdFor(sessionDetailQuery.data ?? directSessionActiveSummary);
  const childSessionLiveQueryPolicy = resolveChatLiveQueryPolicy({
    ...chatLiveQueryPolicyInput,
    activeRootSessionId: activeRootSessionId || "",
  });
  const childSessionsQuery = useQuery({
    queryKey: queryKeys.sessionChildSessions(activeRootSessionId || "none"),
    queryFn: () => fetchJson<SessionSummary[]>(`/api/sessions/${activeRootSessionId}/child-sessions`),
    enabled: secondaryChatDataEnabled && Boolean(activeRootSessionId) && directSessionPanelActive,
    refetchInterval: childSessionLiveQueryPolicy.childSessionsRefetchInterval,
    refetchIntervalInBackground: childSessionLiveQueryPolicy.directRefetchIntervalInBackground,
  });
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
    setEditingSessionId,
    setEditingSessionTitle,
  });

  const renameAgentMutation = useMutation({
    mutationFn: (payload: { agentId: string; displayName: string }) =>
      fetchJson<AgentInstance>(`/api/agents/${encodeURIComponent(payload.agentId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ displayName: payload.displayName }),
      }),
    onMutate: async (payload) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.agents() });
      const previousAgents = queryClient.getQueryData<AgentInstance[]>(queryKeys.agents());
      queryClient.setQueryData<AgentInstance[]>(queryKeys.agents(), (current) =>
        current?.map((agent) => agent.agentId === payload.agentId
          ? { ...agent, displayName: payload.displayName }
          : agent),
      );
      return { previousAgents };
    },
    onSuccess: (updatedAgent) => {
      queryClient.setQueryData<AgentInstance[]>(queryKeys.agents(), (current) =>
        current?.map((agent) => agent.agentId === updatedAgent.agentId ? updatedAgent : agent),
      );
      setSessionComposerErrors((current) => ({ ...current, __sessions__: "" }));
      void chatWorkspaceCache.afterAgentWorkspaceChanged();
    },
    onError: (error, _variables, context) => {
      if (context?.previousAgents) {
        queryClient.setQueryData(queryKeys.agents(), context.previousAgents);
      }
      setSessionComposerErrors((current) => ({
        ...current,
        __sessions__: describeError(error, t("loadFailed")),
      }));
    },
  });

  const archiveAgentMutation = useMutation({
    mutationFn: (payload: { agentId: string }) =>
      fetchJson<AgentInstance>(`/api/agents/${encodeURIComponent(payload.agentId)}`, {
        method: "DELETE",
      }),
    onMutate: async (payload) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.agents() });
      const previousAgents = queryClient.getQueryData<AgentInstance[]>(queryKeys.agents());
      const previousSelectedAgentId = selectedAgentId;
      const previousActiveSessionId = activeSessionId;
      const remainingAgents = (previousAgents ?? []).filter((agent) => agent.agentId !== payload.agentId);
      const remainingAgentIds = new Set(remainingAgents.map((agent) => agent.agentId));
      const currentActiveSession = (sessionsQuery.data ?? []).find((session) => session.id === activeSessionId);
      const fallbackSession = (
        currentActiveSession
        && remainingAgentIds.has(String(currentActiveSession.agentId || "").trim())
      )
        ? currentActiveSession
        : (sessionsQuery.data ?? []).find(
          (session) => remainingAgentIds.has(String(session.agentId || "").trim()),
        );
      const activeSessionAgentId = String(
        sessionDetailQuery.data?.agentId
        || currentActiveSession?.agentId
        || "",
      ).trim();
      const fallbackAgentId = String(
        fallbackSession?.agentId
        || remainingAgents.find((agent) => String(agent.status || "").trim() !== "archived")?.agentId
        || "",
      ).trim();

      queryClient.setQueryData<AgentInstance[]>(queryKeys.agents(), remainingAgents);
      setAgentContextMenu(null);
      setSelectedAgentId((current) => current === payload.agentId ? fallbackAgentId : current);
      if (activeSessionAgentId === payload.agentId) {
        setActiveSession(fallbackSession?.id || "");
      }
      return {
        previousActiveSessionId,
        previousAgents,
        previousSelectedAgentId,
      };
    },
    onSuccess: (agent) => {
      queryClient.setQueryData<AgentInstance[]>(queryKeys.agents(), (current) =>
        current?.filter((item) => item.agentId !== agent.agentId),
      );
      setSessionComposerErrors((current) => ({
        ...current,
        __sessions__: "",
      }));
      void chatWorkspaceCache.afterAgentArchived();
    },
    onError: (error, _variables, context) => {
      if (context?.previousAgents) {
        queryClient.setQueryData(queryKeys.agents(), context.previousAgents);
      }
      setSelectedAgentId(context?.previousSelectedAgentId ?? "");
      if (context?.previousActiveSessionId) {
        setActiveSession(context.previousActiveSessionId);
      }
      setSessionComposerErrors((current) => ({
        ...current,
        __sessions__: describeError(error, t("loadFailed")),
      }));
      void chatWorkspaceCache.afterAgentArchived();
    },
  });

  const {
    sessionReasoningEffortMutation,
    loadEarlierSessionMessagesMutation,
    resolveToolApprovalMutation,
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
    return new Set(teams.map((team) => String(team.linkedChatRoomId ?? "").trim()).filter(Boolean));
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
    if (activeSessionId && sessionDetailQuery.data) {
      hydrateSession(activeSessionId, [], "agent");
    }
  }, [activeSessionId, hydrateSession, sessionDetailQuery.data]);

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

  const locale = lang === "zh" ? "zh-CN" : "en-US";

  const timeFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat(locale, {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      }),
    [locale],
  );
  const numberFormatter = useMemo(() => new Intl.NumberFormat(locale), [locale]);
  const compactNumberFormatter = useMemo(
    () => new Intl.NumberFormat(locale, { notation: "compact", maximumFractionDigits: 1 }),
    [locale],
  );

  const runtime = runtimeQuery.data;
  const pet = petQuery.data;
  const rawSessionDetail = sessionDetailQuery.data;
  const selectedSessionDetail =
    rawSessionDetail && rawSessionDetail.id === activeSessionId ? rawSessionDetail : undefined;
  const detail = selectedSessionDetail;
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
  const sessionDetailLoadingForActiveSession = Boolean(
    activeSessionId
    && (!rawSessionDetail || rawSessionDetail.id !== activeSessionId)
    && sessionDetailQuery.isFetching,
  );
  const runtimeActiveChatTurnSessionIds = new Set(
    [
      ...(runtime?.workRuns?.activeItems?.chat_turn ?? []),
      runtime?.workRuns?.active?.chat_turn,
    ]
      .map((run) => String(run?.sessionId ?? "").trim())
      .filter(Boolean),
  );
  const runtimeMatchesSelectedSession = Boolean(
    activeSessionId && runtimeActiveChatTurnSessionIds.has(activeSessionId),
  );
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
  const pendingToolApproval = useMemo(
    () => (detail?.pendingToolGovernanceRequests ?? []).find((request) => request.status === "pending_review") ?? null,
    [detail?.pendingToolGovernanceRequests],
  );
  const pendingToolApprovalLabels = useMemo(
    () => toolApprovalLabels(pendingToolApproval),
    [pendingToolApproval],
  );
  const pendingToolApprovalRawTitle = pendingToolApprovalLabels.map((item) => item.id).join("、");
  const pendingToolApprovalScope = toolApprovalScopeLabel(pendingToolApproval?.grantScope, lang);
  const pendingToolApprovalRisk = toolApprovalRiskLabel(pendingToolApproval?.riskLevel, lang);
  const pendingToolApprovalPending = Boolean(
    pendingToolApproval
    && resolveToolApprovalMutation.isPending
    && resolveToolApprovalMutation.variables?.request.requestId === pendingToolApproval.requestId,
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
      .filter((signal) => shouldShowNextStateSignalInConversation(signal, phase))
      .slice(-3)
      .reverse();
  }, [detail?.currentPhase, detail?.nextStateSignals, directSessionActiveSummary?.currentPhase, directSessionActiveSummary?.status]);
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
  const sessionBusy = isBusyPhase(detail?.currentPhase);
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
    resolvedEditTarget,
    activeEditTarget,
    composerDisabled,
    sessionBusy,
    sessionStopping,
    activePhase: detail?.currentPhase,
    activeAgentImageInputUnsupported,
    activeImageInputModelId,
    latestUserMessageId,
    detail,
    setMentalModelEnabledForNextTurn,
  });
  const sessionLlmOptions = sessionLlmOptionsQuery.data;
  const sessionLlmControl = activeSessionId ? {
    model: sessionLlmOptions?.model ?? null,
    currentReasoningEffort: sessionLlmOptions?.currentReasoningEffort || detail?.reasoningEffort || "",
    disabled: sessionBusy || sessionLlmOptionsQuery.isLoading,
    pending: sessionReasoningEffortMutation.isPending,
    onReasoningEffortChange: (reasoningEffort: string) => {
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
    mental: runtime?.mentalState,
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

  const allVisibleSessions = useMemo(() => {
    const merged = [...(sessionsQuery.data ?? []), ...(childSessionsQuery.data ?? [])];
    return merged
      .filter(isVisibleDirectSession)
      .filter((session, index, sessions) => sessions.findIndex((item) => item.id === session.id) === index);
  }, [childSessionsQuery.data, sessionsQuery.data]);

  const sessionsById = useMemo(() => {
    return new Map(allVisibleSessions.map((session) => [session.id, session]));
  }, [allVisibleSessions]);

  const visibleChatAgents = useMemo(() => {
    return (agentsQuery.data ?? []).filter(isVisibleDirectoryAgent);
  }, [agentsQuery.data]);
  const activeSessionAgentId = useMemo(() => {
    return String(
      sessionDetailQuery.data?.agentId
      || directSessionActiveSummary?.agentId
      || sessionsById.get(activeSessionId || "")?.agentId
      || "",
    ).trim();
  }, [activeSessionId, directSessionActiveSummary?.agentId, sessionDetailQuery.data?.agentId, sessionsById]);
  useEffect(() => {
    if (activeSessionAgentId) {
      setSelectedAgentId(activeSessionAgentId);
    }
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

  const agentSessionTabs = useMemo(
    () => buildAgentSessionTabs({
      sessions: selectedAgentSessionsQuery.data?.items,
      selectedChatAgentDirectSessionId: agentsById.get(selectedChatAgentId)?.directSessionId,
    }),
    [agentsById, selectedAgentSessionsQuery.data?.items, selectedChatAgentId],
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
  const sessionIndexLoadedCount = rawSessionsQuery.loadedCount;
  const sessionIndexTotalEstimate = rawSessionsQuery.totalEstimate;
  const sessionIndexHasMore = rawSessionsQuery.hasMore;
  const sessionIndexLoadMoreLabel = rawSessionsQuery.isLoadingMore
    ? (lang === "zh" ? "加载中" : "Loading")
    : (lang === "zh" ? "加载更多会话" : "Load more chats");
  const sessionIndexFullyLoadedLabel = lang === "zh" ? "已加载全部会话" : "All chats loaded";
  const sessionIndexProgressLabel =
    sessionIndexTotalEstimate > sessionIndexLoadedCount
      ? `${numberFormatter.format(sessionIndexLoadedCount)} / ${numberFormatter.format(sessionIndexTotalEstimate)}`
      : numberFormatter.format(sessionIndexLoadedCount);
  const sessionIndexProgressVisible = sessionIndexHasMore || sessionIndexTotalEstimate > SESSION_INDEX_PAGE_SIZE;

  function formatTime(value: string) {
    if (!value) {
      return "";
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
      return value;
    }
    return timeFormatter.format(parsed);
  }

  function formatConversationIndexTime(value: string) {
    return formatTime(value).replace(/:\d{2}$/, "");
  }

  function toggleConversationGroup(groupKey: ConversationIndexDynamicGroupKey) {
    setCollapsedConversationGroups((current) => ({
      ...current,
      [groupKey]: !(current[groupKey] ?? defaultConversationGroupCollapsed(groupKey)),
    }));
  }

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
    chatWorkspaceCache,
    latestDirectSessionSelectionRef,
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
    selectDirectSessionMutation,
    petActionMutation,
  });

  function handleCreateAgent() {
    setAgentCreateWizardOpen(true);
  }

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
  });

  const openAgentContextMenu = useCallback((
    event: ReactMouseEvent<HTMLElement>,
    agent: AgentInstance,
    latestSession: SessionSummary | null,
  ) => {
    event.preventDefault();
    event.stopPropagation();
    setSessionContextMenu(null);
    setAgentContextMenu({
      agent,
      latestSession,
      x: event.clientX,
      y: event.clientY,
    });
  }, []);

  const handleOpenAgentLatestSession = useCallback((
    agent: AgentInstance,
    latestSession: SessionSummary | null,
  ) => {
    setAgentContextMenu(null);
    if (latestSession?.id) {
      handleOpenDirectSession(latestSession.id);
      return;
    }
    handleOpenAgent(agent);
  }, [handleOpenAgent, handleOpenDirectSession]);

  const handleCreateAgentSession = useCallback((agent: AgentInstance) => {
    const agentId = String(agent.agentId || "").trim();
    setAgentContextMenu(null);
    if (!agentId || createSessionMutation.isPending) {
      return;
    }
    setSessionComposerErrors((current) => ({
      ...current,
      __sessions__: "",
    }));
    createSessionMutation.mutate({ agentId });
  }, [createSessionMutation, setSessionComposerErrors]);

  const handleOpenAgentConfig = useCallback((
    agent: AgentInstance,
    latestSession: SessionSummary | null,
  ) => {
    const agentId = String(agent.agentId || "").trim();
    setAgentContextMenu(null);
    if (!agentId) {
      return;
    }
    navigate(agentCenterConfigRoute({
      agentId,
      pane: "config",
      returnLabel: "chat",
      returnTo: latestSession?.id
        ? `/chat?session=${encodeURIComponent(latestSession.id)}`
        : "/chat",
    }));
  }, [navigate]);

  const handleRenameAgent = useCallback((agent: AgentInstance) => {
    const agentId = String(agent.agentId || "").trim();
    setAgentContextMenu(null);
    if (!agentId || renameAgentMutation.isPending) {
      return;
    }
    const currentName = String(agent.displayName || agent.agentCode || agentId).trim();
    const requestedName = window.prompt(
      lang === "zh" ? "输入新的 Agent 名称" : "Enter a new Agent name",
      currentName,
    );
    if (requestedName === null) {
      return;
    }
    const title = requestedName.trim();
    if (!title) {
      setSessionComposerErrors((current) => ({
        ...current,
        __sessions__: t("renameAgentEmpty"),
      }));
      return;
    }
    if (title === currentName) {
      return;
    }
    renameAgentMutation.mutate({ agentId, displayName: title });
  }, [lang, renameAgentMutation, setSessionComposerErrors, t]);

  const handleArchiveAgent = useCallback((agent: AgentInstance) => {
    const agentId = String(agent.agentId || "").trim();
    if (!agentId || archiveAgentMutation.isPending) {
      return;
    }
    const agentName = String(agent.displayName || agent.agentCode || agentId).trim();
    const confirmed = window.confirm(
      lang === "zh"
        ? `确认安全归档 ${agentName}？这会将 Agent 移出可用列表及相关绑定，但保留会话、记忆、日志和工作区。`
        : `Archive ${agentName}? This removes the Agent from active lists and bindings while keeping sessions, memory, logs, and workspace data.`,
    );
    if (!confirmed) {
      return;
    }
    setSessionComposerErrors((current) => ({
      ...current,
      __sessions__: "",
    }));
    archiveAgentMutation.mutate({ agentId });
  }, [archiveAgentMutation, lang]);

  const toggleFeaturePreset = useCallback((key: FeaturePresetKey) => {
    setFeaturePresetState((current) => ({
      ...current,
      [key]: !current[key],
    }));
  }, []);

  const contextMenuSessionIsBusy = contextMenuSession
    ? isBusyPhase(contextMenuSession.currentPhase || contextMenuSession.status)
    : false;
  const contextMenuDeletePending = Boolean(
    contextMenuSession
    && deleteSessionMutation.isPending
    && deleteSessionMutation.variables?.sessionId === contextMenuSession.id,
  );
  const contextMenuAddToReviewPending = Boolean(
    contextMenuSession
    && addSessionToReviewMutation.isPending
    && addSessionToReviewMutation.variables?.sessionId === contextMenuSession.id,
  );
  const contextMenuClearHistoryPending = Boolean(
    contextMenuSession
    && clearSessionHistoryMutation.isPending
    && clearSessionHistoryMutation.variables?.sessionId === contextMenuSession.id
  );
  const contextMenuClearHistoryVisible = Boolean(
    contextMenuSession?.agentId
    && isAgentRootSession(contextMenuSession)
  );
  const contextMenuAgentArchivePending = Boolean(
    agentContextMenu
    && archiveAgentMutation.isPending
    && archiveAgentMutation.variables?.agentId === agentContextMenu.agent.agentId
  );
  const contextMenuDeleteDisabled = contextMenuDeletePending || contextMenuSessionIsBusy;
  const contextMenuAddToReviewDisabled = contextMenuAddToReviewPending || contextMenuSessionIsBusy;
  const contextMenuClearHistoryDisabled = contextMenuClearHistoryPending || contextMenuSessionIsBusy;
  const conversationIndexPanel = (
    <>
      {sessionComposerErrors.__sessions__ ? (
        <VStateSurface
          className={styles.panelState}
          tone="error"
          title={sessionComposerErrors.__sessions__}
        />
      ) : null}
      {sessionsErrorState.transientError ? (
        <div className={styles.panelNotice} role="status">{sessionsErrorMessage}</div>
      ) : null}
      {sessionsErrorState.blockingError ? (
        <VStateSurface className={styles.panelState} tone="error" title={sessionsErrorMessage} />
      ) : conversationsQuery.isPending && !conversationsQuery.data && sessionsQuery.isPending && !sessionsQuery.data ? (
        <ConversationIndexLoadingShell label={t("loadingSession")} />
      ) : filteredConversations.length === 0 && visibleChatAgents.length === 0 && filteredTeams.length === 0 && filteredStandaloneGroupConversations.length === 0 ? (
        <VStateSurface
          className={styles.panelState}
          tone="empty"
          title={sessionFilter.trim() ? t("noSessionMatches") : t("noSessionsYet")}
        />
      ) : (
        <>
          <AgentConversationDirectory
            activeAgentId={selectedChatAgentId}
            agents={visibleChatAgents}
            avatarInitials={avatarInitials}
            filterText={sessionFilter}
            formatTime={formatConversationIndexTime}
            lang={lang}
            resolveModelLabel={resolveModelLabel}
            sessions={allVisibleSessions}
            onContextMenu={openAgentContextMenu}
            onOpenAgent={(agent) => (
              agent.directSessionId ? handleOpenAgent(agent) : handleCreateAgentSession(agent)
            )}
          />
          {agentContextMenu ? (
            <Suspense fallback={null}>
              <AgentContextMenu
                archivePending={contextMenuAgentArchivePending}
                createPending={createSessionMutation.isPending}
                renamePending={renameAgentMutation.isPending}
                lang={lang}
                state={agentContextMenu}
                onArchive={handleArchiveAgent}
                onCreateSession={handleCreateAgentSession}
                onOpenConfig={handleOpenAgentConfig}
                onOpenLatest={handleOpenAgentLatestSession}
                onRename={handleRenameAgent}
              />
            </Suspense>
          ) : null}
          <ConversationIndexTree
            activeGroupRoomId={activeGroupRoomId}
            activeSessionId={activeSessionId}
            addToReviewSucceededLabel={t("addSessionToReviewSucceeded")}
            agentsById={agentsById}
            avatarImageUrlFrom={avatarImageUrlFrom}
            avatarInitials={avatarInitials}
            buildSessionReferencePayload={buildSessionReferencePayload}
            collapsedConversationGroups={collapsedConversationGroups}
            contextMenuSessionId={contextMenuSessionId}
            conversationGroupLabel={conversationGroupLabel}
            deleteBusyLabel={t("deleteSessionBusy")}
            editingSessionId={editingSessionId}
            editingSessionTitle={editingSessionTitle}
            filteredConversationsCount={groupedGroupConversationCount}
            filteredStandaloneGroupConversations={filteredStandaloneGroupConversations}
            filteredTeams={filteredTeams}
            formatTime={formatConversationIndexTime}
            groupPanelActive={groupPanelActive}
            groupedConversations={groupedGroupConversations}
            isBusyPhase={isBusyPhase}
            lang={lang}
            renamePending={renameSessionMutation.isPending}
            renameSessionId={renameSessionMutation.variables?.sessionId ?? ""}
            resolveModelLabel={resolveModelLabel}
            searchHasTerm={searchHasTerm}
            sessionComposerErrors={sessionComposerErrors}
            sessionsById={sessionsById}
            statusLabel={statusLabel}
            t={t}
            onCancelRename={cancelRenameSession}
            onContextMenu={openSessionContextMenu}
            onDragReference={startSessionReferenceDrag}
            onOpenDirectSession={handleOpenDirectSession}
            onOpenGroupRoom={handleOpenGroupRoom}
            onRenameTitleChange={setEditingSessionTitle}
            onSubmitRename={submitRenameSession}
            onToggleConversationGroup={toggleConversationGroup}
          />
          {sessionIndexHasMore ? (
            <VButton
              type="button"
              className={styles.sessionLoadMoreButton}
              onClick={() => rawSessionsQuery.loadMore()}
              isDisabled={rawSessionsQuery.isLoadingMore}
              aria-label={sessionIndexLoadMoreLabel}
            >
              <span>{sessionIndexLoadMoreLabel}</span>
              <strong>{sessionIndexProgressLabel}</strong>
            </VButton>
          ) : sessionIndexProgressVisible ? (
            <div className={styles.sessionLoadMoreStatus} role="status">
              <span>{sessionIndexFullyLoadedLabel}</span>
              <strong>{sessionIndexProgressLabel}</strong>
            </div>
          ) : null}
          {sessionContextMenu && contextMenuSession ? (
            <Suspense fallback={null}>
              <SessionContextMenu
                addToReviewDisabled={contextMenuAddToReviewDisabled}
                addToReviewPending={contextMenuAddToReviewPending}
                clearHistoryDisabled={contextMenuClearHistoryDisabled}
                clearHistoryPending={contextMenuClearHistoryPending}
                clearHistoryVisible={contextMenuClearHistoryVisible}
                deleteDisabled={contextMenuDeleteDisabled}
                lang={lang}
                position={sessionContextMenu}
                session={contextMenuSession}
                t={t}
                onAddToReview={handleAddSessionToReview}
                onClearHistory={handleClearSessionHistory}
                onDelete={handleDeleteSession}
                onOpenAgentConfig={openSessionAgentConfig}
                onRename={beginRenameSession}
              />
            </Suspense>
          ) : null}
        </>
      )}
    </>
  );

  return (
    <div
      ref={layoutRef}
      className={chatLayoutClassName}
      style={layoutStyle}
      data-chat-responsive-mode={responsiveLayout.mode}
      data-chat-status-rail={statusRailCollapsed ? "collapsed" : "visible"}
    >
      {responsiveOverlayOpen ? (
        <VButton
          type="button"
          className={styles.overlayBackdrop}
          aria-label={lang === "zh" ? "关闭侧栏" : "Close side panel"}
          onClick={closeResponsiveOverlayPane}
        >
          <span className="sr-only">{lang === "zh" ? "关闭侧栏" : "Close side panel"}</span>
        </VButton>
      ) : null}
      <ChatStatusRail
        statusRailClassName={statusRailClassName}
        statusRailCollapsed={statusRailCollapsed}
        statusRailOverlayOpen={statusRailOverlayOpen}
        standardGroupRoomActive={standardGroupRoomActive}
        lang={lang}
        t={t}
        numberFormatter={numberFormatter}
        activeGroupRoom={activeGroupRoom}
        activeGroupTeamOwned={activeGroupTeamOwned}
        activeGroupTeam={activeGroupTeam}
        availableGroupParticipantCount={availableGroupParticipantCount}
        statusLabel={statusLabel}
        groupManageChanged={groupManageChanged}
        groupManageDisabled={groupManageDisabled}
        groupDeleteDisabled={groupDeleteDisabled}
        groupResetDisabled={groupResetDisabled}
        groupRoundActive={groupRoundActive}
        groupRoundRunning={groupRoundRunning}
        groupRoomActionError={groupRoomActionError}
        setGroupRoomActionError={setGroupRoomActionError}
        groupManageTitleDraft={groupManageTitleDraft}
        setGroupManageTitleDraft={setGroupManageTitleDraft}
        groupManageModeDraft={groupManageModeDraft}
        setGroupManageModeDraft={setGroupManageModeDraft}
        groupManagePurposeDraft={groupManagePurposeDraft}
        setGroupManagePurposeDraft={setGroupManagePurposeDraft}
        readyChatRoomModes={readyChatRoomModes}
        availableChatRoomPurposes={availableChatRoomPurposes}
        chatRoomModeLabel={chatRoomModeLabel}
        chatRoomPurposeLabel={chatRoomPurposeLabel}
        groupManageSessionIds={groupManageSessionIds}
        groupManageSessionSet={groupManageSessionSet}
        sessions={sessionsQuery.data}
        agentsById={agentsById}
        resolveModelLabel={resolveModelLabel}
        renderAgentAvatar={renderAgentAvatar}
        avatarInitials={avatarInitials}
        agentRoleClass={agentRoleClass}
        avatarImageUrlFrom={avatarImageUrlFrom}
        updateGroupRoomPending={updateGroupRoomMutation.isPending}
        deleteGroupRoomPending={deleteGroupRoomMutation.isPending}
        resetGroupRoomPending={resetGroupRoomMutation.isPending}
        onOpenTeam={(teamId) => navigate(`/teams?team=${encodeURIComponent(teamId)}`)}
        onApplyGroupRoomManagement={handleApplyGroupRoomManagement}
        onDeleteActiveGroupRoom={handleDeleteActiveGroupRoom}
        onResetActiveGroupRoom={handleResetActiveGroupRoom}
        onToggleGroupManageSession={handleToggleGroupManageSession}
        activeSurfaceTitle={activeSurfaceTitle}
        sessionStateValue={sessionStateValue}
        sessionStateLabel={sessionStateLabel}
        sessionStateLine={sessionStateLine}
        compactSessionStateLine={compactSessionStateLine}
        agentDirectSessionMismatch={agentDirectSessionMismatch}
        agentPrimaryDirectSessionId={agentPrimaryDirectSessionId}
        sessionBindingMismatchLine={sessionBindingMismatchLine}
        onOpenDirectSession={handleOpenDirectSession}
        sessionCompactRows={sessionCompactRows}
        activeSkillSummary={hasActiveSkill}
        activeSkillStatusStyle={activeSkillStatusStyle}
        activeSkillTitle={activeSkillTitle}
        activeSkillName={activeSkillName}
        activeSkillCommand={activeSkillCommand}
        activeSkillStatusLabel={activeSkillStatusLabel}
        activeSkillShortHash={activeSkillShortHash}
        mentalModelEnabledForNextTurn={mentalModelEnabledForNextTurn}
        activeSessionId={activeSessionId}
        onMentalModelEnabledChange={handleMentalModelEnabledChange}
        featurePresetState={featurePresetState}
        onToggleFeaturePreset={toggleFeaturePreset}
        cacheDetailAvailable={cacheDetailAvailable}
        cacheDetailOpen={cacheDetailOpen}
        cacheDetailOpenLabel={cacheDetailOpenLabel}
        tokenStatusMetrics={tokenStatusMetrics}
        onOpenCacheDetail={openCacheDetail}
        lastLlmPayloadTrace={lastLlmPayloadTrace}
        mentalCompactLine={mentalCompactLine}
        mentalSourceLabel={mentalSourceLabel}
        mentalCognitiveStateValue={mentalCognitiveStateValue}
        mentalStateLabel={mentalStateLabel}
        mentalSummary={mentalSummary}
        mentalWhisper={mentalWhisper}
        mentalCognitiveStateLabel={mentalCognitiveStateLabel}
        mentalConfidence={mentalConfidence}
        mentalRelativeTime={mentalRelativeTime}
        formatTime={formatTime}
        mental={mental}
        pet={pet}
        petPresetLabel={petPresetLabel}
        petCompactLine={petCompactLine}
        petAvatarSkinStyle={petAvatarSkinStyle}
        petAvatarSymbol={petAvatarSymbol}
        petVitals={petVitals}
        petInteractionLabels={petInteractionLabels}
        petActionPending={petActionMutation.isPending}
        petActionFeedback={petActionFeedback}
        onPetInteraction={handlePetInteraction}
      />

      {responsiveLayout.leftVisible ? <PaneCollapseHandle
        side="left"
        collapsed={conversationIndexCollapsed}
        separatorLabel={t("resizeLeftPanel")}
        collapseLabel={lang === "zh" ? "收起会话列" : "Collapse conversation column"}
        expandLabel={lang === "zh" ? "展开会话列" : "Expand conversation column"}
        className={`${styles.resizeHandle} ${styles.resizeHandleLeft}`}
        active={dragState?.side === "left"}
        activeClassName={styles.resizeHandleActive}
        onToggle={() => setLeftRailCollapsed((current) => !current)}
        onPointerDown={(event) => handleResizeStart("left", event)}
        onKeyDown={(event) => handleResizeKeyDown("left", event)}
      /> : null}

      <section className={centerPaneClassName}>
        <div className={styles.tabStrip}>
          <div className={styles.overlayPaneControls}>
            {!responsiveLayout.leftVisible ? (
              <VButton
                id="chat-conversation-index-toggle"
                type="button"
                className={styles.overlayPaneToggle}
                aria-expanded={conversationIndexOverlayOpen}
                aria-controls="chat-conversation-index-pane"
                onClick={() => setResponsiveOverlayPane((current) => current === "left" ? null : "left")}
              >
                {lang === "zh" ? "会话" : "Chats"}
              </VButton>
            ) : null}
            {!responsiveLayout.rightVisible ? (
              <VButton
                id="chat-status-toggle"
                type="button"
                className={styles.overlayPaneToggle}
                aria-expanded={statusRailOverlayOpen}
                aria-controls="chat-status-pane"
                onClick={() => setResponsiveOverlayPane((current) => current === "right" ? null : "right")}
              >
                {lang === "zh" ? "状态" : "Status"}
              </VButton>
            ) : null}
          </div>
          {chatReturnTarget ? (
            <Link className={styles.chatReturnLink} to={chatReturnTarget} title={chatReturnLabel}>
              <ArrowLeft size={14} aria-hidden="true" />
              <span>{chatReturnLabel}</span>
            </Link>
          ) : null}
          {groupPanelActive ? (
            <VButton
              type="button"
              className={`${styles.tab} ${styles.tabActive}`}
              onClick={() => undefined}
            >
              {projectBusActive ? (lang === "zh" ? "通知流" : "Notice stream") : (lang === "zh" ? "群聊" : "Group")}
            </VButton>
          ) : agentSessionTabs.length > 0 || cliAgentRunTabs.length > 0 ? (
            <>
            <AgentSessionTabStrip
              activeSessionId={activeSessionId}
              activeCliAgentRunId={activeCliAgentRunId}
              agentsById={agentsById}
              buildSessionReferencePayload={buildSessionReferencePayload}
              contextMenuSessionId={contextMenuSessionId}
              cliAgentRuns={cliAgentRunTabs}
              editingSessionId={editingSessionId}
              editingSessionTitle={editingSessionTitle}
              lang={lang}
              renamePending={renameSessionMutation.isPending}
              renameSessionId={renameSessionMutation.variables?.sessionId ?? ""}
              resolveModelLabel={resolveModelLabel}
              sessions={agentSessionTabs}
              statusLabel={statusLabel}
              t={t}
              workspaceActiveTab={workspace.activeTab}
              onCancelRename={cancelRenameSession}
              onContextMenu={openSessionContextMenu}
              onDragReference={startSessionReferenceDrag}
              onOpenCliAgentRun={(runId) => {
                if (activeSessionId) {
                  setActiveTab(activeSessionId, cliAgentRunTabId(runId));
                }
              }}
              onCloseCliAgentRun={(runId) => {
                const run = cliAgentRunTabs.find((item) => item.id === runId);
                if (run) {
                  void closeCliAgentRun(run);
                }
              }}
              onOpenDirectSession={handleOpenDirectSession}
              onRenameTitleChange={setEditingSessionTitle}
              onSetActiveTab={setActiveTab}
              onSubmitRename={submitRenameSession}
            />
            <VButton
              type="button"
              className={styles.tab}
              icon={<Plus size={14} />}
              onClick={handleCreateSession}
              isDisabled={createSessionMutation.isPending || !selectedChatAgentId}
              title={lang === "zh" ? "在当前 Agent 下新建会话" : "New session for current Agent"}
            >
              <span>{lang === "zh" ? "新建会话" : "New session"}</span>
            </VButton>
            </>
          ) : (
            <VButton
              type="button"
              className={workspace.activeTab === "agent" ? `${styles.tab} ${styles.tabActive}` : styles.tab}
              onClick={() => {
                activeSessionId && setActiveTab(activeSessionId, "agent");
              }}
            >
              {t("agentSession")}
            </VButton>
          )}
          <ChatFileWorkspaceTabs
            activeTab={workspace.activeTab}
            closePreviewTabLabel={t("closePreviewTab")}
            hidden={groupPanelActive}
            openTabs={workspace.openTabs}
            onCloseTab={(tabPath) => {
              activeSessionId && closePreviewTab(activeSessionId, tabPath);
            }}
            onOpenTab={(tabPath) => {
              activeSessionId && setActiveTab(activeSessionId, tabPath);
            }}
          />
        </div>

        <div className={styles.centerSurface}>
          <ChatCliAgentTerminalStack
            runs={mountedCliAgentRuns}
            activeCliAgentRunId={activeCliAgentRunId}
            activeSessionId={activeSessionId}
            groupPanelActive={groupPanelActive}
            lang={lang}
            TerminalPanel={CliAgentRunTerminalPanel}
            onTerminalSessionChange={handleCliAgentTerminalSessionChange}
          />
          {groupPanelActive ? (
            <ChatGroupCenterSurface
              lang={lang}
              projectBusActive={projectBusActive}
              standardGroupRoomActive={standardGroupRoomActive}
              activeGroupRoom={activeGroupRoom}
              activeGroupRoomId={activeGroupRoomId}
              availableGroupParticipantCount={availableGroupParticipantCount}
              activeGroupParticipantById={activeGroupParticipantById}
              projectBusTimeline={projectBusTimeline}
              projectBusEvents={projectBusEvents}
              projectBusDraft={projectBusDraft}
              projectBusInterruptTargets={projectBusInterruptTargets}
              groupTopicDraft={groupTopicDraft}
              groupRoomActionError={groupRoomActionError}
              groupRoundActive={groupRoundActive}
              groupRoundStopping={groupRoundStopping}
              groupStopDisabled={groupStopDisabled}
              expandedGroupMessageIds={expandedGroupMessageIds}
              chatMentionTargets={chatMentionTargets}
              userDisplayName={runtime?.userName || (lang === "zh" ? "我" : "Me")}
              projectBusRefreshing={projectAgentBusQuery.isFetching}
              projectBusRefreshError={projectAgentBusQuery.isError ? describeError(projectAgentBusQuery.error, t("loadFailed")) : ""}
              projectBusSendPending={sendProjectBusMessageMutation.isPending}
              projectBusRevokePending={revokeProjectBusMessageMutation.isPending}
              groupRoomRefreshing={activeGroupRoomQuery.isFetching}
              groupRoomRefreshError={activeGroupRoomQuery.isError ? describeError(activeGroupRoomQuery.error, t("loadFailed")) : ""}
              startGroupRoundPending={startGroupRoundMutation.isPending}
              stopGroupRoundPending={stopGroupRoundMutation.isPending}
              formatTime={formatTime}
              statusLabel={statusLabel}
              groupParticipantIdentity={groupParticipantIdentity}
              renderAgentAvatar={renderAgentAvatar}
              avatarInitials={avatarInitials}
              onProjectBusDraftChange={setProjectBusDraft}
              onProjectBusInterruptTargetsChange={setProjectBusInterruptTargets}
              onGroupTopicDraftChange={setGroupTopicDraft}
              onRefreshProjectBus={() => { void projectAgentBusQuery.refetch(); }}
              onRefreshGroupRoom={() => { if (activeGroupRoomId) void activeGroupRoomQuery.refetch(); }}
              onSendProjectBusMessage={handleSendProjectBusMessage}
              onRevokeProjectBusMessage={handleRevokeProjectBusMessage}
              onStartGroupRound={handleStartGroupRound}
              onStopGroupRound={handleStopGroupRound}
              onOpenMentionTarget={handleOpenMentionTarget}
              onToggleExpandedGroupMessage={(messageId) =>
                setExpandedGroupMessageIds((current) =>
                  current.includes(messageId)
                    ? current.filter((id) => id !== messageId)
                    : [...current, messageId],
                )
              }
            />
          ) : (
            <ChatSessionWorkspacePanel
              activeCliAgentRunAvailable={Boolean(activeCliAgentRun)}
              activeCliAgentRunId={activeCliAgentRunId}
              activeSessionId={activeSessionId}
              blockingErrorMessage={sessionDetailErrorMessage}
              cliAgentRunEmptyLabel={lang === "zh" ? "这个 CLI 工具页还没有可显示的运行记录。" : "This CLI tool page has no run to display."}
              conversation={detail ? {
                sessionId: activeSessionId ?? detail.id,
                title: detail.title,
                phase: detail.currentPhase,
                messages: detail.messages,
                activeTurnMessage,
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
                defaultFileContext: detail.defaultFileContext,
                showHeader: false,
                showSessionOverview: false,
                showMentalSnapshots: mentalModelEnabledForNextTurn,
                composer: conversationComposer,
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
              } : null}
              conversationFocused={statusRailCollapsed}
              filePreview={{
                changed: fileContentQuery.data ? changedFiles.has(fileContentQuery.data.path) : false,
                errorMessage: fileContentQuery.isError ? describeError(fileContentQuery.error, t("loadFailed")) : "",
                file: fileContentQuery.data,
                loadingLabel: t("loadingFilePreview"),
                sourceLabel: detail?.title ?? t("currentSession"),
              }}
              hasBlockingError={sessionDetailErrorState.blockingError}
              hasTransientError={sessionDetailErrorState.transientError}
              invalidChildSessionLinkMessage={invalidChildSessionLinkMessage}
              lang={lang}
              loadingSessionLabel={t("loadingSession")}
              noSessionsLabel={t("noSessionsYet")}
              notices={activeRuntimeNotices}
              sessionsPending={sessionsQuery.isPending}
              toolApproval={pendingToolApproval ? {
                pending: pendingToolApprovalPending,
                rawTitle: pendingToolApprovalRawTitle,
                riskLabel: pendingToolApprovalRisk,
                scopeLabel: pendingToolApprovalScope,
                toolLabels: pendingToolApprovalLabels,
              } : null}
              transientErrorMessage={sessionDetailErrorMessage}
              workspaceActiveTab={workspace.activeTab}
              onApproveToolApproval={() => {
                if (!pendingToolApproval) {
                  return;
                }
                resolveToolApprovalMutation.mutate({ request: pendingToolApproval, decision: "approve" });
              }}
              onRejectToolApproval={() => {
                if (!pendingToolApproval) {
                  return;
                }
                resolveToolApprovalMutation.mutate({ request: pendingToolApproval, decision: "reject" });
              }}
            />
          )}
        </div>
      </section>

      {responsiveLayout.rightVisible ? <PaneCollapseHandle
        side="right"
        collapsed={statusRailCollapsed}
        separatorLabel={t("resizeRightPanel")}
        collapseLabel={lang === "zh" ? "收起状态栏" : "Collapse status rail"}
        expandLabel={lang === "zh" ? "展开状态栏" : "Expand status rail"}
        className={`${styles.resizeHandle} ${styles.resizeHandleRight}`}
        active={dragState?.side === "right"}
        activeClassName={styles.resizeHandleActive}
        onToggle={() => setRightPaneCollapsed((current) => !current)}
        onPointerDown={(event) => handleResizeStart("right", event)}
        onKeyDown={(event) => handleResizeKeyDown("right", event)}
      /> : null}

      <ChatConversationIndexRail
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
        mentalModelEnabledForNextTurn={mentalModelEnabledForNextTurn}
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
      {cacheDetailOpen && cacheDetailAvailable ? (
        <Suspense fallback={null}>
          <CacheDetailDialog
            averageCacheObservedTurnCount={averageCacheObservedTurnCount}
            cacheCompositionAverageLabel={cacheCompositionAverageLabel}
            cacheCompositionAverageValue={cacheCompositionAverageValue}
            cacheCompositionPercent={cacheCompositionPercent}
            cacheCompositionTitle={cacheCompositionTitle}
            cacheCompositionUpperBoundLabel={cacheCompositionUpperBoundLabel}
            cacheComputedOverestimatedInputTokens={cacheComputedOverestimatedInputTokens}
            cacheDetailDialogTitle={cacheDetailDialogTitle}
            cachePromptCompositionTotalTokens={cachePromptCompositionTotalTokens}
            cachePromptDonutSegments={cachePromptDonutSegments}
            cacheProviderExtraCachedInputTokens={cacheProviderExtraCachedInputTokens}
            cacheCalibrationReason={cacheCalibrationReason}
            cacheCalibrationSummaryText={cacheCalibrationSummaryText}
            closeLabel={lang === "zh" ? "关闭缓存详情" : "Close cache details"}
            lang={lang}
            missingSegmentLabel={cacheCompositionSegmentLabel("missing", "missing", t)}
            numberFormatter={numberFormatter}
            onClose={closeCacheDetail}
            previousCacheHitLabel={t("previousCacheHit")}
            providerCachedInputTokens={providerCachedInputTokens}
            providerCacheInputTokens={providerCacheInputTokens}
            trueCacheDonutSegments={trueCacheDonutSegments}
            upperBoundCachedInputTokens={upperBoundCachedInputTokens}
            upperBoundCacheCompositionPercent={upperBoundCacheCompositionPercent}
            upperBoundCacheInputTokens={upperBoundCacheInputTokens}
          />
        </Suspense>
      ) : null}
      {agentCreateWizardOpen ? (
        <Suspense fallback={null}>
          <AgentCreateWizardDialog
            open={agentCreateWizardOpen}
            triggerRef={agentCreateTriggerRef}
            triggerId="chat-agent-create-trigger"
            onClose={() => setAgentCreateWizardOpen(false)}
            onCreated={(agent) => {
              setSelectedAgentId(agent.agentId);
              setRightIndexPanel("conversations");
            }}
            onStartConversation={async (agent) => {
              if (!agent.directSessionId) return false;
              handleOpenAgent(agent);
              return true;
            }}
            onOpenAdvancedConfig={(agent) => {
              setAgentCreateWizardOpen(false);
              navigate(`/agents?agent=${encodeURIComponent(agent.agentId)}&pane=config&returnTo=${encodeURIComponent("/chat")}`);
            }}
          />
        </Suspense>
      ) : null}
    </div>
  );
}
