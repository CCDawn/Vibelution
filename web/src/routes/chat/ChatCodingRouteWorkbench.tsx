/**
 * Chat Coding workbench implementation (R01).
 * Entry re-export: web/src/routes/ChatCodingRoute.tsx
 * Prefer editing modules under web/src/routes/chat/ over growing this file.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type Query,
  type QueryFunctionContext,
  type QueryKey,
} from "@tanstack/react-query";
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
} from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { listSessionChildSessions, fetchSessionLlmOptions, listPendingSessionToolApprovals } from "../../api/chat";
import { archiveAgent, updateAgent } from "../../api/agents";
import {
  listVirtualHumanCompanionActivity,
  listVirtualHumanCompanions,
} from "../../api/agentPlugins";
import { fetchFileContent } from "../../api/files";
import { createChatWorkspaceCache } from "../chatWorkspaceCache";
import type { AgentArchiveResponse } from "../agentWorkspaceCache";
import { prefetchConversationView } from "../../components/conversation/prefetchConversationView";
import { queryKeys } from "../../api/queryKeys";
import {
  AgentInstance,
  ChatRoomDetail,
  FileContent,
  MentalStateSnapshot,
  PetActionResponse,
  ChatNextStateSignalSummary,
  SessionGuidanceMode,
  ConversationSummary,
  SessionDetail,
  SessionRuntimeNotice,
  SessionToolApprovalRequest,
    SessionLlmOptions,
    SessionSummary,
  SessionStreamEvent,
  SessionReferenceAttachment,
  SessionTurnAcceptedResponse,
  ConversationMessage,
  ToolCall,
  VirtualHumanCompanion,
} from "../../api/types";
import type { ConversationStreamingFramePaintMetrics } from "../../components/conversation/conversationStreamingMetrics";
import { shouldShowNextStateSignalInConversation } from "../../components/conversation/conversationNextStateSignal";
import { VButton, VContextualHint, VInput, VNativeInput, VStateSurface, VTooltip, type VButtonProps } from "../../components/vui";
import { collectBrowserPageSnapshot, postBrowserTelemetry } from "../../app/browserTelemetry";
import { startUserAction } from "../../app/userActionTelemetry";
import { getPageInstanceId } from "../../app/pageInstance";
import { usePageVisibility, useStartupWarmup } from "../../app/pollingPolicy";
import type { TranslationKey } from "../../i18n/dictionary";
import { PaneCollapseHandle } from "../../components/layout/PaneCollapseHandle";
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
  SESSION_INDEX_PAGE_SIZE,
  updateSessionSummaryCaches,
} from "../chatSessionIndexQuery";
import { isTempSessionId } from "../sessionOptimisticIds";
import {
  ACTIVE_INDEX_POLL_MS,
  resolveChatLiveQueryPolicy,
} from "../chatLiveQueryPolicy";
import { resolveChatSecondaryPollPolicy } from "../chatSecondaryPollPolicy";
import {
  resolveChatUserDisplayName,
} from "../chatCompactPanel";
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
  sessionAgentDisplayInfo,
} from "../agentDisplay";
import { AgentSessionTabStrip, type CliAgentRunTab } from "../AgentSessionTabStrip";
import {
  AgentConversationDirectory,
} from "../AgentConversationDirectory";
import { ConversationIndexTree } from "../ConversationIndexTree";
import { teamWorkspaceRoute } from "../teams/researchWorkspaceModel";
import {
  hasInvalidChildSessionLink,
  rootSessionIdFor,
  sessionToConversationSummary,
  useConversationIndexModel,
  conversationGroupLabel,
} from "../conversationIndexModel";
import {
  activeTurnTerminalRefreshKey,
  activeTurnLayerToConversationMessage,
  activeTurnLayerTextLength,
  isActiveTurnSettledByDetail,
  selectFirstUnpaintedRunningTool,
  setActiveTurnLayerForSession,
  toolStartToFirstPaintMs,
  runningToolPaintKeys,
  type ActiveTurnLayerState,
} from "../chatActiveTurnLayer";
import {
  isChildSession,
} from "../DirectSessionIndexItem";
import { agentCenterConfigRoute } from "../agentCenterRoutes";
import { useChatToolApprovalBridge } from "./useChatToolApprovalBridge";
import { useChatComposerBridgeState } from "./useChatComposerBridgeState";
import { useChatGroupRoomViewModel } from "./useChatGroupRoomViewModel";
import { ChatSessionWorkspacePanel } from "./ChatSessionWorkspacePanel";
import { ChatConversationIndexRail } from "./ChatConversationIndexRail";
import { ChatComposerPlusMenu } from "./ChatComposerPlusMenu";
import { ChatGroupManagementDialog } from "./ChatGroupManagementDialog";
import {
  chatStreamPerformanceNowMs,
  describeChatRouteError as describeError,
  isBusyPhase,
  MAX_LEFT_PANEL_WIDTH,
  MAX_RIGHT_PANEL_WIDTH,
  MIN_LEFT_PANEL_WIDTH,
  MIN_RIGHT_PANEL_WIDTH,
  formatChatRuntimeMismatchLine,
  runtimeMatchesSelectedChatSession,
} from "./chatCodingRouteViewModel";
import { ChatCenterSessionSurface } from "./ChatCenterSessionSurface";
import { ChatCenterTabStrip } from "./ChatCenterTabStrip";
import { ChatConversationIndexPanelContent } from "./ChatConversationIndexPanelContent";
import { SessionBulkOperationsPanel } from "./SessionBulkOperationsPanel";
import { ChatSessionWorkbenchShell } from "./ChatSessionWorkbenchShell";
import { CompanionConversationHeader } from "../companions/CompanionConversationHeader";
import { CompanionLifeRail } from "../companions/CompanionLifeRail";
import { CompanionPersonRail, type CompanionRailState } from "../companions/CompanionPersonRail";
import {
  companionAgentIdForDirectSession,
  sessionsForChatRoute,
} from "../companions/companionChatRouteIsolation";
import { ChatWorkbenchCenterColumn } from "./ChatWorkbenchCenterColumn";
import { useChatWorkbenchLayout } from "./useChatWorkbenchLayout";
import {
  useChatLocaleFormatters,
  useChatReturnNavigation,
} from "./useChatWorkbenchPresentation";
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
import { useChatRouteSelection } from "./useChatRouteSelection";
import {
  activeGroupRoomIdFromRouteSelection,
  activeSessionIdFromRouteSelection,
} from "./chatSelectionProjection";
import { resolveAuthoritativeArchivedSessionIds } from "./chatSessionRouteSync";
import {
  remainingAgentsAfterConfirmedArchive,
  restoreOptimisticallyArchivedAgent,
  useChatAgentArchiveQueue,
} from "./useChatAgentArchiveQueue";
import { useChatArchivedAgentRetirement } from "./useChatArchivedAgentRetirement";
import { useChatSelectionPersistence } from "./useChatSelectionPersistence";
import { useChatWorkspaceLifecycle } from "./useChatWorkspaceLifecycle";
import { useChatSessionDetailMutations } from "./useChatSessionDetailMutations";
import { useChatWorkspaceActions } from "./useChatWorkspaceActions";
import { ChatDangerConfirmDialog } from "./ChatDangerConfirmDialog";
import { useChatSessionBulkSelection } from "./useChatSessionBulkSelection";
import { useChatWorkbenchConfirmDialog } from "./useChatWorkbenchConfirmDialog";
import { useChatVisibleSessionCatalog } from "./useChatVisibleSessionCatalog";
import { useChatAgentSessionTabs } from "./useChatAgentSessionTabs";
import { toSessionIndexProgressQuerySlice, useChatSessionIndexRailModel } from "./useChatSessionIndexRailModel";
import { useChatGroupRoomChromeModel } from "./useChatGroupRoomChromeModel";
import { useChatAgentDirectoryMaps } from "./useChatAgentDirectoryMaps";
import { useChatIndexDerivedState } from "./useChatIndexDerivedState";
import { useDesktopConversationAttention } from "./useDesktopConversationAttention";
import { ChatCliAgentTerminalStack } from "./ChatCliAgentTerminalStack";
import { useChatSessionRenameMenu } from "./useChatSessionRenameMenu";
import { useChatAgentDirectoryActions } from "./useChatAgentDirectoryActions";
import { useChatCliAgentTerminal } from "./useChatCliAgentTerminal";
import { buildChatCacheDetailViewModel } from "./chatCacheDetailModel";
import { buildComposerContextRingModel } from "./composerContextModel";
import { useChatCacheDetailDialog } from "./useChatCacheDetailDialog";
import { useAgentPermissionPresetMutation } from "./useAgentPermissionPresetMutation";
import { useChatWorkbenchCatalogQueries } from "./useChatWorkbenchCatalogQueries";
import {
  useChatGroupDraftState,
  useSyncChatGroupManageDrafts,
} from "./useChatGroupDraftState";
import { useChatWorkbenchContextMenus } from "./useChatWorkbenchContextMenus";
import { useChatConversationIndexChrome } from "./useChatConversationIndexChrome";
import {
  chatTurnSessionIdsFromRuntime,
  runtimeHasChatTurnForSession,
} from "./chatRuntimeWorkRuns";
import {
  buildChatActiveSkillViewModel,
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
  agentRoleClass,
  avatarInitials,
  avatarImageUrlFrom,
  renderAgentAvatar,
} from "./chatRoutePresentation";
import {
  SESSION_DETAIL_INITIAL_MESSAGE_LIMIT,
  SESSION_DETAIL_HISTORY_PAGE_SIZE,
  fetchSessionDetailWindow,
  isSessionDetailHardLoading,
  prefetchSessionDetailWindow,
  removeDeletedSessionFromConversations,
  mergeSessionDetailIntoConversations,
  resolveActiveSessionDetailForUi,
  resolveNeighborSessionIdsForPrefetch,
  resolveSessionDetailPlaceholder,
  sessionDetailSnapshotKey,
  isStaleLedgerUpdate,
  latestMentalSnapshot,
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

/** Secondary-lazy: open only when creating an Agent (keeps wizard graph out of Chat shell). */
const AgentCreateWizardDialog = lazy(() =>
  import("../agent-create/AgentCreateWizardDialog").then((module) => ({
    default: module.AgentCreateWizardDialog,
  })),
);

/** Secondary-lazy: cache donut dialog opens from status rail action. */
const CacheDetailDialog = lazy(() =>
  import("./CacheDetailDialog").then((module) => ({
    default: module.CacheDetailDialog,
  })),
);

/** Secondary-lazy: session row context menu. */
const SessionContextMenu = lazy(() =>
  import("../SessionContextMenu").then((module) => ({
    default: module.SessionContextMenu,
  })),
);

/** Secondary-lazy: Agent directory row context menu. */
const AgentRenameDialog = lazy(() =>
  import("../AgentRenameDialog").then((module) => ({
    default: module.AgentRenameDialog,
  })),
);
const AgentContextMenu = lazy(() =>
  import("../AgentContextMenu").then((module) => ({
    default: module.AgentContextMenu,
  })),
);

/** S2: not required for first paint of direct chat center. */
const ChatStatusRail = lazy(() =>
  import("./ChatStatusRail").then((module) => ({ default: module.ChatStatusRail })),
);
const ChatGroupCenterSurface = lazy(() =>
  import("./ChatGroupCenterSurface").then((module) => ({ default: module.ChatGroupCenterSurface })),
);
const ChatFileWorkspaceTabs = lazy(() =>
  import("./ChatFileWorkspaceTabs").then((module) => ({ default: module.ChatFileWorkspaceTabs })),
);

type SessionDetailWithActiveSkill = SessionDetail & {
  activeSkillContract?: ActiveSkillContract | null;
};

type PetInteractionAction = "feed" | "talk" | "care";

/**
 * Stable session-detail placeholder for the active-session detail query.
 *
 * React Query re-derives `placeholderData` while a detail fetch is pending
 * (`state.data === undefined`). The previous inline callback rebuilt
 * `resolveSessionDetailPlaceholder` output on every render, so each no-op
 * parent rerender handed the query observer a fresh placeholder reference
 * and session switches spiraled into "Maximum update depth exceeded" inside
 * React Query's `forceStoreRerender`. Memoizing keeps the placeholder
 * reference identical while `activeSessionId`, the cached detail, and the
 * list summary are unchanged, and recomputes only when one of those inputs
 * actually changes.
 */
export function useStableSessionDetailPlaceholder(options: {
  activeSessionId: string | null | undefined;
  cachedDetail: SessionDetail | undefined;
  summary: SessionSummary | null | undefined;
}): SessionDetail | undefined {
  const { activeSessionId, cachedDetail, summary } = options;
  return useMemo(
    () => resolveSessionDetailPlaceholder({ activeSessionId, cachedDetail, summary }),
    [activeSessionId, cachedDetail, summary],
  );
}

/**
 * Stable structural-sharing merge for the active session-detail query.
 *
 * React Query keeps the `structuralSharing` option reference across renders;
 * an inline arrow rebuilt on every render handed the observer a fresh callback
 * each time and drove `forceStoreRerender` into the "Maximum update depth
 * exceeded" loop. Hoisting the merge to module scope fixes the identity while
 * preserving the exact `mergeSessionDetailMessageWindow` previous/next merge
 * semantics.
 */
export function sessionDetailStructuralSharing(
  previous: unknown,
  next: unknown,
): SessionDetail {
  return mergeSessionDetailMessageWindow(previous as SessionDetail | undefined, next as SessionDetail);
}

/**
 * Polling inputs that drive the pending tool-approvals observer.
 *
 * Shared by `useSessionToolApprovalsRefetchInterval` (which maps them to a
 * stable resolver reference) and `useSessionToolApprovalsQuery` (which owns the
 * whole observer). Keeping the inputs as one stable shape means an unrelated
 * parent rerender with identical inputs recomputes nothing.
 */
export type SessionToolApprovalPollingInput = {
  directSessionPanelActive: boolean;
  runtimeActive: boolean;
  detailCurrentPhase: string | undefined;
  summaryCurrentPhase: string | undefined;
  summaryStatus: string | undefined;
};

/**
 * Stable refetchInterval resolver for the pending tool-approvals poll.
 *
 * React Query re-derives the `refetchInterval` option while a poll runs, and
 * the previous inline closure rebuilt on every render, so each no-op parent
 * rerender handed the observer a fresh callback and reset the 2s timer in
 * lockstep — the same "Maximum update depth exceeded" `forceStoreRerender`
 * churn seen with the placeholder and structural-sharing seams. Hoisting the
 * resolver into `useCallback` keeps the reference identical while the polling
 * inputs (panel activity, busy inputs, detail/summary status) are unchanged,
 * and recomputes only when one of those inputs actually changes.
 */
export function useSessionToolApprovalsRefetchInterval(
  options: SessionToolApprovalPollingInput,
): (query: Query<SessionToolApprovalRequest[]>) => number | false {
  const {
    directSessionPanelActive,
    runtimeActive,
    detailCurrentPhase,
    summaryCurrentPhase,
    summaryStatus,
  } = options;
  return useCallback(
    (query) => {
      if (!directSessionPanelActive) {
        return false;
      }
      const hasPending = (query.state.data?.length ?? 0) > 0;
      // Avoid 250ms thrash while busy (queues behind heavy session-detail under load).
      // Pending approvals still poll sub-second; busy-without-pending is lighter.
      const busy = runtimeActive
        || isBusyPhase(detailCurrentPhase || summaryCurrentPhase || summaryStatus);
      if (hasPending) {
        return 750;
      }
      if (busy) {
        return 2_000;
      }
      return 4_000;
    },
    [
      directSessionPanelActive,
      runtimeActive,
      detailCurrentPhase,
      summaryCurrentPhase,
      summaryStatus,
    ],
  );
}

/**
 * Stable queryFn for the pending tool-approvals observer.
 *
 * Module scope: React Query re-derives the `queryFn` option on every parent
 * render. The previous inline arrow rebuilt each time and handed the observer a
 * fresh callback reference, so each no-op rerender re-triggered the same
 * `forceStoreRerender` churn already fixed for the placeholder /
 * structural-sharing / refetchInterval seams. Reading the sessionId from the
 * queryKey keeps this a single stable reference while still routing to the
 * active session; switching sessions re-keys the query so only the new session
 * is ever fetched.
 */
export function sessionToolApprovalsQueryFn(
  context: QueryFunctionContext<QueryKey>,
): Promise<SessionToolApprovalRequest[]> {
  return listPendingSessionToolApprovals(String(context.queryKey[1] ?? ""));
}

export type SessionToolApprovalsQueryOptions = {
  sessionId: string | null | undefined;
  enabled: boolean;
  polling: SessionToolApprovalPollingInput;
};

/**
 * Stable observer seam for the pending tool-approvals poll.
 *
 * Owns the queryKey/queryFn/refetchInterval configuration so an unrelated
 * parent rerender with the same `sessionId` and polling inputs cannot hand the
 * observer a fresh query identity, queryFn, or refetch callback and restart the
 * poll timer / trigger extra fetches. The queryKey is memoized per `sessionId`
 * so the observer's identity reference is stable, the queryFn is a module-scope
 * function, and the refetch resolver is `useCallback`-stable. `inactive=false`,
 * `pending=750`, `busy=2000` and `idle=4000` all come from
 * `useSessionToolApprovalsRefetchInterval`.
 */
export function useSessionToolApprovalsQuery(options: SessionToolApprovalsQueryOptions) {
  const { sessionId, enabled, polling } = options;
  const refetchInterval = useSessionToolApprovalsRefetchInterval(polling);
  const queryKey = useMemo(() => queryKeys.sessionToolApprovals(sessionId ?? "none"), [sessionId]);
  return useQuery<SessionToolApprovalRequest[]>({
    queryKey,
    enabled,
    queryFn: sessionToolApprovalsQueryFn,
    refetchInterval,
    refetchIntervalInBackground: false,
  });
}

/**
 * Stable sticky session-detail paint for the active session.
 *
 * `resolveStickySessionDetailPaint` rebuilds the merged sticky+live detail
 * (including a brand-new `messages` array) on every call. Called inline during
 * render, an unrelated parent rerender with the same `activeSessionId` and the
 * same `rawSessionDetail` reference handed downstream effects a fresh
 * detail/messages reference each time; the token-speed effect depended on
 * `detail.messages` and called `setTokenSpeedTracker`, and a single React Query
 * observer notification restarted the whole cycle until React bailed out with
 * "Maximum update depth exceeded" inside `forceStoreRerender`. Memoizing keeps
 * the detail (and its `messages` array) reference strictly identical while both
 * inputs are unchanged, and recomputes only when `activeSessionId` or the
 * resolved raw detail actually changes, preserving the existing sticky
 * transcript semantics. A query observer can still replay an equivalent raw
 * detail with a new reference; `updateTokenSpeedTracker` treats an unchanged
 * token count as a state no-op so that replay cannot feed another render back
 * into this observer cycle.
 */
export function useStableSessionDetailPaint(options: {
  activeSessionId: string | null | undefined;
  detail: SessionDetail | undefined;
}): SessionDetail | undefined {
  const { activeSessionId, detail: rawSessionDetail } = options;
  return useMemo(
    () => resolveStickySessionDetailPaint({ activeSessionId, detail: rawSessionDetail }),
    [activeSessionId, rawSessionDetail],
  );
}

export function ChatCodingRoute() {
  // pet + evolution: companion rail shows mental/pet labels (otherwise raw keys leak).
  const { lang, t, statusLabel } = useAppI18n({ domains: ["chat", "agents", "pet", "evolution"] });
  const queryClient = useQueryClient();
  const chatWorkspaceCache = useMemo(() => createChatWorkspaceCache(queryClient), [queryClient]);
  const navigate = useNavigate();
  const location = useLocation();
  // Committed React Router URL is the single authority for the current Chat selection.
  const {
    selection: chatRouteSelection,
    openSession,
    openCompanionSession,
    openRoom,
    openProjectBus,
    canonicalizeBareRoute,
    replaceIfStillViewing,
  } = useChatRouteSelection();
  const activeSessionId = activeSessionIdFromRouteSelection(chatRouteSelection) || null;
  const activeGroupRoomId = activeGroupRoomIdFromRouteSelection(chatRouteSelection);
  const routeSelectionRef = useRef(chatRouteSelection);
  routeSelectionRef.current = chatRouteSelection;
  const sessionWorkspaces = useChatWorkbenchStore((state) => state.sessionWorkspaces);
  const hydrateSession = useChatWorkbenchStore((state) => state.hydrateSession);
  const removeSessionWorkspace = useChatWorkbenchStore((state) => state.removeSession);
  const closePreviewTab = useChatWorkbenchStore((state) => state.closePreviewTab);
  const latestDirectSessionSelectionRef = useRef("");
  const latestDirectSessionSelectionAtRef = useRef(0);
  const directSessionSelectionGenerationRef = useRef(0);
  const retiredDirectSessionIdsRef = useRef<ReadonlySet<string>>(new Set());
  const setActiveTab = useChatWorkbenchStore((state) => state.setActiveTab);
  const [sessionFilter, setSessionFilter] = useState("");
  const imageUploadInFlightRef = useRef<Record<string, boolean>>({});
  const [sessionDrafts, setSessionDrafts] = useState<Record<string, string>>({});
  const [sessionFollowupQueues, setSessionFollowupQueues] = useState<Record<string, Array<{ id: string; text: string }>>>({});
  const [sessionComposerErrors, setSessionComposerErrors] = useState<Record<string, string>>({});
  const composerFocusSequenceRef = useRef(0);
  const [composerFocusRequest, setComposerFocusRequest] = useState({ sessionId: "", signal: "" });
  const requestSessionComposerFocus = useCallback((sessionId: string) => {
    const normalizedSessionId = String(sessionId || "").trim();
    if (!normalizedSessionId) {
      return;
    }
    composerFocusSequenceRef.current += 1;
    setComposerFocusRequest({
      sessionId: normalizedSessionId,
      signal: `delete:${normalizedSessionId}:${composerFocusSequenceRef.current}`,
    });
  }, []);
  const settleSessionComposerFocusRequest = useCallback((focusSignal: string) => {
    setComposerFocusRequest((current) => (
      current.signal === focusSignal
        ? { sessionId: "", signal: "" }
        : current
    ));
  }, []);
  const [sessionImageAttachments, setSessionImageAttachments] = useState<Record<string, ComposerImageAttachment[]>>({});
  const [sessionReferenceAttachments, setSessionReferenceAttachments] = useState<Record<string, SessionReferenceAttachment[]>>({});
  const [sessionImageUploadPending, setSessionImageUploadPending] = useState<Record<string, boolean>>({});
  const [sessionEditTargets, setSessionEditTargets] = useState<Record<string, { messageId: string; original: string }>>({});
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const editingSessionIdRef = useRef<string | null>(null);
  /** Suppress tab title blur-submit while create remaps temp id → server id. */
  const suppressRenameBlurUntilRef = useRef(0);
  const [editingSessionTitle, setEditingSessionTitle] = useState("");
  const editingSessionTitleRef = useRef("");
  const {
    sessionContextMenu,
    setSessionContextMenu,
    agentContextMenu,
    setAgentContextMenu,
  } = useChatWorkbenchContextMenus();
  const [activeTurnLayersBySession, setActiveTurnLayersBySession] = useState<Record<string, ActiveTurnLayerState>>({});

  useEffect(() => {
    editingSessionIdRef.current = editingSessionId;
  }, [editingSessionId]);
  useEffect(() => {
    editingSessionTitleRef.current = editingSessionTitle;
  }, [editingSessionTitle]);

  const [petActionFeedback, setPetActionFeedback] = useState("");
  const [mentalModelEnabledForNextTurn, setMentalModelEnabledForNextTurn] = useState<boolean>(
    () => readStoredMentalModelToggle() ?? false,
  );
  const [runtimeStatusEnabledForNextTurn, setRuntimeStatusEnabledForNextTurn] = useState<boolean>(
    () => readStoredRuntimeStatusToggle() ?? true,
  );
  const [groupManageDialogOpen, setGroupManageDialogOpen] = useState(false);
  const {
    groupComposerOpen,
    setGroupComposerOpen,
    groupTitleDraft,
    setGroupTitleDraft,
    groupModeDraft,
    setGroupModeDraft,
    groupPurposeDraft,
    setGroupPurposeDraft,
    groupSelectedAgentIds,
    setGroupSelectedAgentIds,
    groupTopicDraft,
    setGroupTopicDraft,
    projectBusDraft,
    setProjectBusDraft,
    projectBusInterruptTargets,
    setProjectBusInterruptTargets,
    groupRoomActionError,
    setGroupRoomActionError,
    groupManageTitleDraft,
    setGroupManageTitleDraft,
    groupManageSessionIds,
    setGroupManageSessionIds,
    groupManageModeDraft,
    setGroupManageModeDraft,
    groupManagePurposeDraft,
    setGroupManagePurposeDraft,
    groupManageSessionSet,
  } = useChatGroupDraftState();
  const [expandedGroupAgentSessionIds, setExpandedGroupAgentSessionIds] = useState<string[]>([]);
  const [expandedGroupMessageIds, setExpandedGroupMessageIds] = useState<string[]>([]);
  const lastConversationStreamingFrameTelemetryAtRef = useRef<Record<string, number>>({});
  const lastAssistantDeltaAppliedAtRef = useRef<Record<string, number>>({});
  const activeTurnLayersBySessionRef = useRef<Record<string, ActiveTurnLayerState>>({});
  // ConversationView reports its committed frame from a child effect. React
  // runs that effect before this parent's effects, so effect-based ref syncing
  // leaves paint telemetry one render behind. Keep the read-through ref current
  // during render so a newly-started tool is measured on its first painted frame.
  activeTurnLayersBySessionRef.current = activeTurnLayersBySession;
  const paintedRunningToolIdsBySessionRef = useRef<Record<string, string[]>>({});
  const firstPaintedRunningToolAtBySessionRef = useRef<Record<string, Record<string, number>>>({});
  const terminalIndexRefreshKeysBySessionRef = useRef<Record<string, string>>({});
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
  const requestedCompanionId = useMemo(() => {
    return String(new URLSearchParams(location.search).get("companion") || "").trim();
  }, [location.search]);
  const workflowSessionAnchor = useMemo(() => {
    // Task 7: exact node session anchors — never invent agent default DM.
    try {
      // Lazy import path kept pure for tests; inline parse avoids circular route deps.
      const params = new URLSearchParams(location.search);
      const sessionId = (params.get("session") || "").trim();
      const focusTask = (params.get("focusTask") || "").trim();
      const focusTurn = (params.get("focusTurn") || "").trim();
      if (!sessionId) return null;
      if (!focusTask || !focusTurn) {
        return { degraded: true as const, sessionId, reason: !focusTask ? "missing_focus_task" : "missing_focus_turn" };
      }
      return { degraded: false as const, sessionId, focusTask, focusTurn };
    } catch {
      return null;
    }
  }, [location.search]);
  useEffect(() => {
    if (!workflowSessionAnchor || workflowSessionAnchor.degraded) {
      return;
    }
    const turn = workflowSessionAnchor.focusTurn;
    const task = workflowSessionAnchor.focusTask;
    const tryFocus = () => {
      const byTurn =
        document.querySelector(`[data-turn-id="${CSS.escape(turn)}"]`)
        || document.querySelector(`[data-message-id="${CSS.escape(turn)}"]`);
      const byTask = document.querySelector(`[data-task-id="${CSS.escape(task)}"]`);
      const el = (byTurn || byTask) as HTMLElement | null;
      if (el && typeof el.scrollIntoView === "function") {
        el.scrollIntoView({ block: "center", behavior: "smooth" });
        el.setAttribute("data-workflow-anchor-focus", "true");
        return true;
      }
      return false;
    };
    if (tryFocus()) return;
    const timer = window.setTimeout(() => {
      tryFocus();
    }, 600);
    return () => window.clearTimeout(timer);
  }, [workflowSessionAnchor, activeSessionId]);
  const { chatReturnTarget, chatReturnLabel } = useChatReturnNavigation(location.search, lang);
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
  const companionMode = Boolean(requestedCompanionId && requestedSessionId && !requestedRoomId);
  const companionRouteUpgradeLookupEnabled = Boolean(
    requestedSessionId && !requestedCompanionId && !requestedRoomId,
  );
  const companionRouteUpgradeQuery = useQuery({
    queryKey: queryKeys.virtualHumanCompanionActivity(),
    queryFn: listVirtualHumanCompanionActivity,
    enabled: companionRouteUpgradeLookupEnabled,
    staleTime: 5_000,
  });
  const companionsQuery = useQuery({
    queryKey: queryKeys.virtualHumanCompanions(),
    queryFn: listVirtualHumanCompanions,
    enabled: companionMode,
    refetchInterval: companionMode && pageVisible ? 30_000 : false,
  });
  const activeCompanion = useMemo<VirtualHumanCompanion | null>(() => {
    if (!companionMode) return null;
    return (companionsQuery.data ?? []).find((companion) => (
      companion.agentId === requestedCompanionId
      && companion.directSessionId === requestedSessionId
    )) ?? null;
  }, [companionMode, companionsQuery.data, requestedCompanionId, requestedSessionId]);
  const verifiedCompanionMode = Boolean(activeCompanion);
  const companionTransportAgentId = activeCompanion?.agentId;
  const companionRailState: CompanionRailState = companionsQuery.isPending && !companionsQuery.data
    ? "loading"
    : companionsQuery.isError && !companionsQuery.data
      ? "error"
      : activeCompanion
        ? "ready"
        : "missing";
  const companionRailError = companionsQuery.isError
    ? describeError(companionsQuery.error, lang === "zh" ? "人物状态载入失败" : "Failed to load companion")
    : "";
  const [chatStartupDataReady, setChatStartupDataReady] = useState(false);
  const [startupDetailSettledSessionId, setStartupDetailSettledSessionId] = useState("");
  const chatStartupWarmupActive = useStartupWarmup(chatStartupDataReady);
  const chatPollingVisible = pageVisible || chatStartupWarmupActive;
  const projectBusActive = chatRouteSelection.kind === "project_bus";
  const groupPanelActive = Boolean(activeGroupRoomId);
  const standardGroupRoomActive = groupPanelActive && !projectBusActive;
  const {
    collapsedConversationGroups,
    rightIndexPanel,
    setRightIndexPanel,
    toggleConversationGroup,
  } = useChatConversationIndexChrome({ standardGroupRoomActive });
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

  // Room / project-bus route commits sync panel chrome only (never navigation).
  useEffect(() => {
    if (chatRouteSelection.kind === "room" || chatRouteSelection.kind === "project_bus") {
      setRightIndexPanel("members");
      setRightPaneCollapsed(false);
      setGroupRoomActionError("");
    }
  }, [chatRouteSelection.kind, setGroupRoomActionError, setRightIndexPanel, setRightPaneCollapsed]);

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
  const activeSessionDetail = queryClient.getQueryData<SessionDetail>(queryKeys.session(activeSessionId || "none"));
  const sessionTitleForNotifications = (
    activeSessionDetail?.title
    || activeSessionDetail?.agentDisplayName
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
    viewedSessionId: activeSessionId || "",
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

  const {
    runtimeQuery,
    petQuery,
    configSummaryQuery,
    selectedAgentId,
    setSelectedAgentId,
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
    skillsQuery,
    slashCommandSuggestions,
    chatRoomModesQuery,
    chatRoomPurposesQuery,
    activeGroupRoomQuery,
    projectAgentBusQuery,
    expandedGroupAgentDetailQueries,
  } = useChatWorkbenchCatalogQueries({
    queryClient,
    secondaryChatDataEnabled,
    chatSecondaryPollPolicy,
    chatLiveQueryPolicy,
    sessionQueryText,
    activeSessionId: activeSessionId || "",
    activeGroupRoomId,
    expandedGroupAgentSessionIds,
    groupComposerOpen,
    standardGroupRoomActive,
    projectBusActive,
    chatPollingVisible,
    chatStartupWarmupActive,
    groupBackgroundSyncActive,
    groupStreamConnected,
    requestedSessionId,
    requestedRoomId,
  });
  const agentPermissionPresetMutation = useAgentPermissionPresetMutation({
    onSuccess: (_agent, input) => {
      setSessionComposerErrors((current) => ({
        ...current,
        [input.sessionId]: "",
      }));
    },
    onError: (error, input) => {
      setSessionComposerErrors((current) => ({
        ...current,
        [input.sessionId]: describeError(
          error,
          lang === "zh" ? "Agent 权限更新失败" : "Failed to update Agent permissions",
        ),
      }));
    },
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
    routeSessionId: activeSessionIdFromRouteSelection(chatRouteSelection),
    latestDirectSessionSelectionRef,
    latestDirectSessionSelectionAtRef,
    directSessionSelectionGenerationRef,
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

  // Pending self-evolution handoff payloads only fill a draft for the explicit
  // route target; they never select matchedSession || active || first.
  useEffect(() => {
    const pendingHandoff = loadPendingSelfEvolutionHandoff();
    if (!pendingHandoff || !sessionsQuery.data || sessionsQuery.data.length === 0) {
      return;
    }
    const matchedSession = sessionsQuery.data.find((item) => item.id === pendingHandoff.sessionId);
    const targetSessionId = matchedSession?.id || "";
    if (!targetSessionId) {
      return;
    }
    if (activeSessionId !== targetSessionId) {
      return;
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
  }, [activeSessionId, sessionsQuery.data]);

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
  const sessionDetailPlaceholder = useStableSessionDetailPlaceholder({
    activeSessionId,
    cachedDetail: queryClient.getQueryData<SessionDetail>(queryKeys.session(activeSessionId ?? "none")),
    summary: activeSessionId
      ? sessionsQuery.data?.find((session) => session.id === activeSessionId)
      : undefined,
  });
  const sessionDetailQuery = useQuery<SessionDetail>({
    queryKey: queryKeys.session(activeSessionId ?? "none"),
    // Temp create shells are local-only; never GET/stream them until rebased.
    enabled: Boolean(activeSessionId) && !isTempSessionId(activeSessionId),
    queryFn: ({ signal }) => fetchSessionDetailWindow(activeSessionId, {
      signal,
      // When SSE owns live transcript, skip expensive secondary lists on poll/refetch.
      // First paint still hydrates fully until stream ownership is true.
      includeSecondary: !chatLiveQueryPolicy.directSessionStreamOwnsLiveQueries,
    }),
    // Select + GET often race on switch; brief freshness avoids immediate double rebuild
    // when /select already wrote a windowed detail into the same query key.
    staleTime: 1_500,
    structuralSharing: sessionDetailStructuralSharing,
    placeholderData: sessionDetailPlaceholder,
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
    enabled: secondaryChatDataEnabled && Boolean(activeSessionId) && !isTempSessionId(activeSessionId),
    queryFn: () => fetchSessionLlmOptions(activeSessionId ?? ""),
    staleTime: 30_000,
  });
  // Explicit missing/archived session keeps its URL and renders the blocking
  // unavailable surface. Background misses must never fall back to another
  // session and must never navigate.
  const activeRootSessionId = rootSessionIdFor(sessionDetailQuery.data ?? directSessionActiveSummary);
  const childSessionLiveQueryPolicy = resolveChatLiveQueryPolicy({
    ...chatLiveQueryPolicyInput,
    activeRootSessionId: activeRootSessionId || "",
  });
  const childSessionsQuery = useQuery({
    queryKey: queryKeys.sessionChildSessions(activeRootSessionId || "none"),
    queryFn: () => listSessionChildSessions(activeRootSessionId),
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
    companionAgentId: companionTransportAgentId,
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
    bulkDeleteSessionsMutation,
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
    requestSessionComposerFocus,
    routeSelectionRef,
    chatRoute: {
      openSession,
      openRoom,
      replaceIfStillViewing,
    },
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
    editingSessionTitleRef,
    setEditingSessionId,
    setEditingSessionTitle,
    suppressRenameBlurUntilRef,
  });

  const renameAgentMutation = useMutation({
    mutationFn: (payload: { agentId: string; displayName: string }) =>
      updateAgent(payload.agentId, { displayName: payload.displayName }) as Promise<AgentInstance>,
    onMutate: async (payload) => {
      const telemetry = startUserAction("agent_rename", { agentId: payload.agentId });
      await queryClient.cancelQueries({ queryKey: queryKeys.agents() });
      const previousAgents = queryClient.getQueryData<AgentInstance[]>(queryKeys.agents());
      queryClient.setQueryData<AgentInstance[]>(queryKeys.agents(), (current) =>
        current?.map((agent) => agent.agentId === payload.agentId
          ? { ...agent, displayName: payload.displayName }
          : agent),
      );
      return { previousAgents, telemetry };
    },
    onSuccess: (updatedAgent, _variables, context) => {
      context?.telemetry?.succeeded({ agentId: updatedAgent.agentId });
      queryClient.setQueryData<AgentInstance[]>(queryKeys.agents(), (current) =>
        current?.map((agent) => agent.agentId === updatedAgent.agentId ? updatedAgent : agent),
      );
      setSessionComposerErrors((current) => ({ ...current, __sessions__: "" }));
      void chatWorkspaceCache.afterAgentRenamed(updatedAgent.agentId);
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, { agentId: variables.agentId });
      if (context?.previousAgents) {
        queryClient.setQueryData(queryKeys.agents(), context.previousAgents);
      }
      setSessionComposerErrors((current) => ({
        ...current,
        __sessions__: describeError(error, t("loadFailed")),
      }));
    },
  });

  const retireArchivedAgentSessions = useChatArchivedAgentRetirement({
    clearSessionTransientUiState,
    directSessionSelectionGenerationRef,
    forgetSessionDetailPaint,
    queryClient,
    removeSessionWorkspace,
    requestedSessionId,
    retiredDirectSessionIdsRef,
    setSelectedAgentId,
    setSessionComposerErrors,
    chatRoute: { replaceIfStillViewing },
  });

  const {
    enqueueArchive: enqueueAgentArchive,
    isAgentArchivePending,
    pendingAgentIds: pendingArchiveAgentIds,
  } = useChatAgentArchiveQueue({
    executeArchive: (agentId: string) => archiveAgent(agentId) as Promise<AgentArchiveResponse>,
    onOptimisticArchive: (agentId: string) => {
      void queryClient.cancelQueries({ queryKey: queryKeys.agents() });
      void queryClient.cancelQueries({ queryKey: queryKeys.sessions() });
      void queryClient.cancelQueries({ queryKey: queryKeys.conversations() });
      const currentAgents = queryClient.getQueryData<AgentInstance[]>(queryKeys.agents()) ?? [];
      const currentSessions = (
        queryClient.getQueryData<SessionSummary[]>(queryKeys.sessions())
        ?? sessionsQuery.data
        ?? []
      );
      const archivedAgentIndex = currentAgents.findIndex((agent) => agent.agentId === agentId);
      const archivedAgent = archivedAgentIndex >= 0 ? currentAgents[archivedAgentIndex] : null;
      const remainingAgents = currentAgents.filter((agent) => agent.agentId !== agentId);
      const archivedSessionIds = currentSessions
        .filter((session) => String(session.agentId || "").trim() === agentId)
        .map((session) => session.id);

      queryClient.setQueryData<AgentInstance[]>(queryKeys.agents(), remainingAgents);
      setAgentContextMenu(null);
      return {
        agent: archivedAgent,
        agentIndex: archivedAgentIndex,
        agents: currentAgents,
        sessions: currentSessions,
        optimisticArchivedSessionIds: archivedSessionIds,
      };
    },
    onArchiveSuccess: (_agentId, agent, context) => {
      const archivedSessionIds = resolveAuthoritativeArchivedSessionIds({
        optimisticSessionIds: context.optimisticArchivedSessionIds,
        archiveSummary: agent.archiveSummary,
      });
      queryClient.setQueryData<AgentInstance[]>(queryKeys.agents(), (current) =>
        current?.filter((item) => item.agentId !== agent.agentId),
      );
      // Another Agent may already be optimistically hidden while its FIFO
      // request is still pending. Keep it eligible as the semantic fallback
      // until its own archive succeeds.
      const remainingAgents = remainingAgentsAfterConfirmedArchive(context.agents, agent.agentId);
      retireArchivedAgentSessions({
        agentId: agent.agentId,
        archivedSessionIds,
        sessions: queryClient.getQueryData<SessionSummary[]>(queryKeys.sessions()) ?? context.sessions,
        remainingAgents,
      });
      setSessionComposerErrors((current) => ({
        ...current,
        __sessions__: "",
      }));
    },
    onArchiveFailure: (_agentId, error, context) => {
      queryClient.setQueryData<AgentInstance[]>(queryKeys.agents(), (current) =>
        restoreOptimisticallyArchivedAgent(current, {
          agent: context.agent,
          index: context.agentIndex,
        }),
      );
      setSessionComposerErrors((current) => ({
        ...current,
        __sessions__: describeError(error, t("loadFailed")),
      }));
    },
    onQueueDrained: async () => {
      try {
        await chatWorkspaceCache.afterAgentArchived();
      } catch (error) {
        setSessionComposerErrors((current) => ({
          ...current,
          __sessions__: describeError(error, t("loadFailed")),
        }));
      }
    },
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
  const groupRoomInitialLoading = Boolean(
    standardGroupRoomActive && activeGroupRoomQuery.isPending && !activeGroupRoomQuery.data,
  );
  useSyncChatGroupManageDrafts({
    activeGroupRoom,
    sessions: sessionsQuery.data,
    setGroupManageSessionIds,
    setGroupManageTitleDraft,
    setGroupManageModeDraft,
    setGroupManagePurposeDraft,
  });
  const {
    pendingConfirm,
    pendingConfirmPresentation,
    openDeleteSessionConfirm,
    openClearSessionHistoryConfirm,
    openDeleteGroupConfirm,
    openResetGroupConfirm,
    confirmPendingWorkbenchAction,
    dismissPendingConfirm,
  } = useChatWorkbenchConfirmDialog({
    activeGroupRoom,
    deleteSessionMutation,
    clearSessionHistoryMutation,
    deleteGroupRoomMutation,
    resetGroupRoomMutation,
    setSessionComposerErrors,
    lang,
    t,
  });
  const teams = teamsQuery.data?.teams ?? [];
  const {
    linkedTeamRoomIds,
    activeGroupTeam,
    activeGroupTeamOwned,
    availableGroupParticipants,
    availableGroupParticipantCount,
    activeGroupRound,
    groupRoundRunning,
    groupRoundStopping,
    groupRoundActive,
    activeGroupParticipantById,
    expandedGroupAgentDetailsBySessionId,
    groupManageChanged,
    groupManageDisabled,
    groupDeleteDisabled,
    groupResetDisabled,
    groupStopDisabled,
  } = useChatGroupRoomChromeModel({
    teams,
    activeGroupRoom,
    activeGroupRoomId,
    groupPanelActive,
    standardGroupRoomActive,
    expandedGroupAgentSessionIds,
    setExpandedGroupAgentSessionIds,
    expandedGroupAgentDetailQueries,
    groupManageTitleDraft,
    groupManageModeDraft,
    groupManagePurposeDraft,
    groupManageSessionIds,
    updateGroupRoomPending: updateGroupRoomMutation.isPending,
    deleteGroupRoomPending: deleteGroupRoomMutation.isPending,
    resetGroupRoomPending: resetGroupRoomMutation.isPending,
    stopGroupRoundPending: stopGroupRoundMutation.isPending,
  });

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
    if (groupPanelActive || !secondaryChatDataEnabled || !pageVisible || !sessionsQuery.data?.length) {
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
    const run = async () => {
      for (const sessionId of neighborIds) {
        if (cancelled) {
          return;
        }
        try {
          await prefetchSessionDetailWindow(queryClient, sessionId);
        } catch {
          return;
        }
      }
    };
    const idleRequest = (window as Window & {
      requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => number;
    }).requestIdleCallback;
    const handle = typeof idleRequest === "function"
      ? idleRequest(() => void run(), { timeout: 1_500 })
      : window.setTimeout(() => void run(), 280);
    return () => {
      cancelled = true;
      if (typeof idleRequest === "function") {
        (window as Window & { cancelIdleCallback?: (id: number) => void }).cancelIdleCallback?.(handle as number);
      } else {
        window.clearTimeout(handle as number);
      }
    };
  }, [activeSessionId, groupPanelActive, pageVisible, queryClient, secondaryChatDataEnabled, sessionsQuery.data]);


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
    queryFn: () => fetchFileContent(activeFilePath ?? ""),
  });

  const changedFiles = new Set(sessionDetailQuery.data?.changedFiles ?? []);

  const {
    locale,
    numberFormatter,
    formatTime,
    formatConversationIndexTime,
  } = useChatLocaleFormatters(lang);

  const runtime = runtimeQuery.data;
  const runtimeChatTurnSessionIds = useMemo(
    () => chatTurnSessionIdsFromRuntime(runtime),
    [runtime],
  );
  const runtimeActiveChatTurnSessionIds = useMemo(
    () => new Set(runtimeChatTurnSessionIds),
    [runtimeChatTurnSessionIds],
  );
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
  // Memoized seam: identical activeSessionId/rawSessionDetail must yield the same
  // detail/messages reference across unrelated parent rerenders.
  const detail = useStableSessionDetailPaint({
    activeSessionId,
    detail: rawSessionDetail,
  });
  const sessionToolApprovalRuntimeActive = runtimeHasChatTurnForSession(runtime, activeSessionId);
  const sessionToolApprovalsQuery = useSessionToolApprovalsQuery({
    sessionId: activeSessionId,
    enabled: Boolean(activeSessionId && directSessionPanelActive && !isTempSessionId(activeSessionId)),
    polling: {
      directSessionPanelActive,
      runtimeActive: sessionToolApprovalRuntimeActive,
      detailCurrentPhase: detail?.currentPhase,
      summaryCurrentPhase: directSessionActiveSummary?.currentPhase,
      summaryStatus: directSessionActiveSummary?.status,
    },
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
  const terminalIndexRefreshKey = activeTurnTerminalRefreshKey(activeTurnLayer, detail);
  const activeTurnMessage = useMemo(
    () => activeTurnSettledByDetail ? undefined : activeTurnLayerToConversationMessage(activeTurnLayer),
    [activeTurnLayer, activeTurnSettledByDetail],
  );
  useEffect(() => {
    if (!activeSessionId || !terminalIndexRefreshKey) {
      return;
    }
    if (terminalIndexRefreshKeysBySessionRef.current[activeSessionId] === terminalIndexRefreshKey) {
      return;
    }
    terminalIndexRefreshKeysBySessionRef.current = {
      ...terminalIndexRefreshKeysBySessionRef.current,
      [activeSessionId]: terminalIndexRefreshKey,
    };
    void Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.sessions() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.conversations() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.runtimeSummary() }),
    ]);
  }, [activeSessionId, queryClient, terminalIndexRefreshKey]);
  useEffect(() => {
    if (!activeSessionId || !activeTurnLayer || !activeTurnSettledByDetail || !detail) {
      return;
    }
    const settledTurnId = activeTurnLayer.turnId;
    void queryClient.refetchQueries({
      queryKey: queryKeys.session(activeSessionId),
      exact: true,
    }).then(() => {
      const canonicalDetail = queryClient.getQueryData<SessionDetail>(queryKeys.session(activeSessionId));
      if (!canonicalDetail) {
        return;
      }
      updateSessionSummaryCaches(queryClient, (sessions) =>
        mergeSessionDetailIntoSummaries(sessions, canonicalDetail),
      );
      reconcileAgentSessionDetailCache(queryClient, canonicalDetail);
    });
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
  }, [activeSessionId, activeTurnLayer, activeTurnSettledByDetail, detail, queryClient]);
  const handleConversationStreamingFramePaint = useCallback((metrics: ConversationStreamingFramePaintMetrics) => {
    const sessionId = String(metrics.sessionId || "").trim();
    if (!sessionId || sessionId !== activeSessionId) {
      return;
    }
    const now = Date.now();
    const paintedActiveTurn = activeTurnLayersBySessionRef.current[sessionId];
    const paintedToolSelection = selectFirstUnpaintedRunningTool(
      paintedActiveTurn,
      paintedRunningToolIdsBySessionRef.current[sessionId] ?? [],
    );
    const newlyPaintedRunningTool = paintedToolSelection.tool;
    const newlyPaintedRunningTools = paintedToolSelection.tools;
    const firstPaintedToolAtById = {
      ...(firstPaintedRunningToolAtBySessionRef.current[sessionId] ?? {}),
    };
    const runningPaintKeys = runningToolPaintKeys(paintedActiveTurn);
    runningPaintKeys.forEach(({ toolId, fallbackKey, ordinalKey }) => {
      [toolId, fallbackKey, ordinalKey].filter(Boolean).forEach((key) => {
        if (!Number.isFinite(firstPaintedToolAtById[key])) {
          firstPaintedToolAtById[key] = now;
        }
      });
    });
    firstPaintedRunningToolAtBySessionRef.current = {
      ...firstPaintedRunningToolAtBySessionRef.current,
      [sessionId]: firstPaintedToolAtById,
    };
    const lastLoggedAt = lastConversationStreamingFrameTelemetryAtRef.current[sessionId] ?? 0;
    if (now - lastLoggedAt < 1_000 && !newlyPaintedRunningTool) {
      return;
    }
    if (newlyPaintedRunningTools.length > 0) {
      const newlyPaintedFallbackKeys = paintedToolSelection.toolIds.flatMap((toolId) => {
        const keys = runningPaintKeys.find((key) => key.toolId === toolId);
        return keys ? [keys.fallbackKey, keys.ordinalKey] : [];
      }).filter(Boolean);
      paintedRunningToolIdsBySessionRef.current = {
        ...paintedRunningToolIdsBySessionRef.current,
        [sessionId]: Array.from(new Set([
          ...(paintedRunningToolIdsBySessionRef.current[sessionId] ?? []),
          ...paintedToolSelection.toolIds,
          ...newlyPaintedFallbackKeys,
        ])).slice(-64),
      };
    }
    const paintedAtMs = metrics.paintedAtMs || chatStreamPerformanceNowMs();
    const lastAssistantDeltaAppliedAtMs = lastAssistantDeltaAppliedAtRef.current[sessionId] ?? 0;
    const toolStartToBrowserPaintMs = newlyPaintedRunningTools.reduce((maximum, tool, index) => {
      const toolId = paintedToolSelection.toolIds[index];
      const paintKeys = runningPaintKeys.find((key) => key.toolId === toolId);
      const firstPaintCandidates = [
        firstPaintedToolAtById[toolId],
        firstPaintedToolAtById[paintKeys?.fallbackKey ?? ""],
        firstPaintedToolAtById[paintKeys?.ordinalKey ?? ""],
      ]
        .filter(Number.isFinite);
      const firstPaintedAt = firstPaintCandidates.length > 0 ? Math.min(...firstPaintCandidates) : undefined;
      return Math.max(maximum, toolStartToFirstPaintMs(tool, firstPaintedAt, now));
    }, 0);
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
        toolStartToBrowserPaintMs: Math.max(0, toolStartToBrowserPaintMs),
        activeStatusSource: paintedActiveTurn?.ledgerSeq ? "assistant_delta" : "optimistic_submit",
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
  const runtimeMatchesSelectedSession = runtimeMatchesSelectedChatSession({
    selectedSessionId: activeSessionId,
    activeRuntimeSessionId: activeSessionBootstrapQuery.data?.activeSessionId,
    activeWorkSessionIds: runtimeActiveChatTurnSessionIds,
  });
  const runtimeActiveChatTurnSessionId = runtimeChatTurnSessionIds[0] ?? "";
  const otherRunningSessionIds = runtimeChatTurnSessionIds.filter(
    (sessionId) => sessionId !== String(activeSessionId || "").trim(),
  );
  const runtimeMismatchLine = runtimeActiveChatTurnSessionId && !runtimeMatchesSelectedSession
    ? formatChatRuntimeMismatchLine({
      otherRunningSessionIds,
      resolveSessionLabel: (sessionId) =>
        sessionsQuery.data?.find((session) => session.id === sessionId)?.title || sessionId,
      lang,
    })
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
    cachePromptCompositionSegments,
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
  const composerContextRing = useMemo(() => {
    const usageUsed = lastContextComposition?.totalTokens ?? detail?.contextUsage?.used ?? 0;
    const usageLimit = lastContextComposition?.limitTokens ?? detail?.contextUsage?.limit ?? 0;
    return buildComposerContextRingModel({
      usageUsed,
      usageLimit,
      hitPercent: cacheCompositionPercent,
      detailAvailable: cacheDetailAvailable,
      segments: cachePromptCompositionSegments,
      lang,
    });
  }, [
    cacheCompositionPercent,
    cacheDetailAvailable,
    cachePromptCompositionSegments,
    detail?.contextUsage?.limit,
    detail?.contextUsage?.used,
    lang,
    lastContextComposition?.limitTokens,
    lastContextComposition?.totalTokens,
  ]);
  const {
    sessionIdsNeedingApproval,
    toolApproval,
    handleApproveToolApproval,
    handleApproveToolForSession,
    handleRejectToolApproval,
  } = useChatToolApprovalBridge({
    detail,
    sessionToolApprovals: sessionToolApprovalsQuery.data,
    activeSessionId,
    lang,
    resolveSessionToolApprovalMutation,
    resolveToolApprovalMutation,
  });
  const runtimeRunningSessionIds = useMemo(() => {
    const runningSessionIds = new Set(runtimeChatTurnSessionIds);
    Object.entries(activeTurnLayersBySession).forEach(([sessionId, layer]) => {
      if (layer.status === "pending" || layer.status === "running") {
        runningSessionIds.add(sessionId);
      }
    });
    return [...runningSessionIds];
  }, [activeTurnLayersBySession, runtimeChatTurnSessionIds]);
  const {
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
    sessionStopping,
    sessionBusy,
    composerDisabled,
    conversationComposer,
  } = useChatComposerBridgeState({
    activeSessionId,
    sessionDrafts,
    sessionFollowupQueues,
    sessionComposerErrors,
    sessionEditTargets,
    sessionImageAttachments,
    sessionReferenceAttachments,
    sessionImageUploadPending,
    detail,
    agents: agentsQuery.data,
    modelImageInputSupportById,
    lang,
    t,
    submitTurnMutation,
    editResubmitMutation,
    stopTurnMutation,
    sessionGuidanceMutation,
    activeTurnSettledByDetail,
  });
  const companionComposerDisabled = composerDisabled || (companionMode && !companionTransportAgentId);
  const companionConversationComposer = companionMode
    ? {
      ...conversationComposer,
      actionDisabled: companionComposerDisabled
        || submitPending
        || !conversationComposer.value.trim(),
      actionMode: "send" as const,
      attachmentInputDisabled: companionComposerDisabled
        || sessionBusy
        || conversationComposer.attachmentInputDisabled,
      disabled: companionComposerDisabled,
      pending: submitPending,
    }
    : conversationComposer;
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

  const {
    handleSubmitTurn,
    handleStopTurn,
    handleSubmitGuidance,
    handleFollowupQueueUpdate,
    handleFollowupQueueRemove,
    handleFollowupQueueMove,
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
    composerDisabled: companionComposerDisabled,
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
    companionAgentId: companionTransportAgentId,
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

  const {
    agentsById,
    archiveVisibleAgents,
    chatMentionTargets,
    resolveConversationTurnAvatar,
  } = useChatAgentDirectoryMaps({
    agents: agentsQuery.data,
    pendingArchiveAgentIds,
  });

  const routeVisibleSessions = useMemo(() => sessionsForChatRoute({
    sessions: sessionsQuery.data,
    agents: agentsQuery.data,
    companionRouteVerified: verifiedCompanionMode,
  }), [agentsQuery.data, sessionsQuery.data, verifiedCompanionMode]);

  const requestedCompanionAgentId = useMemo(() => (
    requestedCompanionId
      ? ""
      : companionAgentIdForDirectSession(companionRouteUpgradeQuery.data, requestedSessionId)
  ), [companionRouteUpgradeQuery.data, requestedCompanionId, requestedSessionId]);

  useEffect(() => {
    if (!requestedSessionId || requestedCompanionId || requestedRoomId || !requestedCompanionAgentId) {
      return;
    }
    openCompanionSession(requestedSessionId, requestedCompanionAgentId, {
      replace: true,
      returnLabel: lang === "zh" ? "人物大厅" : "Companion lobby",
      telemetrySource: "companion_route_upgrade",
    });
  }, [
    lang,
    openCompanionSession,
    requestedCompanionAgentId,
    requestedCompanionId,
    requestedRoomId,
    requestedSessionId,
  ]);

  const composerSessionReferenceOptions = useMemo(() =>
    (routeVisibleSessions ?? [])
      .filter((session) => session.id !== activeSessionId)
      .map((session) => {
        const sessionAgent = session.agentId ? agentsById.get(session.agentId) : undefined;
        const display = sessionAgentDisplayInfo(session, sessionAgent, lang, resolveModelLabel);
        return {
          id: session.id,
          title: String(session.taskTitle || session.resultCard?.title || session.title || session.id).trim(),
          meta: display.name,
          reference: buildSessionReferencePayload(session, display.name, session.taskSummary ?? ""),
        };
      }),
  [activeSessionId, agentsById, lang, resolveModelLabel, routeVisibleSessions]);

  const {
    allVisibleSessions,
    sessionsById,
    visibleChatAgents,
    activeSessionAgentId,
  } = useChatVisibleSessionCatalog({
    sessions: routeVisibleSessions,
    childSessions: childSessionsQuery.data,
    pendingArchiveAgentIds,
    archiveVisibleAgents,
    activeSessionId,
    detail,
    directSessionActiveSummary,
    sessionDetailAgentId: sessionDetailQuery.data?.agentId,
  });

  const { bareRouteBootstrapTarget } = useChatSelectionPersistence({
    selection: chatRouteSelection,
    serverSessionId: activeSessionBootstrapQuery.data?.activeSessionId,
    activeSessionAgentId,
    selectedAgentId,
    sessions: routeVisibleSessions,
  });

  // Bare `/chat` canonicalizes once per location key, only after the session
  // directory is authoritative. Explicit routes always skip bootstrap.
  useEffect(() => {
    if (!routeVisibleSessions) {
      return;
    }
    if (chatRouteSelection.kind !== "bare") {
      return;
    }
    if (!bareRouteBootstrapTarget) {
      return;
    }
    canonicalizeBareRoute(bareRouteBootstrapTarget);
  }, [bareRouteBootstrapTarget, canonicalizeBareRoute, chatRouteSelection.kind, routeVisibleSessions]);
  const selectedChatAgentId = selectedAgentId || activeSessionAgentId || visibleChatAgents[0]?.agentId || "";

  const {
    rightIndexSessions,
    agentSessionTabs,
  } = useChatAgentSessionTabs({
    queryClient,
    selectedChatAgentId,
    agentsById,
    allVisibleSessions,
    activeSessionId,
    secondaryChatDataEnabled,
    sessionsRefetchInterval: chatLiveQueryPolicy.sessionsRefetchInterval,
    directRefetchIntervalInBackground: chatLiveQueryPolicy.directRefetchIntervalInBackground,
  });

  const {
    groupCandidateAgents,
    readyChatRoomModes,
    availableChatRoomPurposes,
    activeGroupTeamMemberByAgentId,
    groupParticipantIdentity,
  } = useChatGroupRoomViewModel({
    archiveVisibleAgents,
    chatRoomModes: chatRoomModesQuery.data,
    chatRoomPurposes: chatRoomPurposesQuery.data,
    activeGroupTeam,
    agentsById,
    lang,
    resolveModelLabel,
    avatarImageUrlFrom,
  });
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
  const {
    groupedGroupConversations,
    groupedGroupConversationCount,
    sessionIndexHasMore,
    sessionIndexLoadMoreLabel,
    sessionIndexFullyLoadedLabel,
    sessionIndexProgressLabel,
    sessionIndexProgressVisible,
  } = useChatSessionIndexRailModel({
    groupedConversations,
    rawSessionsQuery: toSessionIndexProgressQuerySlice(rawSessionsQuery),
    lang,
    numberFormatter,
  });
  const {
    selectedBulkSessionIds,
    selectedBulkSessions,
    allVisibleSessionsSelected,
    bulkSessionPending,
    sessionBulkNotice,
    sessionBulkCopy,
    clearBulkSessions,
    selectVisibleBulkSessions,
    toggleBulkSession,
    bulkRemoveSessions,
    visibleDirectSessionIds,
  } = useChatSessionBulkSelection({
    filteredConversations,
    sessionsById,
    bulkDeleteSessionsMutation,
    isBusyPhase,
    lang,
    t,
  });
  const {
    handlePetInteraction,
    handleCreateSession,
    handleOpenProjectAgentBus,
    handleOpenDirectSession,
    handlePrefetchDirectSession,
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
    chatRoute: {
      openSession,
      openRoom,
      openProjectBus,
    },
    queryClient,
    chatWorkspaceCache,
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
    sessionsById,
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
    openDeleteSessionConfirm,
    openClearSessionHistoryConfirm,
    openDeleteGroupConfirm,
    openResetGroupConfirm,
  });

  useDesktopConversationAttention({
    sessions: allVisibleSessions,
    viewedSessionId: activeSessionId || "",
    notifierRef: desktopConversationNotifierRef,
    onOpenSession: handleOpenDirectSession,
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
    agentCreateWizardOpen,
    setAgentCreateWizardOpen,
    agentCreateTriggerRef,
  } = useChatAgentDirectoryActions({
    lang,
    navigate,
    createSessionPending: createSessionMutation.isPending,
    renameAgentPending: renameAgentMutation.isPending,
    isAgentArchivePending,
    createSession: (variables) => createSessionMutation.mutate(variables),
    renameAgent: (variables) => renameAgentMutation.mutate(variables),
    archiveAgent: (variables) => {
      enqueueAgentArchive(variables.agentId);
    },
    openDirectSession: handleOpenDirectSession,
    openAgent: handleOpenAgent,
    setAgentContextMenu,
    setSessionContextMenu,
    setSessionComposerErrors,
    renameAgentEmptyMessage: t("renameAgentEmpty"),
  });

  const {
    contextMenuSession,
    contextMenuSessionId,
    contextMenuDeletePending,
    contextMenuAddToReviewPending,
    contextMenuClearHistoryPending,
    contextMenuClearHistoryVisible,
    contextMenuAgentArchivePending,
    contextMenuDeleteDisabled,
    contextMenuAddToReviewDisabled,
    contextMenuClearHistoryDisabled,
    conversationIndexLoading,
  } = useChatIndexDerivedState({
    sessionContextMenu,
    sessionsById,
    deleteSessionMutation,
    addSessionToReviewMutation,
    clearSessionHistoryMutation,
    agentContextMenu,
    isAgentArchivePending,
    bootstrapIsLoading: activeSessionBootstrapQuery.isLoading,
    conversationsHasData: Boolean(conversationsQuery.data),
    conversationsIsLoading: conversationsQuery.isLoading,
    sessionsHasData: Boolean(sessionsQuery.data),
    sessionsIsLoading: sessionsQuery.isLoading,
    agentsHasData: Boolean(agentsQuery.data),
    agentsIsLoading: agentsQuery.isLoading,
    visibleSessionCount: allVisibleSessions.length,
  });
  const conversationIndexPanel = (
    <ChatConversationIndexPanelContent
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
        && archiveVisibleAgents.length === 0
        && filteredTeams.length === 0
        && filteredStandaloneGroupConversations.length === 0
        && allVisibleSessions.length === 0
      }
    >
          <AgentConversationDirectory
            activeAgentId={selectedChatAgentId}
            activeSessionId={activeSessionId}
            activeGroupRoomId={activeGroupRoomId}
            agents={archiveVisibleAgents}
            avatarInitials={avatarInitials}
            filterText={sessionFilter}
            formatTime={formatConversationIndexTime}
            lang={lang}
            resolveModelLabel={resolveModelLabel}
            runtimeRunningSessionIds={runtimeRunningSessionIds}
            sessions={allVisibleSessions}
            sessionIdsNeedingApproval={sessionIdsNeedingApproval}
            statusLabel={statusLabel}
            teams={teams}
            onContextMenu={openAgentContextMenu}
            onOpenAgent={(agent) => {
              if (!handleOpenAgent(agent)) {
                handleCreateAgentSession(agent);
              }
            }}
            onOpenGroupRoom={handleOpenGroupRoom}
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
                onDismiss={() => setAgentContextMenu(null)}
              />
            </Suspense>
          ) : null}
          {agentRenameDraft ? (
            <Suspense fallback={null}>
              <AgentRenameDialog
                draft={agentRenameDraft}
                lang={lang}
                pending={renameAgentMutation.isPending}
                onCancel={cancelAgentRename}
                onChange={setAgentRenameDraftName}
                onSubmit={submitAgentRename}
              />
            </Suspense>
          ) : null}
          {sessionBulkNotice ? (
            <div className={styles.panelNotice} role="status">{sessionBulkNotice.text}</div>
          ) : null}
          <SessionBulkOperationsPanel
            copy={sessionBulkCopy}
            selectedCount={selectedBulkSessions.length}
            visibleCount={visibleDirectSessionIds.length}
            allVisibleSelected={allVisibleSessionsSelected}
            pending={bulkSessionPending}
            onSelectVisible={selectVisibleBulkSessions}
            onClearSelection={clearBulkSessions}
            onRemove={() => { void bulkRemoveSessions(); }}
          />
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
            runtimeRunningSessionIds={runtimeRunningSessionIds}
            searchHasTerm={searchHasTerm}
            sessionComposerErrors={sessionComposerErrors}
            sessionIdsNeedingApproval={sessionIdsNeedingApproval}
            sessionsById={sessionsById}
            teams={teams}
            statusLabel={statusLabel}
            t={t}
            onCancelRename={cancelRenameSession}
            onContextMenu={openSessionContextMenu}
            onDragReference={startSessionReferenceDrag}
            onOpenDirectSession={handleOpenDirectSession}
            onPrefetchDirectSession={handlePrefetchDirectSession}
            onOpenGroupRoom={handleOpenGroupRoom}
            onRenameTitleChange={setEditingSessionTitle}
            onSubmitRename={submitRenameSession}
            onToggleConversationGroup={toggleConversationGroup}
            bulkSelectionEnabled
            selectedBulkSessionIds={selectedBulkSessionIds}
            bulkSelectLabel={lang === "zh" ? "选择会话" : "Select session"}
            onToggleBulk={toggleBulkSession}
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
                onDismiss={() => setSessionContextMenu(null)}
              />
            </Suspense>
          ) : null}
    </ChatConversationIndexPanelContent>
  );

  return (
    <ChatSessionWorkbenchShell
      layoutRef={layoutRef}
      className={chatLayoutClassName}
      style={layoutStyle}
      responsiveMode={responsiveLayout.mode}
      statusRailCollapsed={statusRailCollapsed}
      overlay={
      responsiveOverlayOpen ? (
        <VButton
          type="button"
          className={styles.overlayBackdrop}
          aria-label={lang === "zh" ? "关闭侧栏" : "Close side panel"}
          onClick={closeResponsiveOverlayPane}
        >
          <span className="sr-only">{lang === "zh" ? "关闭侧栏" : "Close side panel"}</span>
        </VButton>
      ) : null
      }
      statusRail={verifiedCompanionMode ? (
      <CompanionLifeRail
        className={statusRailClassName}
        collapsed={statusRailCollapsed}
        overlayOpen={statusRailOverlayOpen}
        companion={activeCompanion}
        state={companionRailState}
        errorMessage={companionRailError}
        lang={lang}
        onOpenLifeSteward={(stewardSessionId) => {
          openSession(stewardSessionId, {
            replace: false,
            telemetrySource: "virtual_human_life_steward",
          });
        }}
      />
      ) : (
      <Suspense fallback={null}>
      <ChatStatusRail
        statusRailClassName={statusRailClassName}
        statusRailCollapsed={statusRailCollapsed}
        statusRailOverlayOpen={statusRailOverlayOpen}
        standardGroupRoomActive={standardGroupRoomActive}
        groupRoomInitialLoading={groupRoomInitialLoading}
        groupRoomLoadError={activeGroupRoomQuery.isError ? describeError(activeGroupRoomQuery.error, t("loadFailed")) : ""}
        lang={lang}
        t={t}
        numberFormatter={numberFormatter}
        activeGroupRoom={activeGroupRoom}
        activeGroupTeamOwned={activeGroupTeamOwned}
        availableGroupParticipantCount={availableGroupParticipantCount}
        statusLabel={statusLabel}
        groupRoundRunning={groupRoundRunning}
        activeSurfaceTitle={activeSurfaceTitle}
        sessionStateValue={sessionStateValue}
        sessionStateLabel={sessionStateLabel}
        sessionStateLine={sessionStateLine}
        compactSessionStateLine={compactSessionStateLine}
        agentDirectSessionMismatch={agentDirectSessionMismatch}
        sessionBindingMismatchLine={sessionBindingMismatchLine}
        sessionCompactRows={sessionCompactRows}
        activeSkillSummary={hasActiveSkill}
        activeSkillStatusStyle={activeSkillStatusStyle}
        activeSkillTitle={activeSkillTitle}
        activeSkillName={activeSkillName}
        activeSkillCommand={activeSkillCommand}
        activeSkillStatusLabel={activeSkillStatusLabel}
        activeSkillShortHash={activeSkillShortHash}
        promptSnapshot={detail?.agentPromptSnapshot}
        promptAssembly={detail?.lastPromptAssembly}
        lastLlmPayloadTrace={lastLlmPayloadTrace}
        pet={pet}
        petPresetLabel={petPresetLabel}
        petCompactLine={petCompactLine}
        petAvatarSkinStyle={petAvatarSkinStyle}
        petAvatarSymbol={petAvatarSymbol}
        petVitals={petVitals}
        petInteractionLabels={petInteractionLabels}
        petActionPending={petActionMutation.isPending}
        petActionFeedback={petActionFeedback}
      />
      </Suspense>
      )}
      leftResizeHandle={
      responsiveLayout.leftVisible ? <PaneCollapseHandle
        side="left"
        collapsed={conversationIndexCollapsed}
        separatorLabel={t("resizeLeftPanel")}
        collapseLabel={lang === "zh" ? "收起会话列" : "Collapse conversation column"}
        expandLabel={lang === "zh" ? "展开会话列" : "Expand conversation column"}
        className={styles.resizeHandleLeft}
        active={dragState?.side === "left"}
        valueNow={leftPanelWidth}
        valueMin={MIN_LEFT_PANEL_WIDTH}
        valueMax={MAX_LEFT_PANEL_WIDTH}
        onToggle={() => setLeftRailCollapsed((current) => !current)}
        onPointerDown={(event) => handleResizeStart("left", event)}
        onKeyDown={(event) => handleResizeKeyDown("left", event)}
      /> : null
      }
      center={(
      <ChatWorkbenchCenterColumn
        className={centerPaneClassName}
        surfaceClassName={styles.centerSurface}
        tabStrip={(
          <ChatCenterTabStrip
            styles={styles}
            lang={lang}
            agentSessionLabel={t("agentSession")}
            chatReturnTarget={chatReturnTarget}
            chatReturnLabel={chatReturnLabel}
            groupPanelActive={groupPanelActive}
            projectBusActive={projectBusActive}
            showSessionTabs={!verifiedCompanionMode && Boolean(selectedChatAgentId || agentSessionTabs.length > 0 || cliAgentRunTabs.length > 0)}
            showAgentFallbackTab={!verifiedCompanionMode}
            companionHeader={verifiedCompanionMode && activeCompanion ? (
              <CompanionConversationHeader companion={activeCompanion} lang={lang} />
            ) : null}
            workspaceActiveTab={workspace.activeTab}
            leftOverlayVisible={responsiveLayout.leftVisible}
            rightOverlayVisible={responsiveLayout.rightVisible}
            conversationIndexOverlayOpen={conversationIndexOverlayOpen}
            statusRailOverlayOpen={statusRailOverlayOpen}
            onActivateAgentFallbackTab={() => {
              activeSessionId && setActiveTab(activeSessionId, "agent");
            }}
            onToggleLeftOverlay={() => setResponsiveOverlayPane((current) => current === "left" ? null : "left")}
            onToggleRightOverlay={() => setResponsiveOverlayPane((current) => current === "right" ? null : "right")}
            sessionTabs={(
              <AgentSessionTabStrip
                activeSessionId={activeSessionId}
                activeCliAgentRunId={activeCliAgentRunId}
                agentsById={agentsById}
                buildSessionReferencePayload={buildSessionReferencePayload}
                contextMenuSessionId={contextMenuSessionId}
                cliAgentRuns={cliAgentRunTabs}
                createPending={createSessionMutation.isPending}
                createDisabled={!selectedChatAgentId}
                deletePendingSessionId={
                  deleteSessionMutation.isPending
                    ? String(deleteSessionMutation.variables?.sessionId || "").trim()
                    : ""
                }
                editingSessionId={editingSessionId}
                editingSessionTitle={editingSessionTitle}
                lang={lang}
                renamePending={renameSessionMutation.isPending}
                renameSessionId={renameSessionMutation.variables?.sessionId ?? ""}
                resolveModelLabel={resolveModelLabel}
                sessions={agentSessionTabs}
                teams={teams}
                runtimeRunningSessionIds={runtimeRunningSessionIds}
                sessionIdsNeedingApproval={sessionIdsNeedingApproval}
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
                onCreateSession={handleCreateSession}
                onDeleteSession={handleDeleteSession}
                onOpenDirectSession={handleOpenDirectSession}
                onPrefetchDirectSession={handlePrefetchDirectSession}
                onRenameTitleChange={setEditingSessionTitle}
                onSetActiveTab={setActiveTab}
                onSubmitRename={submitRenameSession}
              />
            )}
            fileTabs={(
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
            )}
          />
        )}
        surface={(
          <ChatCenterSessionSurface
            terminal={(
              <ChatCliAgentTerminalStack
                runs={mountedCliAgentRuns}
                activeCliAgentRunId={activeCliAgentRunId}
                activeSessionId={activeSessionId}
                groupPanelActive={groupPanelActive}
                lang={lang}
                TerminalPanel={CliAgentRunTerminalPanel}
                onTerminalSessionChange={handleCliAgentTerminalSessionChange}
              />
            )}
            groupPanelActive={groupPanelActive}
            groupSurface={(
            <ChatGroupCenterSurface
              lang={lang}
              projectBusActive={projectBusActive}
              standardGroupRoomActive={standardGroupRoomActive}
              groupRoomInitialLoading={groupRoomInitialLoading}
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
              composerLeadingControl={standardGroupRoomActive && activeGroupRoom ? (
                <ChatComposerPlusMenu
                  lang={lang}
                  showAddReference={false}
                  showCapabilities={false}
                  attachmentDisabled
                  sessionReferences={[]}
                  mentalModelEnabled={mentalModelEnabledForNextTurn}
                  runtimeStatusEnabled={runtimeStatusEnabledForNextTurn}
                  capabilityDisabled
                  onMentalModelEnabledChange={handleMentalModelEnabledChange}
                  onRuntimeStatusEnabledChange={handleRuntimeStatusEnabledChange}
                  group={{
                    title: activeGroupRoom.title,
                    onManage: () => setGroupManageDialogOpen(true),
                    teamId: activeGroupTeamOwned ? activeGroupTeam?.teamId : undefined,
                    onOpenTeam: activeGroupTeamOwned && activeGroupTeam
                      ? () => navigate(teamWorkspaceRoute(activeGroupTeam.teamId))
                      : undefined,
                  }}
                />
              ) : undefined}
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
            )}
            sessionWorkspace={(
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
                companionMode: verifiedCompanionMode,
                // Historical mental snapshots are conversation evidence; next-turn toggle only affects submit.
                showMentalSnapshots: !verifiedCompanionMode,
                composerFocusSignal:
                  composerFocusRequest.sessionId === activeSessionId
                    ? composerFocusRequest.signal
                    : "",
                onComposerFocusRequestSettled: settleSessionComposerFocusRequest,
                composer: companionConversationComposer,
                composerLeadingControl: verifiedCompanionMode ? undefined : (
                  <ChatComposerPlusMenu
                    lang={lang}
                    attachmentDisabled={companionConversationComposer.attachmentInputDisabled}
                    onAddAttachments={handleAddComposerAttachments}
                    sessionReferences={composerSessionReferenceOptions}
                    onAddSessionReference={handleAddComposerReference}
                    mentalModelEnabled={mentalModelEnabledForNextTurn}
                    runtimeStatusEnabled={runtimeStatusEnabledForNextTurn}
                    capabilityDisabled={!activeSessionId}
                    onMentalModelEnabledChange={handleMentalModelEnabledChange}
                    onRuntimeStatusEnabledChange={handleRuntimeStatusEnabledChange}
                    directSession={agentDirectSessionMismatch && agentPrimaryDirectSessionId ? {
                      id: agentPrimaryDirectSessionId,
                      label: sessionBindingMismatchLine,
                      onOpen: () => handleOpenDirectSession(agentPrimaryDirectSessionId),
                      onPrefetch: () => handlePrefetchDirectSession(agentPrimaryDirectSessionId),
                    } : null}
                    companion={pet ? {
                      name: pet.name,
                      pending: petActionMutation.isPending,
                      onAction: handlePetInteraction,
                    } : null}
                    group={standardGroupRoomActive && activeGroupRoom ? {
                      title: activeGroupRoom.title,
                      onManage: () => setGroupManageDialogOpen(true),
                      teamId: activeGroupTeamOwned ? activeGroupTeam?.teamId : undefined,
                      onOpenTeam: activeGroupTeamOwned && activeGroupTeam
                        ? () => navigate(teamWorkspaceRoute(activeGroupTeam.teamId))
                        : undefined,
                    } : null}
                  />
                ),
                permissionControl: !verifiedCompanionMode && activeSessionAgent ? {
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
                llmControl: verifiedCompanionMode ? undefined : sessionLlmControl,
                composerContextRing: verifiedCompanionMode ? null : composerContextRing,
                onOpenComposerContextDetail: !verifiedCompanionMode && cacheDetailAvailable ? openCacheDetail : undefined,
                slashCommandSuggestions: verifiedCompanionMode ? [] : slashCommandSuggestions,
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
                onFollowupQueueUpdate: handleFollowupQueueUpdate,
                onFollowupQueueRemove: handleFollowupQueueRemove,
                onFollowupQueueMove: handleFollowupQueueMove,
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
              toolApproval={toolApproval}
              transientErrorMessage={sessionDetailErrorMessage}
              workspaceActiveTab={workspace.activeTab}
              onApproveToolApproval={handleApproveToolApproval}
              onApproveToolForSession={handleApproveToolForSession}
              onRejectToolApproval={handleRejectToolApproval}
            />
            )}
          />
        )}
      />
      )}
      rightResizeHandle={
      responsiveLayout.rightVisible ? <PaneCollapseHandle
        side="right"
        collapsed={statusRailCollapsed}
        separatorLabel={t("resizeRightPanel")}
        collapseLabel={lang === "zh" ? "收起状态栏" : "Collapse status rail"}
        expandLabel={lang === "zh" ? "展开状态栏" : "Expand status rail"}
        className={styles.resizeHandleRight}
        active={dragState?.side === "right"}
        valueNow={rightPanelWidth}
        valueMin={MIN_RIGHT_PANEL_WIDTH}
        valueMax={MAX_RIGHT_PANEL_WIDTH}
        onToggle={() => setRightPaneCollapsed((current) => !current)}
        onPointerDown={(event) => handleResizeStart("right", event)}
        onKeyDown={(event) => handleResizeKeyDown("right", event)}
      /> : null
      }
      conversationIndex={verifiedCompanionMode ? (
      <CompanionPersonRail
        className={conversationIndexPaneClassName}
        collapsed={conversationIndexCollapsed}
        overlayOpen={conversationIndexOverlayOpen}
        companion={activeCompanion}
        state={companionRailState}
        errorMessage={companionRailError}
        lang={lang}
      />
      ) : (
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
        groupRoomInitialLoading={groupRoomInitialLoading}
        groupRoomLoadError={activeGroupRoomQuery.isError ? describeError(activeGroupRoomQuery.error, t("loadFailed")) : ""}
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
        sessionBulkSelectVisibleVisible={selectedBulkSessions.length === 0 && visibleDirectSessionIds.length > 0}
        sessionBulkSelectVisibleLabel={t("bulkSelectVisibleSessions")}
        onSessionBulkSelectVisible={selectVisibleBulkSessions}
        sessionBulkSelectVisibleDisabled={bulkSessionPending || conversationIndexLoading}
      />
      )}
    >
      <ChatGroupManagementDialog
        open={groupManageDialogOpen}
        onOpenChange={setGroupManageDialogOpen}
        lang={lang}
        activeGroupRoom={activeGroupRoom}
        activeGroupTeamOwned={activeGroupTeamOwned}
        activeGroupTeam={activeGroupTeam}
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
        onOpenTeam={(teamId) => navigate(teamWorkspaceRoute(teamId))}
        onApplyGroupRoomManagement={handleApplyGroupRoomManagement}
        onDeleteActiveGroupRoom={handleDeleteActiveGroupRoom}
        onResetActiveGroupRoom={handleResetActiveGroupRoom}
        onToggleGroupManageSession={handleToggleGroupManageSession}
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
      <ChatDangerConfirmDialog
        open={Boolean(pendingConfirm)}
        title={pendingConfirmPresentation?.title ?? ""}
        confirmLabel={pendingConfirmPresentation?.confirmLabel ?? ""}
        cancelLabel={lang === "zh" ? "取消" : "Cancel"}
        confirmPending={pendingConfirmPresentation?.confirmPending ?? false}
        onOpenChange={(open) => {
          if (!open) {
            dismissPendingConfirm();
          }
        }}
        onCancel={dismissPendingConfirm}
        onConfirm={confirmPendingWorkbenchAction}
      />
    </ChatSessionWorkbenchShell>
  );
}
