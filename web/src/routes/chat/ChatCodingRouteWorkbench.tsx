import { collapseProjectUtilityRail, selectSessionUtilityRail, setProjectUtilityHost } from "../../app/projectUtilityRail";
import { useProjectAwareRightRail } from "./useProjectAwareRightRail";
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

import { listSessionChildSessions, fetchSessionLlmOptions } from "../../api/chat";
import { listArchivedChatSessions } from "../../api/sessionArchive";
import { archiveAgent } from "../../api/agents";
import {
  listVirtualHumanCompanionActivity,
  listVirtualHumanCompanions,
} from "../../api/agentPlugins";
import { fetchKnowledgeOverview, listAgentKnowledgeBases, searchKnowledgeItems } from "../../api/knowledge";
import { ChatRightRail } from "./ChatRightRail";
import {
  EMPTY_CHAT_RIGHT_RAIL,
  openChatRightRailTab,
  openFreshChatRightRailSideTab,
  type ChatRightRailModel,
} from "./chatRightRailModel";
import { requestChatRightRailOpen, subscribeChatRightRailOpen } from "./chatRightRailRequests";
import { useChatComposerTransientState } from "./useChatComposerTransientState";
import { useChatRailPreview } from "./useChatRailPreview";
import { useChatSessionMutations } from "./useChatSessionMutations";
import { createChatWorkspaceCache } from "../chatWorkspaceCache";
import type { AgentArchiveResponse } from "../agentWorkspaceCache";
import { prefetchConversationView } from "../../components/conversation/prefetchConversationView";
import type { ActiveTurnStreamState } from "../../components/conversation/activeTurnStreamState";
import type { ComposerQueueItem } from "../../components/conversation/composerFollowupQueueModel";
import { ConversationRerunFileChoiceDialog } from "../../components/conversation/ConversationRerunFileChoiceDialog";
import { FollowupQueueTogglePauseContext } from "../../components/conversation/ConversationFollowupQueueBar";
import { queryKeys } from "../../api/queryKeys";
import {
  AgentInstance,
  ChatRoomDetail,
  FileContent,
  MentalStateSnapshot,
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
  SessionModelSelection,
  SessionTurnAcceptedResponse,
  ConversationMessage,
  ToolCall,
  VirtualHumanCompanion,
  AgentPermissionPreset,
} from "../../api/types";
import type { ConversationStreamingFramePaintMetrics } from "../../components/conversation/conversationStreamingMetrics";
import type { ConversationForkScope } from "../../components/conversation/conversationViewTypes";
import { shouldShowNextStateSignalInConversation } from "../../components/conversation/conversationNextStateSignal";
import { VButton, VContextualHint, VInput, VNativeInput, VStateSurface, VTooltip, type VButtonProps } from "../../components/vui";
import { collectBrowserPageSnapshot, postBrowserTelemetry } from "../../app/browserTelemetry";
import { getPageInstanceId } from "../../app/pageInstance";
import { usePageVisibility, useStartupWarmup } from "../../app/pollingPolicy";
import type { TranslationKey } from "../../i18n/dictionary";
import { PaneResizeHandle } from "../../components/layout/PaneResizeHandle";
import { PaneCollapseHandle } from "../../components/layout/PaneCollapseHandle";
import { useAppI18n } from "../../i18n/useAppI18n";
import { useChatWorkbenchStore } from "../../store/chatWorkbenchStore";
import {
  deriveSessionDetailQueryErrorState,
  deriveSessionListQueryErrorState,
  mergeSessionDetailHandoffWithOutcome,
  mergeSessionDetailMessageWindowWithOutcome,
  mergeSessionDetailIntoSummaries,
} from "../chatSessionState";
import {
  reconcileAgentSessionDetailCache,
  updateSessionSummaryCaches,
} from "../chatSessionIndexQuery";
import {
  loadSessionListPreferences,
  saveSessionListPreferences,
  sessionListSortQueryValue,
  type SessionListPreferences,
} from "./sessionListPreferences";
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
import { directoryTeamBlockIds } from "../agentConversationDirectoryModel";
import { teamWorkspaceRoute } from "../teams/researchWorkspaceModel";
import {
  hasInvalidChildSessionLink,
  isSessionArchived,
  rootSessionIdFor,
  useConversationIndexModel,
} from "../conversationIndexModel";
import {
  activeTurnTerminalRefreshKey,
  activeTurnLayerTextLength,
  isActiveTurnSettledByDetail,
  isActiveTurnSettledByMessages,
  selectFirstUnpaintedRunningTool,
  setActiveTurnLayerForSession,
  toolStartToFirstPaintMs,
  runningToolPaintKeys,
} from "../chatActiveTurnLayer";
import {
  ActiveTurnLayersStoreProvider,
  createActiveTurnLayersStore,
  useActiveTurnLayersSignal,
  useActiveTurnLayersSignalFlag,
} from "./activeTurnLayersStore";
import {
  isChildSession,
} from "../DirectSessionIndexItem";
import { agentCenterConfigRoute, agentCenterMemoryRoute } from "../agentCenterRoutes";
import { FinancialAssistantChatNote } from "../finance/FinancialAssistantChatNote";
import { useFinancialResearchSessionBridge } from "../finance/FinancialResearchBridge";
import { FinancialResearchLiveProjection } from "../finance/FinancialResearchLiveProjection";
import { EMPTY_FINANCIAL_MESSAGES } from "../finance/stockResearchModel";
import { useFinancialAssistants } from "../finance/useFinancialAssistants";
import { useChatToolApprovalBridge } from "./useChatToolApprovalBridge";
import { useChatComposerBridgeState } from "./useChatComposerBridgeState";
import { useChatGroupRoomViewModel } from "./useChatGroupRoomViewModel";
import { ChatSessionWorkspacePanel } from "./ChatSessionWorkspacePanel";
import { ChatConversationIndexRail } from "./ChatConversationIndexRail";
import { ChatComposerPlusMenu, type ChatComposerSessionReferenceOption } from "./ChatComposerPlusMenu";
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
import { ChatSessionBrowser } from "./ChatSessionBrowser";
import { ChatCodingCenterTabs } from "./ChatCodingCenterTabs";
import { ChatCodingGroupSurface } from "./ChatCodingGroupSurface";
import { ChatConversationIndexPanel } from "./ChatConversationIndexPanel";
import { ChatSessionWorkbenchShell } from "./ChatSessionWorkbenchShell";
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
import { useGroupRoomTimeline } from "./useGroupRoomTimeline";
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
import { mergeArchivedSessionSummaries } from "./chatVisibleSessionCatalogModel";
import { useChatAgentSessionTabs } from "./useChatAgentSessionTabs";
import { useChatSessionIndexRailModel } from "./useChatSessionIndexRailModel";
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
  chatControlSignalLabel,
  buildChatSessionStateViewModel,
} from "./chatSessionSurfaceModel";
import {
  chatRoomModeLabel,
  chatRoomPurposeLabel,
  contextCompositionSegmentClass,
  contextCompositionSegmentLabel,
  promptSegmentDisplayLabel,
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
  cancelUnobservedSessionPrefetches,
  resolveActiveSessionDetailForUi,
  resolveNeighborSessionIdsForPrefetch,
  sessionDetailSnapshotKey,
  latestMentalSnapshot,
} from "./chatSessionDetailHelpers";
import {
  forgetSessionDetailPaint,
  shouldShowStickyTranscriptPending,
  touchSessionKeepAlive,
} from "./chatSessionPaintCache";
import {
  sessionDetailStructuralSharing,
  useStableSessionDetailPaint,
  useStableSessionDetailPlaceholder,
  useSessionToolApprovalsQuery,
  type SessionToolApprovalPollingInput,
} from "./chatSessionQuerySeams";

import {
  cliAgentRunIdFromTabId,
} from "./cliAgentRunModel";
import { postSubmitTelemetry } from "./chatSubmitTelemetry";
import {
  moveStoredSessionDraft,
  scheduleSessionDraftMetaSave,
} from "./chatDraftPersistence";
import { rekeySessionComposerEntry } from "../chatComposerState";
import {
  buildFileReferencePayload,
  buildKnowledgeBaseReferencePayload,
  buildKnowledgeItemReferencePayload,
  buildSessionReferencePayload,
  clearUnsupportedSessionImageAttachments,
  readStoredMentalModelToggle,
  readStoredPromptSuggestionToggle,
  readStoredRuntimeStatusToggle,
  startSessionReferenceDrag,
  writeStoredPromptSuggestionToggle,
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

/**
 * Module-level shared default so `changedFiles: detail.changedFiles ?? []` in
 * the memoized conversation model keeps a stable reference across renders
 * (a fresh `[]` per render would defeat the ConversationView memo gate).
 */
const EMPTY_SESSION_CHANGED_FILES: string[] = [];

/**
 * Knowledge-reference queries feeding the composer "reference" dropdown.
 *
 * The item options enumerate entries across every knowledge base the agent can
 * read (its private bases plus readable team bases). `searchKnowledgeItems` is
 * the only endpoint offering that cross-owner enumeration with a server-side
 * limit, so it stays — but it used to fire unconditionally with an empty query
 * on every chat-workbench mount and agent switch, which dominated the live
 * audit's scopeless empty-query search noise (most offenders scanned zero
 * bases). The search is now gated on the agent-scoped knowledge overview:
 * `summary.itemCount` counts the items of exactly the same owner/base set the
 * search scans, so `itemCount === 0` proves the search would return nothing
 * and the request is skipped. The overview is metadata-only (no item content)
 * and cached alongside the bases query, so agents that do own knowledge pay
 * one lightweight extra request instead of an unscoped scan-per-visit.
 */
export function useComposerKnowledgeReferenceQueries(agentId: string) {
  const agentKnowledgeBasesQuery = useQuery({
    queryKey: ["knowledge", "agent-bases", agentId],
    queryFn: () => listAgentKnowledgeBases<{ knowledgeBases?: Array<{ knowledgeBaseId?: string; name?: string; description?: string }> }>(
      agentId,
      { actorAgentId: agentId },
    ),
    enabled: Boolean(agentId),
    staleTime: 60_000,
  });
  const agentKnowledgeOverviewQuery = useQuery({
    queryKey: ["knowledge", "overview", agentId],
    queryFn: () => fetchKnowledgeOverview<{ summary?: { itemCount?: number } }>({ agentId }),
    enabled: Boolean(agentId),
    staleTime: 60_000,
  });
  const agentKnowledgeItemsQuery = useQuery({
    queryKey: queryKeys.knowledgeSearch("", agentId, "", "", "keyword"),
    queryFn: () => searchKnowledgeItems<{ results?: Array<{
      knowledgeItemId?: string;
      knowledgeBaseId?: string;
      title?: string;
      knowledgeBaseName?: string;
    }> }>({ agentId, limit: 20 }),
    enabled: Boolean(agentId) && (agentKnowledgeOverviewQuery.data?.summary?.itemCount ?? 0) > 0,
    staleTime: 60_000,
  });
  return { agentKnowledgeBasesQuery, agentKnowledgeItemsQuery };
}

export function ChatCodingRouteWorkbench() {
  // evolution: the companion rail shows evolution labels (otherwise raw keys leak).
  const { lang, t, statusLabel } = useAppI18n({ domains: ["chat", "agents", "evolution"] });
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
  const openPreviewTab = useChatWorkbenchStore((state) => state.openPreviewTab);
  const [sessionFilter, setSessionFilter] = useState("");
  const [sessionListPrefs, setSessionListPrefs] = useState<SessionListPreferences>(
    () => loadSessionListPreferences(),
  );
  useEffect(() => {
    saveSessionListPreferences(sessionListPrefs);
  }, [sessionListPrefs]);
  const sessionListSort = sessionListSortQueryValue(sessionListPrefs.sortBy);
  const [railSectionCollapsed, setRailSectionCollapsed] = useState<Record<string, boolean>>({});
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
  const rebaseComposerPreviewOwnersRef = useRef<((fromSessionId: string, toSessionId: string) => void) | null>(null);
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
  // Lazy boot-volley guard: the only consumer in this shell is the session
  // context-menu "report library" entry below, which already degrades to a
  // hidden item while the data is absent. Unconditionally fetching here put
  // GET /api/financial-assistants into every app-open boot volley (cold hits
  // measured at multiple seconds), so the query only enables while a session
  // context menu is open; the hook cache still serves repeat opens.
  const financialAssistants = useFinancialAssistants(Boolean(sessionContextMenu));
  // Active-turn layers live in an external store instead of component state:
  // assistant delta frames commit multiple times per second, and only the
  // ConversationView bridge subscribes per frame (see activeTurnLayersStore).
  // The workbench itself re-renders only on the primitive signals below.
  const activeTurnLayersStore = useMemo(() => createActiveTurnLayersStore(), []);
  const { setActiveTurnLayersBySession, activeTurnLayersBySessionRef } = activeTurnLayersStore;
  const {
    storedDraftState,
    sessionDrafts,
    setSessionDrafts,
    sessionComposerErrors,
    setSessionComposerErrors,
    sessionImageAttachments,
    setSessionImageAttachments,
    sessionReferenceAttachments,
    setSessionReferenceAttachments,
    sessionImageUploadPending,
    setSessionImageUploadPending,
    imageUploadInFlightRef,
    clearSessionTransientUiState,
  } = useChatComposerTransientState({
    queryClient,
    setActiveTurnLayersBySession,
  });

  useEffect(() => {
    editingSessionIdRef.current = editingSessionId;
  }, [editingSessionId]);
  useEffect(() => {
    editingSessionTitleRef.current = editingSessionTitle;
  }, [editingSessionTitle]);

  const [sessionBrowserOpen, setSessionBrowserOpen] = useState(false);
  useEffect(() => {
    setSessionBrowserOpen(false);
  }, [location.key]);
  const [showArchivedSessions, setShowArchivedSessions] = useState(false);
  const [mentalModelEnabledForNextTurn, setMentalModelEnabledForNextTurn] = useState<boolean>(
    () => readStoredMentalModelToggle() ?? false,
  );
  const [runtimeStatusEnabledForNextTurn, setRuntimeStatusEnabledForNextTurn] = useState<boolean>(
    () => readStoredRuntimeStatusToggle() ?? true,
  );
  // Per-session opt-in; the backend only holds the latest capture per session,
  // so remember the operator choice per session instead of globally.
  const [promptSuggestionEnabledBySession, setPromptSuggestionEnabledBySession] = useState<Record<string, boolean>>({});
  // Retain the financial-assistant bridge's existing draft contract. Ordinary
  // Agent chat ignores these legacy selections and always uses Agent bindings.
  const [turnModelSelections, setTurnModelSelections] = useState<Record<string, SessionModelSelection | null>>(storedDraftState.turnModelSelections);
  const setTurnModelSelectionForSession = useCallback((sessionId: string, selection: SessionModelSelection | null) => {
    setTurnModelSelections((current) => ({ ...current, [sessionId]: selection }));
  }, []);
  const rebaseSessionComposerState = useCallback((fromId: string, toId: string) => {
    rebaseComposerPreviewOwnersRef.current?.(fromId, toId);
    moveStoredSessionDraft(fromId, toId);
    setSessionDrafts((current) => rekeySessionComposerEntry(current, fromId, toId));
    setSessionReferenceAttachments((current) => rekeySessionComposerEntry(current, fromId, toId));
    setTurnModelSelections((current) => rekeySessionComposerEntry(current, fromId, toId));
    setSessionImageAttachments((current) => rekeySessionComposerEntry(current, fromId, toId));
  }, []);
  // Rich draft persistence: per-turn model selection and reference chips ride
  // the same debounced store as the draft text (ZCode draft parity). The
  // composer-change text save stays in useChatComposerSubmit; only this effect
  // reports meta. Images/files never enter the store (text metadata only).
  useEffect(() => {
    const sessionId = activeSessionId;
    if (!sessionId) {
      return;
    }
    scheduleSessionDraftMetaSave(sessionId, {
      turnModelSelection: turnModelSelections[sessionId] ?? null,
      referenceAttachments: sessionReferenceAttachments[sessionId] ?? [],
    });
  }, [activeSessionId, turnModelSelections, sessionReferenceAttachments]);
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
  // Epoch-ms stamp of the last applied stream event per session; feeds the
  // active-turn no-output stall baseline through a getter (see below).
  const lastStreamActivityAppliedAtRef = useRef<Record<string, number>>({});
  // ConversationView reports its committed frame from a child effect. React
  // runs that effect before this parent's effects, so the paint handler must
  // read the freshest committed layers; the store keeps its read-through ref
  // current synchronously on every commit (no render-time sync needed).
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
  const financeSurface = location.pathname === "/finance";
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
      setGroupRoomActionError("");
    }
  }, [chatRouteSelection.kind, setGroupRoomActionError, setRightIndexPanel]);

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
    directSessionBackgroundSyncActive,
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
      // Detail cache keeps metadata/participants/operation results only; the
      // transcript authority is the timeline query, so a snapshot folds into a
      // cursor-incremental timeline reconciliation instead of overwriting the
      // rendered message list wholesale.
      queryClient.setQueryData(queryKeys.chatRoom(room.roomId), room);
      queryClient.invalidateQueries({ queryKey: queryKeys.chatRoomTimeline(room.roomId) });
      if (String(room.status ?? "").trim().toLowerCase() !== "running") {
        void chatWorkspaceCache.afterChatRoomChanged(room.roomId);
      }
    },
    [chatWorkspaceCache, queryClient],
  );
  const { groupStreamConnected, groupSpeakerStreams, groupSpeakerProgress } = useGroupRoomStream({
    activeGroupRoomId,
    groupStreamShouldConnect,
    syncChatRoomDetail,
  });
  const syncSessionDetail = useCallback(
    (
      detail: SessionDetail,
      options?: {
        /** ``preserve`` folds a transcript-free select handoff into the cache. */
        transcript?: "merge" | "preserve";
      },
    ) => {
      let shouldSyncSummaries = true;
      let mergedDetail: SessionDetail = detail;
      queryClient.setQueryData<SessionDetail>(queryKeys.session(detail.id), (previous) => {
        const outcome = options?.transcript === "preserve"
          ? mergeSessionDetailHandoffWithOutcome(previous, detail)
          : mergeSessionDetailMessageWindowWithOutcome(previous, detail);
        const nextDetail = outcome.detail;
        shouldSyncSummaries = outcome.authorityAccepted;
        mergedDetail = nextDetail;
        if (previous && sessionDetailSnapshotKey(previous) === sessionDetailSnapshotKey(nextDetail)) {
          return previous;
        }
        return nextDetail;
      });
      if (!shouldSyncSummaries) {
        return;
      }
      // Summary caches fold onto the merged detail so partial control acks
      // cannot blank title / status / phase fields they did not carry.
      updateSessionSummaryCaches(queryClient, (sessions) =>
        mergeSessionDetailIntoSummaries(sessions, mergedDetail),
      );
      reconcileAgentSessionDetailCache(queryClient, mergedDetail);
      const detailRootSessionId = rootSessionIdFor(mergedDetail);
      if (isChildSession(mergedDetail) && detailRootSessionId) {
        queryClient.setQueryData<SessionSummary[]>(queryKeys.sessionChildSessions(detailRootSessionId), (sessions) =>
          mergeSessionDetailIntoSummaries(sessions, mergedDetail),
        );
      }
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
  const { sessionStreamConnected, streamDisconnectedSinceMs, reconnectSessionStream } = useSessionDetailStream({
    activeSessionId,
    sessionStreamShouldConnect,
    queryClient,
    syncSessionDetail,
    setActiveTurnLayersBySession,
    activeTurnLayersBySessionRef,
    lastAssistantDeltaAppliedAtRef,
    lastStreamActivityAppliedAtRef,
    sessionStreamDecisionSnapshotRef,
    desktopConversationNotifierRef,
    sessionTitleForNotifications,
    viewedSessionId: activeSessionId || "",
  });
  // Transport visibility for the active-turn status note. `streamConnected`
  // stays tri-state: only a real reconnect loop reports false; route-settling
  // teardowns keep it undefined so the note never flashes a false drop.
  const activeTurnStreamState = useMemo<ActiveTurnStreamState>(
    () => ({
      streamConnected: streamDisconnectedSinceMs != null ? false : undefined,
      streamDisconnectedSinceMs,
      lastAssistantDeltaAtMs: lastAssistantDeltaAppliedAtRef.current[String(activeSessionId || "")],
      // Ref-backed getter on purpose: the stamps advance on every applied frame
      // while this memo almost never recomputes, so the note's per-second tick
      // must read the fresh value through the closure.
      lastStreamActivityAtMs: () =>
        lastStreamActivityAppliedAtRef.current[String(activeSessionId || "")] || null,
      reconnectSessionStream,
    }),
    [
      streamDisconnectedSinceMs,
      activeSessionId,
      lastAssistantDeltaAppliedAtRef,
      lastStreamActivityAppliedAtRef,
      reconnectSessionStream,
    ],
  );
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
    configSummaryQuery,
    selectedAgentId,
    setSelectedAgentId,
    activeSessionBootstrapQuery,
    sessionIndexQueryEnabled,
    directoryGatePending,
    modelLabelsById,
    modelImageInputSupportById,
    resolveModelLabel,
    rawSessionsQuery,
    sessionsQuery,
    archivedSessionsQuery,
    conversationsQuery,
    teamsQuery,
    agentsQuery,
    skillsQuery,
    slashCommandSuggestions,
    slashSkillsCatalogState,
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
    sessionListSort,
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
    showArchivedSessions,
    sessionDirectoryEnabled: !financeSurface,
  });

  const archivedSessions = useMemo(
    () => (showArchivedSessions ? archivedSessionsQuery.data?.items ?? [] : []),
    [archivedSessionsQuery.data, showArchivedSessions],
  );
  const {
    sessionArchiveMutation,
    pinSessionMutation,
    renameAgentMutation,
    handleForkSessionFromNode,
  } = useChatSessionMutations({
    queryClient,
    chatWorkspaceCache,
    lang,
    t,
    setSessionComposerErrors,
    latestDirectSessionSelectionRef,
    directSessionSelectionGenerationRef,
    activeSessionId,
    syncSessionDetail,
    openSession,
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
    // Re-read the Agent binding when returning from Agent management.
    refetchOnMount: "always",
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
    if ((financeSurface || sessionsQuery.data) && directReady && groupReady) {
      setChatStartupDataReady(true);
    }
  }, [
    activeGroupRoomQuery.data,
    activeSessionId,
    financeSurface,
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
  // A hidden window can miss frames or a stream restart; refocusing must not
  // trust the cached transcript, so force one authoritative resync for the
  // active session and the indexes that feed badges and notification titles.
  const previousPageVisibleRef = useRef(pageVisible);
  const refetchSessionDetailRef = useRef(sessionDetailQuery.refetch);
  refetchSessionDetailRef.current = sessionDetailQuery.refetch;
  const focusResyncSessionIdRef = useRef(activeSessionId || "");
  focusResyncSessionIdRef.current = activeSessionId || "";
  useEffect(() => {
    const previousPageVisible = previousPageVisibleRef.current;
    previousPageVisibleRef.current = pageVisible;
    const resyncSessionId = focusResyncSessionIdRef.current;
    if (!pageVisible || previousPageVisible || !resyncSessionId) {
      return;
    }
    // enabled:false does not stop refetch(). A temp shell has no server row;
    // this GET 404s and the error surface replaces the composer.
    if (!isTempSessionId(resyncSessionId)) {
      void refetchSessionDetailRef.current();
    }
    void queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.conversations() });
    postBrowserTelemetry({
      phase: "session_stream",
      eventCode: "browser.session_stream.focus_resync",
      message: "Focus after a hidden period forced an authoritative session resync.",
      level: "info",
      fields: {
        sessionId: resyncSessionId,
        streamShouldConnect: sessionStreamDecisionSnapshotRef.current.shouldConnect,
        visibilityState: typeof document === "undefined" ? "unknown" : document.visibilityState,
      },
    });
  }, [pageVisible, queryClient]);

  const {
    submitTurnMutation,
    editResubmitMutation,
    regenerateMutation,
    switchHeadMutation,
    stopTurnMutation,
    sessionGuidanceMutation,
  } = useChatComposerTurnMutations({
    queryClient,
    chatWorkspaceCache,
    activeSessionId: activeSessionId ?? undefined,
    activeTurnLayersStore,
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
    rebaseSessionComposerState,
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
  } = useChatSessionDetailMutations({
    queryClient,
    chatWorkspaceCache,
    lang,
    describeError,
    activeSessionId,
    setSessionComposerErrors,
  });

  const activeGroupRoom = activeGroupRoomQuery.data;
  const groupRoomInitialLoading = Boolean(
    standardGroupRoomActive && activeGroupRoomQuery.isPending && !activeGroupRoomQuery.data,
  );
  const groupTimeline = useGroupRoomTimeline({
    roomId: activeGroupRoomId,
    enabled: Boolean(standardGroupRoomActive && activeGroupRoomId),
    detail: activeGroupRoom,
  });
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
  const activePrefetchTargetRef = useRef(activeSessionId);
  activePrefetchTargetRef.current = activeSessionId;
  useEffect(() => {
    if (financeSurface || groupPanelActive || !secondaryChatDataEnabled || !pageVisible || !sessionsQuery.data?.length) {
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
    const ownedPendingIds = new Set<string>();
    const run = async () => {
      for (const sessionId of neighborIds) {
        if (cancelled) {
          return;
        }
        try {
          const alreadyFetching = queryClient.getQueryState(queryKeys.session(sessionId))?.fetchStatus === "fetching";
          if (!alreadyFetching) ownedPendingIds.add(sessionId);
          await prefetchSessionDetailWindow(queryClient, sessionId);
        } catch {
          return;
        } finally {
          ownedPendingIds.delete(sessionId);
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
      void cancelUnobservedSessionPrefetches(queryClient, ownedPendingIds, activePrefetchTargetRef.current || "");
      if (typeof idleRequest === "function") {
        (window as Window & { cancelIdleCallback?: (id: number) => void }).cancelIdleCallback?.(handle as number);
      } else {
        window.clearTimeout(handle as number);
      }
    };
  }, [activeSessionId, financeSurface, groupPanelActive, pageVisible, queryClient, secondaryChatDataEnabled, sessionsQuery.data]);


  const workspace = activeSessionId
    ? sessionWorkspaces[activeSessionId] ?? {
        openTabs: [],
        activeTab: "agent",
      }
    : { openTabs: [], activeTab: "agent" };

  const activeCliAgentRunId = cliAgentRunIdFromTabId(workspace.activeTab);
  const activeFilePath = workspace.activeTab !== "agent" && !activeCliAgentRunId ? workspace.activeTab : null;
  const changedFileList = sessionDetailQuery.data?.changedFiles ?? EMPTY_SESSION_CHANGED_FILES;
  // Group rooms share the ordinary right rail (review/git, file preview,
  // devtools); session-scoped kinds (side chats, subagent directory) stay
  // hidden through the launcher filter, and rail state keys off the room id.
  const ordinaryChangeRail = !verifiedCompanionMode && !financeSurface;
  const {
    fileContentQuery,
    changeRail,
    changeRailOpened,
    setChangeRailOpened,
    railsBySession,
    setRailsBySession,
    railModel,
    activeRailTab,
    updateRailModel,
    project: projectRail,
    gitRail,
    reviewSource,
    sessionReviewPath,
    gitReviewPath,
    setReviewPick,
    changePreview,
  } = useChatRailPreview({
    activeSessionId: groupPanelActive ? `group:${activeGroupRoomId}` : activeSessionId,
    activeFilePath,
    workspace,
    changedFileList,
    ordinaryChangeRail,
    companion: verifiedCompanionMode,
    finance: financeSurface,
    group: groupPanelActive,
  });

  const sessionBrowserVisible = sessionBrowserOpen && !financeSurface && !verifiedCompanionMode && !groupPanelActive;
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
  } = useChatWorkbenchLayout({
    standardGroupRoomActive,
    statusRailEnabled: !sessionBrowserVisible && (verifiedCompanionMode || (ordinaryChangeRail && (changeRail.show || changeRailOpened))),
    indexRailEnabled: !financeSurface,
  });
  useEffect(() => {
    if (!ordinaryChangeRail) {
      return undefined;
    }
    return subscribeChatRightRailOpen((request) => {
      const requestSessionId = request.sessionId.trim();
      if (!requestSessionId) {
        return false;
      }
      setRailsBySession((current) => {
        const model = current[requestSessionId] ?? EMPTY_CHAT_RIGHT_RAIL;
        return {
          ...current,
          [requestSessionId]: openChatRightRailTab(model, {
            kind: request.kind,
            title: request.title,
            targetId: request.targetId,
            filePath: request.filePath,
          }),
        };
      });
      if (requestSessionId === activeSessionId) {
        selectSessionUtilityRail();
        setChangeRailOpened(true);
        if (responsiveLayout.rightVisible) {
          setRightPaneCollapsed(false);
        } else {
          setResponsiveOverlayPane("right");
        }
      }
      return true;
    });
  }, [
    activeSessionId,
    ordinaryChangeRail,
    responsiveLayout.rightVisible,
    setResponsiveOverlayPane,
    setRightPaneCollapsed,
  ]);
  useEffect(() => {
    setProjectUtilityHost(ordinaryChangeRail);
    return () => setProjectUtilityHost(false);
  }, [ordinaryChangeRail]);
  useEffect(() => {
    if (!ordinaryChangeRail || !projectRail.selected) return;
    if (!projectRail.opened) {
      setRightPaneCollapsed(true);
      setResponsiveOverlayPane(null);
      return;
    }
    setSessionBrowserOpen(false);
    setChangeRailOpened(true);
    if (responsiveLayout.rightVisible) setRightPaneCollapsed(false);
    else setResponsiveOverlayPane("right");
  }, [ordinaryChangeRail, projectRail.opened, projectRail.selected, projectRail.model.activeId, responsiveLayout.rightVisible, setRightPaneCollapsed, setResponsiveOverlayPane]);
  const changedFiles = new Set(changedFileList);
  const changedPathSet = new Set(
    changedFileList.map((path) => String(path || "").replace(/\\/g, "/").trim()),
  );
  const conversationWorkspaceTab = activeCliAgentRunId || !changeRail.show
    ? workspace.activeTab
    : "agent";
  const changeRailVisible = ordinaryChangeRail && (changeRail.show || changeRailOpened) && !statusRailCollapsed;
  const toggleChangeRail = () => {
    if (changeRailVisible || statusRailOverlayOpen) collapseProjectUtilityRail();
    if (!ordinaryChangeRail) {
      setResponsiveOverlayPane((current) => current === "right" ? null : "right");
      return;
    }
    if (changeRailVisible) {
      if (responsiveLayout.rightVisible) {
        setRightPaneCollapsed(true);
      } else {
        setResponsiveOverlayPane(null);
      }
      return;
    }
    setChangeRailOpened(true);
    if (responsiveLayout.rightVisible) {
      setRightPaneCollapsed(false);
    } else {
      setResponsiveOverlayPane("right");
    }
  };

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
  // The server queue is the single writer: the composer bar mirrors
  // detail.queuedTurns instead of holding a local follow-up list.
  const sessionFollowupQueues = useMemo<Record<string, ComposerQueueItem[]>>(() => {
    const sessionId = String(detail?.id || "").trim();
    const rows = detail?.queuedTurns ?? [];
    if (!sessionId || !rows.length) {
      return {};
    }
    return {
      [sessionId]: rows.map((row) => {
        const kind = String(row.kind || "user");
        const systemReturn = kind === "task_notification" || kind === "subagent_message";
        return {
          id: String(row.id || ""),
          text: String(row.content || ""),
          kind,
          status: String(row.status || "queued"),
          position: Number(row.position || 0),
          sendNow: row.sendNow === true,
          attachmentCount: Array.isArray(row.attachments) ? row.attachments.length : 0,
          lastError: String(row.lastError || ""),
          canSteer: !systemReturn && !(row.attachments?.length) && !(row.references?.length),
        };
      }),
    };
  }, [detail?.id, detail?.queuedTurns]);
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
  // Primitive-signal subscriptions: streaming frames commit into the store
  // without re-rendering this component; these selectors re-render the
  // workbench only when a derived value (settle flag, terminal refresh key,
  // running-session key) actually changes.
  const activeTurnSessionKey = activeSessionId ?? "";
  const activeTurnSettledByDetail = useActiveTurnLayersSignalFlag(useCallback((layers) => {
    return isActiveTurnSettledByMessages(layers[activeTurnSessionKey], detail?.messages);
  }, [activeTurnSessionKey, detail?.messages]));
  const terminalIndexRefreshKey = useActiveTurnLayersSignal(useCallback((layers) => {
    return activeTurnTerminalRefreshKey(layers[activeTurnSessionKey], detail);
  }, [activeTurnSessionKey, detail]));
  const activeTurnRunningSessionKey = useActiveTurnLayersSignal(useCallback((layers) => {
    const runningSessionIds: string[] = [];
    Object.entries(layers).forEach(([sessionId, layer]) => {
      if (layer.status === "pending" || layer.status === "running") {
        runningSessionIds.push(sessionId);
      }
    });
    runningSessionIds.sort();
    return runningSessionIds.join("|");
  }, []));
  // The bridge input only needs the active session's turn id; subscribing to
  // the primitive id (not the whole layer) keeps per-frame commits from
  // re-rendering the workbench while the turn id itself still updates once
  // per turn.
  const activeTurnIdSignal = useActiveTurnLayersSignal(useCallback((layers) => {
    return layers[activeTurnSessionKey]?.turnId ?? "";
  }, [activeTurnSessionKey]));
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
    if (!activeSessionId || !activeTurnSettledByDetail || !detail) {
      return;
    }
    const settledLayer = activeTurnLayersBySessionRef.current[activeSessionId];
    if (!settledLayer) {
      return;
    }
    const settledTurnId = settledLayer.turnId;
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
  }, [activeSessionId, activeTurnSettledByDetail, detail, queryClient, setActiveTurnLayersBySession, activeTurnLayersBySessionRef]);
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
    refetchSessionDetail: () => (
      isTempSessionId(activeSessionId) ? undefined : sessionDetailQuery.refetch()
    ),
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
  const projectBusTimeline = projectAgentBusQuery.data;
  const projectBusEvents = projectBusTimeline?.events ?? [];
  const tempSessionShell = isTempSessionId(activeSessionId);
  const sessionDetailErrorState = deriveSessionDetailQueryErrorState(detail, sessionDetailQuery.isError, {
    dataUpdatedAt: sessionDetailQuery.dataUpdatedAt,
    errorUpdatedAt: sessionDetailQuery.errorUpdatedAt,
    streamConnected: sessionStreamConnected,
    localOnlySession: tempSessionShell,
  });
  const sessionsErrorState = deriveSessionListQueryErrorState(sessionsQuery.data, sessionsQuery.isError, {
    emptyNotFoundAsEmpty: true,
    error: sessionsQuery.error,
  });
  const sessionDetailErrorMessage = sessionDetailQuery.isError && !tempSessionShell
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
  const composerContextRing = useMemo(() => {
    const usageUsed = lastContextComposition?.totalTokens ?? detail?.contextUsage?.used ?? 0;
    const usageLimit = lastContextComposition?.limitTokens ?? detail?.contextUsage?.limit ?? 0;
    const runtimeCompression = runtime?.contextCompression;
    const compressionLevels = runtimeCompression?.strategy?.levels ?? [];
    return buildComposerContextRingModel({
      usageUsed,
      usageLimit,
      hitPercent: cacheCompositionPercent,
      detailAvailable: cacheDetailAvailable,
      segments: (lastContextComposition?.segments ?? []).map(segment => ({
        ...segment,
        label: promptSegmentDisplayLabel(segment, lang, t),
        contentPreview: segment.description,
      })),
      lang,
      cacheSource: lastCacheComposition?.source,
      cacheUsageObserved: lastCacheComposition?.cacheUsageObserved,
      cachedInputTokens: lastCacheComposition?.cachedInputTokens,
      cacheCreationInputTokens: lastCacheComposition?.cacheCreationInputTokens,
      // Backend-owned auto-compression trigger (lowest configured level); read-only.
      autoCompactThresholdTokens: compressionLevels.length
        ? Math.min(...compressionLevels.map(level => level.thresholdTokens))
        : undefined,
      autoCompactEnabled: runtimeCompression?.enabled,
      tokensPerSecond: detail?.llmUsage?.tokensPerSecond ?? null,
    });
  }, [
    cacheCompositionPercent,
    cacheDetailAvailable,
    detail?.contextUsage?.limit,
    detail?.contextUsage?.used,
    detail?.llmUsage?.tokensPerSecond,
    lang,
    lastCacheComposition?.cacheCreationInputTokens,
    lastCacheComposition?.cacheUsageObserved,
    lastCacheComposition?.cachedInputTokens,
    lastCacheComposition?.source,
    lastContextComposition?.limitTokens,
    lastContextComposition?.totalTokens,
    lastContextComposition?.segments,
    runtime?.contextCompression,
    t,
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
  // Rebuilt only when the running-session key changes (a status transition),
  // not on every committed streaming frame; reads the store's latest snapshot.
  const runtimeRunningSessionIds = useMemo(() => {
    const runningSessionIds = new Set(runtimeChatTurnSessionIds);
    Object.entries(activeTurnLayersBySessionRef.current).forEach(([sessionId, layer]) => {
      if (layer.status === "pending" || layer.status === "running") {
        runningSessionIds.add(sessionId);
      }
    });
    return [...runningSessionIds];
  }, [activeTurnLayersBySessionRef, activeTurnRunningSessionKey, runtimeChatTurnSessionIds]);
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
    regenerateMutation,
    stopTurnMutation,
    sessionGuidanceMutation,
    activeTurnSettledByDetail,
  });
  const companionComposerDisabled = composerDisabled || (companionMode && !companionTransportAgentId);
  const companionConversationComposer = useMemo(
    () => (companionMode
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
      : conversationComposer),
    [companionComposerDisabled, companionMode, conversationComposer, sessionBusy, submitPending],
  );
  const activeAgentDisplay = detail
    ? sessionAgentDisplayInfo(detail, activeSessionAgent, lang, resolveModelLabel)
    : { name: "Agent", functionLabel: "", tone: "chat" as const, meta: "" };
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
  const regenerableAssistantMessageId = useMemo(() => {
    const messages = detail?.messages ?? [];
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      if (messages[index].role !== "assistant") {
        continue;
      }
      const hasUserBefore = messages.slice(0, index).some((message) => message.role === "user");
      return hasUserBefore ? messages[index].id : "";
    }
    return "";
  }, [detail?.messages]);
  const latestControlSignalKindLabel = latestControlSignal
    ? chatControlSignalLabel(latestControlSignal, lang)
    : "";
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
    handleFollowupQueueSteer,
    handleFollowupQueueTogglePause,
    handleFollowupQueueSendNow,
    handleEditUserMessage,
    handleCancelEditMessage,
    handleRegenerateAssistantMessage,
    handleRetryFailedTurn,
    handleSwitchMessageVersion,
    rerunFileChoice,
    confirmRerunFileRestore,
    keepFilesAndRerun,
    dismissRerunFileChoice,
    handleComposerChange,
    handleMentalModelEnabledChange,
    handleRuntimeStatusEnabledChange,
    handleAddComposerAttachments,
    handleRemoveComposerAttachment,
    handleRetryComposerAttachmentUpload,
    handleRetryComposerAttachmentUploads,
    handleAddComposerReference,
    handleRemoveComposerReference,
    rebaseComposerPreviewOwners,
  } = useChatComposerSubmitActions({
    queryClient,
    setActiveTurnLayersBySession,
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
    // Ordinary Agent chat must never restore a legacy composer model override.
    turnModelSelection: financeSurface && activeSessionId ? turnModelSelections[activeSessionId] ?? null : null,
    resolvedEditTarget,
    activeEditTarget,
    composerDisabled: companionComposerDisabled,
    sessionBusy,
    sessionStopping,
    activePhase: detail?.currentPhase,
    activeAgentImageInputUnsupported,
    activeImageInputModelId,
    latestUserMessageId,
    activeTurnId: activeTurnIdSignal || undefined,
    detail,
    setMentalModelEnabledForNextTurn,
    setRuntimeStatusEnabledForNextTurn,
    companionAgentId: companionTransportAgentId,
  });
  rebaseComposerPreviewOwnersRef.current = rebaseComposerPreviewOwners;
  const activePromptSuggestionEnabled = activeSessionId
    ? promptSuggestionEnabledBySession[activeSessionId] ?? readStoredPromptSuggestionToggle(activeSessionId)
    : false;
  const handlePromptSuggestionEnabledChange = useCallback((enabled: boolean) => {
    if (!activeSessionId) {
      return;
    }
    writeStoredPromptSuggestionToggle(activeSessionId, enabled);
    setPromptSuggestionEnabledBySession((current) => ({
      ...current,
      [activeSessionId]: enabled,
    }));
  }, [activeSessionId]);
  const sessionLlmOptions = sessionLlmOptionsQuery.data;
  const turnModelSelection = activeSessionId ? turnModelSelections[activeSessionId] ?? null : null;
  const agentModel = sessionLlmOptions?.model ?? null;
  const sessionEffort = sessionLlmOptions?.currentReasoningEffort || detail?.reasoningEffort || "";
  const turnModelControl = activeSessionId ? {
    model: agentModel,
    loading: sessionLlmOptionsQuery.isLoading,
    error: sessionLlmOptionsQuery.isError,
  } : undefined;
  const sessionLlmControl = activeSessionId && agentModel ? {
    model: agentModel,
    sessionId: activeSessionId,
    currentReasoningEffort: sessionEffort,
    disabled: sessionBusy || sessionLlmOptionsQuery.isLoading || sessionLlmOptionsQuery.isError,
    pending: sessionReasoningEffortMutation.isPending,
    onReasoningEffortChange: (reasoningEffort: string) => {
      if (!activeSessionId || sessionLlmOptionsQuery.isError) return;
      sessionReasoningEffortMutation.mutate({ sessionId: activeSessionId, reasoningEffort });
    },
  } : undefined;

  useEffect(() => {
    if (!activeSessionId || !activeAgentImageInputUnsupported || !activeImageAttachments.length) {
      return;
    }
    setSessionImageAttachments((current) => clearUnsupportedSessionImageAttachments(current, activeSessionId));
  }, [activeAgentImageInputUnsupported, activeImageAttachments.length, activeSessionId]);

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

  const rawSessionsWithArchived = useMemo(() => {
    if (!showArchivedSessions || archivedSessions.length === 0) {
      return rawSessionsQuery.data;
    }
    return mergeArchivedSessionSummaries(rawSessionsQuery.data, archivedSessions);
  }, [archivedSessions, rawSessionsQuery.data, showArchivedSessions]);
  const routeVisibleSessions = useMemo(() => {
    const base = sessionsForChatRoute({
      sessions: sessionsQuery.data,
      agents: agentsQuery.data,
      companionRouteVerified: verifiedCompanionMode,
    });
    if (!showArchivedSessions || archivedSessions.length === 0) {
      return base;
    }
    return mergeArchivedSessionSummaries(base, archivedSessions);
  }, [agentsQuery.data, archivedSessions, sessionsQuery.data, showArchivedSessions, verifiedCompanionMode]);

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
    includeArchivedSessions: showArchivedSessions,
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
  const selectedChatAgent = selectedChatAgentId ? agentsById.get(selectedChatAgentId) : undefined;

  const composerKnowledgeAgentId = activeSessionAgentId || selectedChatAgentId || "";
  const { agentKnowledgeBasesQuery, agentKnowledgeItemsQuery } =
    useComposerKnowledgeReferenceQueries(composerKnowledgeAgentId);
  const composerKnowledgeReferenceOptions = useMemo<ChatComposerSessionReferenceOption[]>(() => {
    const options: ChatComposerSessionReferenceOption[] = [];
    for (const base of agentKnowledgeBasesQuery.data?.knowledgeBases ?? []) {
      const baseId = String(base.knowledgeBaseId || "").trim();
      if (!baseId) {
        continue;
      }
      const title = String(base.name || baseId).trim();
      options.push({
        id: `knowledge-base:${baseId}`,
        title,
        meta: t("composerReferenceKindKnowledgeBase"),
        reference: buildKnowledgeBaseReferencePayload(baseId, title),
      });
    }
    for (const item of agentKnowledgeItemsQuery.data?.results ?? []) {
      const itemId = String(item.knowledgeItemId || "").trim();
      const itemBaseId = String(item.knowledgeBaseId || "").trim();
      if (!itemId || !itemBaseId) {
        continue;
      }
      const title = String(item.title || itemId).trim();
      options.push({
        id: `knowledge-item:${itemId}`,
        title,
        meta: String(item.knowledgeBaseName || itemBaseId).trim(),
        reference: buildKnowledgeItemReferencePayload(itemBaseId, itemId, title),
      });
    }
    const seenSessionFiles = new Set<string>();
    for (const message of detail?.messages ?? []) {
      if (message.role !== "user") {
        continue;
      }
      for (const attachment of message.attachments ?? []) {
        const artifactId = String(attachment.artifactId || "").trim();
        if (!artifactId || seenSessionFiles.has(artifactId)) {
          continue;
        }
        if (attachment.kind && attachment.kind !== "user_document") {
          continue;
        }
        seenSessionFiles.add(artifactId);
        const filename = String(attachment.filename || artifactId).trim();
        options.push({
          id: `file:${artifactId}`,
          title: filename,
          meta: t("composerReferenceKindFile"),
          reference: buildFileReferencePayload(artifactId, filename),
        });
      }
    }
    return options;
  }, [agentKnowledgeBasesQuery.data, agentKnowledgeItemsQuery.data, detail, t]);

  const {
    rightIndexSessions,
    agentSessionTabs,
  } = useChatAgentSessionTabs({
    queryClient,
    selectedChatAgentId,
    agentsById,
    allVisibleSessions,
    activeSessionId,
    secondaryChatDataEnabled: secondaryChatDataEnabled && !financeSurface,
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
    includeArchivedSessions: showArchivedSessions,
    lang,
    linkedTeamRoomIds,
    rawSessions: rawSessionsWithArchived,
    rightIndexSessions,
    sessionFilter,
    sessionsById,
    teams,
  });
  const directoryTeamIds = useMemo(() => directoryTeamBlockIds(teams), [teams]);
  const {
    groupedGroupConversations,
    groupedGroupConversationCount,
  } = useChatSessionIndexRailModel({
    groupedConversations,
    directoryTeamIds,
  });
  useEffect(() => {
    if (
      financeSurface
      || !rawSessionsQuery.hasMore
      || rawSessionsQuery.isLoadingMore
      || rawSessionsQuery.isFetchNextPageError
    ) {
      return;
    }
    void rawSessionsQuery.loadMore();
  }, [
    financeSurface,
    rawSessionsQuery.hasMore,
    rawSessionsQuery.isLoadingMore,
    rawSessionsQuery.isFetchNextPageError,
    rawSessionsQuery.loadMore,
  ]);
  const teamRoomsByTeamId = useMemo(() => {
    const roomsByTeamId = new Map<string, ConversationSummary[]>();
    for (const conversation of conversationsQuery.data ?? []) {
      if (String(conversation.type || "").trim() !== "group_room") continue;
      const teamId = String(conversation.teamId || "").trim();
      if (!teamId) continue;
      const rooms = roomsByTeamId.get(teamId) ?? [];
      rooms.push(conversation);
      roomsByTeamId.set(teamId, rooms);
    }
    return roomsByTeamId;
  }, [conversationsQuery.data]);
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
    handleCreateSession,
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
    openDeleteSessionConfirm,
    openClearSessionHistoryConfirm,
    openDeleteGroupConfirm,
    openResetGroupConfirm,
  });

  useDesktopConversationAttention({
    sessions: allVisibleSessions,
    queryClient,
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

  const handleArchiveSession = useCallback((session: SessionSummary) => {
    setSessionContextMenu(null);
    sessionArchiveMutation.mutate({
      sessionId: session.id,
      archive: !isSessionArchived(session),
    });
  }, [sessionArchiveMutation, setSessionContextMenu]);
  const refreshArchivedSessions = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.sessionArchive() });
    void queryClient.invalidateQueries({ queryKey: ["sessions", "finance"] });
    void queryClient.invalidateQueries({ queryKey: ["sessions", "finance-archived"] });
    void queryClient.invalidateQueries({ queryKey: queryKeys.financialAssistants() });
  }, [queryClient]);
  const handleDeleteArchivedSession = useCallback((session: SessionSummary) => {
    deleteSessionMutation.mutate(
      { sessionId: session.id },
      { onSettled: refreshArchivedSessions },
    );
  }, [deleteSessionMutation, refreshArchivedSessions]);
  const handleDeleteAllArchivedSessions = useCallback(() => {
    void (async () => {
      const sessionIds: string[] = [];
      let cursor = "";
      do {
        const page = await listArchivedChatSessions({ limit: 200, cursor });
        for (const item of page.items) {
          if (!item.id || isBusyPhase(item.currentPhase || item.status)) {
            continue;
          }
          sessionIds.push(item.id);
        }
        cursor = page.nextCursor || "";
      } while (cursor);
      try {
        for (let index = 0; index < sessionIds.length; index += 100) {
          await bulkDeleteSessionsMutation.mutateAsync({
            sessionIds: sessionIds.slice(index, index + 100),
          });
        }
      } finally {
        refreshArchivedSessions();
      }
    })();
  }, [bulkDeleteSessionsMutation, refreshArchivedSessions, isBusyPhase]);

  const handleTogglePinSession = useCallback((session: SessionSummary) => {
    setSessionContextMenu(null);
    pinSessionMutation.mutate({
      sessionId: session.id,
      pinned: !(Number(session.pinnedAtMs ?? 0) > 0),
    });
  }, [pinSessionMutation, setSessionContextMenu]);

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
    directoryGatePending,
  });
  const openSessionReportLibrary = useCallback((session: SessionSummary) => {
    const row = financialAssistants.data?.find((item) => item.agentId === session.agentId);
    if (!row?.knowledgeBaseId) {
      return;
    }
    setSessionContextMenu(null);
    navigate(agentCenterMemoryRoute({
      agentId: row.agentId,
      knowledgeBaseId: row.knowledgeBaseId,
      returnLabel: "chat",
      returnTo: `/chat?session=${encodeURIComponent(session.id)}`,
    }));
  }, [financialAssistants.data, navigate, setSessionContextMenu]);
  const sessionReportLibraryOpener = (
    contextMenuSession && financialAssistants.data?.some((item) =>
      item.agentId === contextMenuSession.agentId && item.knowledgeBaseId)
  )
    ? openSessionReportLibrary
    : undefined;
  const conversationIndexPanel = (
    <ChatConversationIndexPanel
      activeGroupRoomId={activeGroupRoomId}
      activeSessionId={activeSessionId}
      agentContextMenu={agentContextMenu}
      agentRenameDraft={agentRenameDraft}
      agentsById={agentsById}
      allVisibleSessions={allVisibleSessions}
      allVisibleSessionsSelected={allVisibleSessionsSelected}
      archiveVisibleAgents={archiveVisibleAgents}
      archivedSessions={archivedSessions}
      archivedSessionsPending={archivedSessionsQuery.isPending}
      archivedTotalEstimate={archivedSessionsQuery.data?.totalEstimate ?? 0}
      beginRenameSession={beginRenameSession}
      bulkDeleteSessionsMutation={bulkDeleteSessionsMutation}
      bulkRemoveSessions={bulkRemoveSessions}
      bulkSessionPending={bulkSessionPending}
      cancelAgentRename={cancelAgentRename}
      cancelRenameSession={cancelRenameSession}
      clearBulkSessions={clearBulkSessions}
      collapsedConversationGroups={collapsedConversationGroups}
      contextMenuAddToReviewDisabled={contextMenuAddToReviewDisabled}
      contextMenuAddToReviewPending={contextMenuAddToReviewPending}
      contextMenuAgentArchivePending={contextMenuAgentArchivePending}
      contextMenuClearHistoryDisabled={contextMenuClearHistoryDisabled}
      contextMenuClearHistoryPending={contextMenuClearHistoryPending}
      contextMenuClearHistoryVisible={contextMenuClearHistoryVisible}
      contextMenuDeleteDisabled={contextMenuDeleteDisabled}
      contextMenuSession={contextMenuSession}
      contextMenuSessionId={contextMenuSessionId}
      conversationIndexLoading={conversationIndexLoading}
      createSessionMutation={createSessionMutation}
      deleteSessionMutation={deleteSessionMutation}
      directoryFilterText=""
      editingSessionId={editingSessionId}
      editingSessionTitle={editingSessionTitle}
      filteredConversations={filteredConversations}
      filteredStandaloneGroupConversations={filteredStandaloneGroupConversations}
      filteredTeams={filteredTeams}
      formatConversationIndexTime={formatConversationIndexTime}
      groupPanelActive={groupPanelActive}
      groupedGroupConversationCount={groupedGroupConversationCount}
      groupedGroupConversations={groupedGroupConversations}
      handleAddSessionToReview={handleAddSessionToReview}
      handleArchiveAgent={handleArchiveAgent}
      handleArchiveSession={handleArchiveSession}
      handleClearSessionHistory={handleClearSessionHistory}
      handleCreateAgentSession={handleCreateAgentSession}
      handleDeleteAllArchivedSessions={handleDeleteAllArchivedSessions}
      handleDeleteArchivedSession={handleDeleteArchivedSession}
      handleDeleteSession={handleDeleteSession}
      handleOpenAgent={handleOpenAgent}
      handleOpenAgentConfig={handleOpenAgentConfig}
      handleOpenAgentLatestSession={handleOpenAgentLatestSession}
      handleOpenDirectSession={handleOpenDirectSession}
      handleOpenGroupRoom={handleOpenGroupRoom}
      handlePrefetchDirectSession={handlePrefetchDirectSession}
      handleRenameAgent={handleRenameAgent}
      handleTogglePinSession={handleTogglePinSession}
      lang={lang}
      onOpenReportLibrary={sessionReportLibraryOpener}
      openAgentContextMenu={openAgentContextMenu}
      openSessionAgentConfig={openSessionAgentConfig}
      openSessionContextMenu={openSessionContextMenu}
      pinSessionMutation={pinSessionMutation}
      railSectionCollapsed={railSectionCollapsed}
      renameAgentMutation={renameAgentMutation}
      renameSessionMutation={renameSessionMutation}
      resolveModelLabel={resolveModelLabel}
      runtimeRunningSessionIds={runtimeRunningSessionIds}
      searchHasTerm={searchHasTerm}
      selectVisibleBulkSessions={selectVisibleBulkSessions}
      selectedBulkSessionIds={selectedBulkSessionIds}
      selectedBulkSessions={selectedBulkSessions}
      selectedChatAgentId={selectedChatAgentId}
      sessionArchiveMutation={sessionArchiveMutation}
      sessionBulkCopy={sessionBulkCopy}
      sessionBulkNotice={sessionBulkNotice}
      sessionComposerErrors={sessionComposerErrors}
      sessionContextMenu={sessionContextMenu}
      sessionIdsNeedingApproval={sessionIdsNeedingApproval}
      sessionListPrefs={sessionListPrefs}
      sessionsBlockingError={Boolean(sessionsErrorState.blockingError)}
      sessionsById={sessionsById}
      sessionsErrorMessage={sessionsErrorMessage}
      sessionsTransientError={Boolean(sessionsErrorState.transientError)}
      setAgentContextMenu={setAgentContextMenu}
      setAgentRenameDraftName={setAgentRenameDraftName}
      setEditingSessionTitle={setEditingSessionTitle}
      setRailSectionCollapsed={setRailSectionCollapsed}
      setSessionContextMenu={setSessionContextMenu}
      setSessionListPrefs={setSessionListPrefs}
      showArchivedSessions={showArchivedSessions}
      statusLabel={statusLabel}
      submitAgentRename={submitAgentRename}
      submitRenameSession={submitRenameSession}
      t={t}
      teamRoomsByTeamId={teamRoomsByTeamId}
      teams={teams}
      toggleBulkSession={toggleBulkSession}
      toggleConversationGroup={toggleConversationGroup}
      visibleDirectSessionIds={visibleDirectSessionIds}
    />
  );

  const openOrdinarySideChat = useCallback((draft: string, sendDraft: boolean) => {
    if (!ordinaryChangeRail || !activeSessionId || detail?.sessionKind === "child") {
      return;
    }
    const sessionId = activeSessionId;
    const titleBase = lang === "zh" ? "辅助对话" : "Side chat";
    selectSessionUtilityRail();
    setRailsBySession((current) => ({
      ...current,
      [sessionId]: openFreshChatRightRailSideTab(current[sessionId] ?? EMPTY_CHAT_RIGHT_RAIL, {
        titleBase,
        draft,
        sendDraft,
      }),
    }));
    setChangeRailOpened(true);
    if (responsiveLayout.rightVisible) {
      setRightPaneCollapsed(false);
    } else {
      setResponsiveOverlayPane("right");
    }
  }, [
    activeSessionId,
    detail?.sessionKind,
    lang,
    ordinaryChangeRail,
    responsiveLayout.rightVisible,
    setResponsiveOverlayPane,
    setRightPaneCollapsed,
  ]);

  const openOrdinaryRailFile = useCallback((path: string) => {
    const filePath = path.trim();
    const requestSessionId = groupPanelActive
      ? `group:${activeGroupRoomId}`
      : (activeSessionId?.trim() || "");
    if (!ordinaryChangeRail || !requestSessionId || (!groupPanelActive && detail?.sessionKind === "child") || !filePath) {
      return;
    }
    const title = filePath.split(/[\\/]/).filter(Boolean).pop() || filePath;
    requestChatRightRailOpen({
      sessionId: requestSessionId,
      kind: "file",
      title,
      filePath,
    });
  }, [activeGroupRoomId, activeSessionId, detail?.sessionKind, groupPanelActive, ordinaryChangeRail]);

  // Conversation surface model, memoized so unrelated workbench renders (rails,
  // dialogs, composer state) do not re-render ConversationView: the memo gate
  // lives on ConversationView and needs stable prop references. The streaming
  // activeTurnMessage is intentionally NOT part of this model — it is
  // projected from the active-turn layer store inside
  // ChatConversationComposerBridge, the single per-frame subscriber.
  const conversationModel = useMemo(
    () => (detail ? {
      sessionId: activeSessionId ?? detail.id,
      title: detail.title,
      phase: detail.currentPhase,
      // Session summary carries an absolute workspace root (backend resolves
      // relative paths against PROJECT_ROOT); markdown workspace-file links
      // resolve against it. Undefined keeps links inert (legacy behavior).
      sessionWorkspacePath: detail.workspaceRoot || detail.workspacePath,
      messages: detail.messages,
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
      changedFiles: detail.changedFiles ?? EMPTY_SESSION_CHANGED_FILES,
      defaultFileContext: detail.defaultFileContext,
      showHeader: false,
      showSessionOverview: false,
      companionMode: verifiedCompanionMode,
      // Historical mental snapshots are conversation evidence; next-turn toggle only affects submit.
      showMentalSnapshots: !verifiedCompanionMode,
      promptSuggestionEnabled: activePromptSuggestionEnabled,
      composerFocusSignal:
        composerFocusRequest.sessionId === activeSessionId
          ? composerFocusRequest.signal
          : "",
      onComposerFocusRequestSettled: settleSessionComposerFocusRequest,
      composer: financeSurface ? { ...companionConversationComposer, placeholder: lang === "zh" ? "追问这只股票…" : "Ask about this stock…" } : companionConversationComposer,
      composerLeadingControl: verifiedCompanionMode ? undefined : (
        <ChatComposerPlusMenu
          lang={lang}
          attachmentDisabled={companionConversationComposer.attachmentInputDisabled}
          onAddAttachments={handleAddComposerAttachments}
          sessionReferences={composerSessionReferenceOptions}
          onAddSessionReference={handleAddComposerReference}
          knowledgeReferenceOptions={composerKnowledgeReferenceOptions}
          onAddKnowledgeReference={handleAddComposerReference}
          labels={{
            composerAttachFiles: t("composerAttachFiles"),
            composerReferenceKnowledgeFiles: t("composerReferenceKnowledgeFiles"),
            composerReferenceKnowledgeUnavailable: t("composerReferenceKnowledgeUnavailable"),
            composerReferenceKnowledgeTitle: t("composerReferenceKnowledgeTitle"),
            composerReferenceKnowledgeDescription: t("composerReferenceKnowledgeDescription"),
            composerReferenceKnowledgeSearch: t("composerReferenceKnowledgeSearch"),
            composerReferenceKnowledgeEmpty: t("composerReferenceKnowledgeEmpty"),
          }}
          mentalModelEnabled={mentalModelEnabledForNextTurn}
          runtimeStatusEnabled={runtimeStatusEnabledForNextTurn}
          promptSuggestionEnabled={activePromptSuggestionEnabled}
          capabilityDisabled={!activeSessionId}
          onMentalModelEnabledChange={handleMentalModelEnabledChange}
          onRuntimeStatusEnabledChange={handleRuntimeStatusEnabledChange}
          onPromptSuggestionEnabledChange={handlePromptSuggestionEnabledChange}
          directSession={!financeSurface && agentDirectSessionMismatch && agentPrimaryDirectSessionId ? {
            id: agentPrimaryDirectSessionId,
            label: sessionBindingMismatchLine,
            onOpen: () => handleOpenDirectSession(agentPrimaryDirectSessionId),
            onPrefetch: () => handlePrefetchDirectSession(agentPrimaryDirectSessionId),
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
      permissionControl: !financeSurface && !verifiedCompanionMode && activeSessionAgent ? {
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
        onChange: (permissionPreset: AgentPermissionPreset) => {
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
      llmControl: financeSurface || verifiedCompanionMode ? undefined : sessionLlmControl,
      turnModelControl: financeSurface || verifiedCompanionMode ? undefined : turnModelControl,
      onOpenAgentModelConfig: !financeSurface && !verifiedCompanionMode && activeSessionAgent
        ? () => handleOpenAgentConfig(activeSessionAgent, sessionsById.get(activeSessionId ?? "") ?? null)
        : undefined,
      composerContextRing: financeSurface || verifiedCompanionMode ? null : composerContextRing,
      onOpenComposerContextDetail: !financeSurface && !verifiedCompanionMode && cacheDetailAvailable ? openCacheDetail : undefined,
      onCreateSession: !verifiedCompanionMode && selectedChatAgent ? () => handleCreateAgentSession(selectedChatAgent) : undefined,
      onOpenSideChat: ordinaryChangeRail && detail.sessionKind !== "child" ? openOrdinarySideChat : undefined,
      onOpenRailFile: ordinaryChangeRail && detail.sessionKind !== "child" ? openOrdinaryRailFile : undefined,
      slashCommandSuggestions: verifiedCompanionMode ? [] : slashCommandSuggestions,
      slashSkillsCatalogState: verifiedCompanionMode ? "ready" : slashSkillsCatalogState,
      composerReferenceOptions: verifiedCompanionMode ? [] : composerKnowledgeReferenceOptions,
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
      onRetryComposerAttachment: handleRetryComposerAttachmentUpload,
      onRetryComposerAttachmentUploads: handleRetryComposerAttachmentUploads,
      onAddComposerReference: handleAddComposerReference,
      onRemoveComposerReference: handleRemoveComposerReference,
      onEditUserMessage: handleEditUserMessage,
      onRegenerateAssistantMessage: handleRegenerateAssistantMessage,
      onSwitchMessageVersion: handleSwitchMessageVersion,
      onForkSessionFromNode: verifiedCompanionMode ? undefined : handleForkSessionFromNode,
      branchVersionSwitchDisabled: (
        sessionBusy
        || (switchHeadMutation.isPending
          && switchHeadMutation.variables?.sessionId === activeSessionId)
      ),
      regenerableAssistantMessageId,
      regenerateDisabled: sessionBusy || regenerateMutation.isPending,
      regeneratePending: (
        regenerateMutation.isPending
        && regenerateMutation.variables?.sessionId === activeSessionId
      ),
      onRetryTurn: handleRetryFailedTurn,
      retryTurnDisabled: sessionBusy || regenerateMutation.isPending,
      retryTurnPending: (
        regenerateMutation.isPending
        && regenerateMutation.variables?.sessionId === activeSessionId
      ),
      onCancelComposerMode: resolvedEditTarget ? handleCancelEditMessage : undefined,
      onLoadEarlierMessages: handleLoadEarlierSessionMessages,
      onSubmit: handleSubmitTurn,
      onStop: handleStopTurn,
      onSafeGuidance: () => handleSubmitGuidance("safe"),
      onInterruptGuidance: () => handleSubmitGuidance("interrupt"),
      onFollowupQueueUpdate: handleFollowupQueueUpdate,
      onFollowupQueueRemove: handleFollowupQueueRemove,
      onFollowupQueueMove: handleFollowupQueueMove,
      onFollowupQueueSteer: handleFollowupQueueSteer,
      onFollowupQueueSendNow: handleFollowupQueueSendNow,
      followupQueueSteerLabel: t("immediateSteer"),
    } : null),
    [
      activeAgentAvatarFallback,
      activeAgentAvatarImageUrl,
      activeAgentDisplayName,
      activeGroupRoom,
      activeGroupTeam,
      activeGroupTeamOwned,
      activePromptSuggestionEnabled,
      activeSessionAgent,
      activeSessionId,
      agentDirectSessionMismatch,
      agentPermissionPresetMutation,
      agentPrimaryDirectSessionId,
      cacheDetailAvailable,
      composerContextRing,
      composerFocusRequest,
      composerKnowledgeReferenceOptions,
      composerSessionReferenceOptions,
      currentTaskSummary,
      detail,
      financeSurface,
      handleAddComposerAttachments,
      handleAddComposerReference,
      handleCancelEditMessage,
      handleComposerChange,
      handleConversationStreamingFramePaint,
      handleCreateAgentSession,
      handleEditUserMessage,
      handleFollowupQueueMove,
      handleFollowupQueueRemove,
      handleFollowupQueueSendNow,
      handleFollowupQueueSteer,
      handleFollowupQueueUpdate,
      handleForkSessionFromNode,
      handleLoadEarlierSessionMessages,
      handleMentalModelEnabledChange,
      handleOpenDirectSession,
      handlePrefetchDirectSession,
      handlePromptSuggestionEnabledChange,
      handleRegenerateAssistantMessage,
      handleRemoveComposerAttachment,
      handleRemoveComposerReference,
      handleRetryComposerAttachmentUpload,
      handleRetryComposerAttachmentUploads,
      handleRetryFailedTurn,
      handleRuntimeStatusEnabledChange,
      handleStopTurn,
      handleSubmitGuidance,
      handleSubmitTurn,
      handleSwitchMessageVersion,
      lang,
      loadEarlierSessionMessagesMutation,
      mentalModelEnabledForNextTurn,
      navigate,
      openCacheDetail,
      openOrdinaryRailFile,
      openOrdinarySideChat,
      ordinaryChangeRail,
      regenerateMutation,
      regenerableAssistantMessageId,
      resolvedEditTarget,
      resolveConversationTurnAvatar,
      runtime,
      selectedChatAgent,
      sessionBusy,
      sessionLlmControl,
      activeSessionAgent,
      handleOpenAgentConfig,
      sessionBindingMismatchLine,
      sessionTranscriptPending,
      setGroupManageDialogOpen,
      settleSessionComposerFocusRequest,
      slashCommandSuggestions,
      slashSkillsCatalogState,
      standardGroupRoomActive,
      switchHeadMutation,
      t,
      verifiedCompanionMode,
      companionConversationComposer,
    ],
  );

  const financialResearchBridge = useFinancialResearchSessionBridge({
    sessionId: activeSessionId ?? "",
    agentId: detail?.agentId,
    title: detail?.title ?? "",
    status: detail?.status ?? "",
    busy: sessionBusy,
    stopping: sessionStopping,
    terminalReason: detail?.terminalReason,
    lastTurnStatus: detail?.lastTurnStatus,
    lastTurnTerminalTurnId: detail?.lastTurnTerminalTurnId,
    messages: detail?.messages,
    phase: detail?.currentPhase,
    error: detail?.lastTurnError?.message || companionConversationComposer.error,
    submitPending,
    transcriptPending: sessionTranscriptPending,
    approvalPending: Boolean(toolApproval),
    onComposerChange: handleComposerChange,
    onFocusComposer: requestSessionComposerFocus,
    composerValue: companionConversationComposer.value,
    onSubmit: handleSubmitTurn,
    sessionLlmOptions,
    sessionLlmOptionsLoading: sessionLlmOptionsQuery.isLoading,
    sessionLlmOptionsError: sessionLlmOptionsQuery.isError,
    turnModelSelection,
    onTurnModelSelectionChange: setTurnModelSelectionForSession,
  });

  const headerExportVisible = !verifiedCompanionMode && !groupPanelActive && !financeSurface
    && !sessionBrowserVisible && conversationWorkspaceTab === "agent" && Boolean(conversationModel)
    && !activeCliAgentRunId && !sessionDetailErrorState.blockingError && !invalidChildSessionLinkMessage;

  return (
    <ActiveTurnLayersStoreProvider store={activeTurnLayersStore}>
    {financeSurface ? <FinancialResearchLiveProjection sessionId={activeSessionId ?? ""} agentId={detail?.agentId} messages={detail?.messages ?? EMPTY_FINANCIAL_MESSAGES} /> : null}
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
      ) : ordinaryChangeRail && (changeRail.show || changeRailOpened) ? (
      <ChatRightRail
        className={statusRailClassName}
        lang={lang}
        sessionId={groupPanelActive ? "" : (activeSessionId ?? "")}
        sessionKind={groupPanelActive ? "group" : detail?.sessionKind}
        model={railModel}
        onModelChange={updateRailModel}
        onOpenSession={(id) => openSession(id, { telemetrySource: "right_rail_project" })}
        onCollapse={toggleChangeRail}
        devtools={detail ? {
          phase: detail.currentPhase,
          status: detail.status,
          messages: detail.messages,
        } : null}
        terminalRun={activeCliAgentRun ?? cliAgentRunTabs[0] ?? null}
        terminalMountedInCenter={Boolean(activeCliAgentRun)}
        onTerminalSessionChange={handleCliAgentTerminalSessionChange}
        onOpenFile={(path) => {
          if (activeSessionId) {
            openPreviewTab(activeSessionId, path);
          }
        }}
        preface={groupPanelActive ? null : <FinancialAssistantChatNote sessionId={activeSessionId} lang={lang} />}
        review={{
          sessionTitle: lang === "zh" ? "这次对话" : "This chat",
          sessionEmptyLabel: lang === "zh" ? "这次对话还没有改动文件" : "This chat has no changed files yet",
          sessionPaths: changeRail.paths,
          sessionSelectedPath: reviewSource === "git" ? null : sessionReviewPath,
          sessionChangedPaths: changedPathSet,
          gitTitle: gitRail.branch
            ? (lang === "zh" ? `仓库 · ${gitRail.branch}` : `Repository · ${gitRail.branch}`)
            : (lang === "zh" ? "仓库" : "Repository"),
          gitEmptyLabel: lang === "zh" ? "工作区是干净的" : "The worktree is clean",
          gitPending: gitRail.pending,
          gitPendingLabel: lang === "zh" ? "正在读取仓库" : "Reading the repository",
          gitUnavailableLabel: gitRail.unavailable
            ? (gitRail.errorText || describeError(gitRail.error, t("loadFailed")))
            : "",
          gitPaths: gitRail.paths,
          gitSelectedPath: gitReviewPath,
          gitDetailByPath: gitRail.detailByPath,
          diff: changePreview.diff,
          diffLoading: changePreview.diffLoading,
          hasDiff: changePreview.hasDiff,
          file: changePreview.file,
          fileLoading: changePreview.fileLoading,
          fileError: changePreview.fileError ? describeError(changePreview.fileError, t("loadFailed")) : "",
          sourceLabel: detail?.title ?? t("currentSession"),
          onSelectSessionFile: (path) => {
            if (!activeSessionId) {
              return;
            }
            setReviewPick({ sessionId: activeSessionId, source: "session", path });
            openPreviewTab(activeSessionId, path);
          },
          onSelectGitFile: (path) => {
            const reviewKey = groupPanelActive ? `group:${activeGroupRoomId}` : activeSessionId;
            if (!reviewKey) {
              return;
            }
            gitRail.selectPath(path);
            setReviewPick({ sessionId: reviewKey, source: "git", path });
          },
        }}
      />
      ) : null}
      leftResizeHandle={
      financeSurface ? null : responsiveLayout.leftVisible ? verifiedCompanionMode ? <PaneCollapseHandle
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
      /> : conversationIndexCollapsed ? null : <PaneResizeHandle
        label={t("resizeLeftPanel")}
        className={styles.resizeHandleLeft}
        active={dragState?.side === "left"}
        valueNow={leftPanelWidth}
        valueMin={MIN_LEFT_PANEL_WIDTH}
        valueMax={MAX_LEFT_PANEL_WIDTH}
        onPointerDown={(event) => handleResizeStart("left", event)}
        onKeyDown={(event) => handleResizeKeyDown("left", event)}
      /> : null
      }
      center={(
      <ChatWorkbenchCenterColumn
        className={centerPaneClassName}
        surfaceClassName={styles.centerSurface}
        tabStrip={(
          <ChatCodingCenterTabs
            lang={lang}
            chatReturnTarget={chatReturnTarget}
            chatReturnLabel={chatReturnLabel}
            groupPanelActive={groupPanelActive}
            projectBusActive={projectBusActive}
            financeSurface={financeSurface}
            verifiedCompanionMode={verifiedCompanionMode}
            selectedChatAgentId={selectedChatAgentId}
            agentSessionTabs={agentSessionTabs}
            cliAgentRunTabs={cliAgentRunTabs}
            activeCompanion={activeCompanion}
            leftOverlayVisible={responsiveLayout.leftVisible}
            rightOverlayVisible={responsiveLayout.rightVisible}
            conversationIndexCollapsed={conversationIndexCollapsed}
            setLeftRailCollapsed={setLeftRailCollapsed}
            conversationWorkspaceTab={conversationWorkspaceTab}
            sessionBrowserVisible={sessionBrowserVisible}
            setSessionBrowserOpen={setSessionBrowserOpen}
            headerExportVisible={headerExportVisible}
            conversationModel={conversationModel}
            conversationIndexOverlayOpen={conversationIndexOverlayOpen}
            ordinaryChangeRail={ordinaryChangeRail}
            changeRailVisible={changeRailVisible}
            statusRailOverlayOpen={statusRailOverlayOpen}
            toggleChangeRail={toggleChangeRail}
            setResponsiveOverlayPane={setResponsiveOverlayPane}
            activeSessionId={activeSessionId}
            setActiveTab={setActiveTab}
            activeCliAgentRunId={activeCliAgentRunId}
            agentsById={agentsById}
            buildSessionReferencePayload={buildSessionReferencePayload}
            contextMenuSessionId={contextMenuSessionId}
            createSessionPending={createSessionMutation.isPending}
            deleteSessionPending={deleteSessionMutation.isPending}
            pendingDeleteSessionId={String(deleteSessionMutation.variables?.sessionId || "").trim()}
            editingSessionId={editingSessionId}
            editingSessionTitle={editingSessionTitle}
            renamePending={renameSessionMutation.isPending}
            renameSessionId={renameSessionMutation.variables?.sessionId ?? ""}
            resolveModelLabel={resolveModelLabel}
            teams={teams}
            runtimeRunningSessionIds={runtimeRunningSessionIds}
            sessionIdsNeedingApproval={sessionIdsNeedingApproval}
            statusLabel={statusLabel}
            t={t}
            onCancelRename={cancelRenameSession}
            onContextMenu={openSessionContextMenu}
            onDragReference={startSessionReferenceDrag}
            closeCliAgentRun={closeCliAgentRun}
            onCreateSession={handleCreateSession}
            onDeleteSession={handleDeleteSession}
            onOpenDirectSession={handleOpenDirectSession}
            onPrefetchDirectSession={handlePrefetchDirectSession}
            onRenameTitleChange={setEditingSessionTitle}
            onSubmitRename={submitRenameSession}
            workspace={workspace}
            closePreviewTab={closePreviewTab}
          />
        )}
        surface={(
          <ChatCenterSessionSurface
            browser={sessionBrowserVisible ? (
              <ChatSessionBrowser
                sessions={allVisibleSessions}
                agentsById={agentsById}
                activeSessionId={activeSessionId}
                lang={lang}
                resolveModelLabel={resolveModelLabel}
                runtimeRunningSessionIds={runtimeRunningSessionIds}
                sessionIdsNeedingApproval={sessionIdsNeedingApproval}
                loading={conversationIndexLoading || (!agentsQuery.data && agentsQuery.isPending)}
                error={sessionsErrorMessage || (agentsQuery.isError ? describeError(agentsQuery.error, t("loadFailed")) : "")}
                createPending={createSessionMutation.isPending}
                createDisabled={!selectedChatAgentId}
                onOpen={(sessionId) => {
                  setSessionBrowserOpen(false);
                  handleOpenDirectSession(sessionId);
                }}
                onCreate={() => {
                  setSessionBrowserOpen(false);
                  handleCreateSession();
                }}
                onRetry={() => { void Promise.allSettled([rawSessionsQuery.refetch(), agentsQuery.refetch()]); }}
              />
            ) : undefined}
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
            <ChatCodingGroupSurface
              lang={lang}
              projectBusActive={projectBusActive}
              standardGroupRoomActive={standardGroupRoomActive}
              groupRoomInitialLoading={groupRoomInitialLoading}
              activeGroupRoom={activeGroupRoom}
              activeGroupRoomId={activeGroupRoomId}
              availableGroupParticipantCount={availableGroupParticipantCount}
              visibleGroupParticipants={availableGroupParticipants}
              onManageGroupRoom={() => setGroupManageDialogOpen(true)}
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
              runtimeUserName={runtime?.userName}
              mentalModelEnabled={mentalModelEnabledForNextTurn}
              runtimeStatusEnabled={runtimeStatusEnabledForNextTurn}
              promptSuggestionEnabled={activePromptSuggestionEnabled}
              onMentalModelEnabledChange={handleMentalModelEnabledChange}
              onRuntimeStatusEnabledChange={handleRuntimeStatusEnabledChange}
              onPromptSuggestionEnabledChange={handlePromptSuggestionEnabledChange}
              chatReturnTarget={chatReturnTarget}
              activeGroupTeam={activeGroupTeam}
              activeGroupTeamOwned={activeGroupTeamOwned}
              onNavigateTeam={(teamId) => navigate(teamWorkspaceRoute(teamId))}
              projectBusRefreshing={projectAgentBusQuery.isFetching}
              projectBusRefreshError={projectAgentBusQuery.isError ? describeError(projectAgentBusQuery.error, t("loadFailed")) : ""}
              projectBusSendPending={sendProjectBusMessageMutation.isPending}
              projectBusRevokePending={revokeProjectBusMessageMutation.isPending}
              groupRoomRefreshing={activeGroupRoomQuery.isFetching}
              groupRoomRefreshError={activeGroupRoomQuery.isError ? describeError(activeGroupRoomQuery.error, t("loadFailed")) : ""}
              groupStreamConnected={groupStreamConnected}
              groupSpeakerStreams={groupSpeakerStreams}
              groupSpeakerProgress={groupSpeakerProgress}
              groupTimeline={groupTimeline}
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
              workspaceRoot={detail?.workspaceRoot || detail?.workspacePath || directSessionActiveSummary?.workspacePath || undefined}
              onOpenRailFile={openOrdinaryRailFile}
            />
            )}
            sessionWorkspace={(
            <FollowupQueueTogglePauseContext.Provider value={handleFollowupQueueTogglePause}>
            <ChatSessionWorkspacePanel
              activeCliAgentRunAvailable={Boolean(activeCliAgentRun)}
              activeCliAgentRunId={activeCliAgentRunId}
              activeSessionId={activeSessionId}
              activeTurnStreamState={activeTurnStreamState}
              blockingErrorMessage={sessionDetailErrorMessage}
              cliAgentRunEmptyLabel={lang === "zh" ? "这个 CLI 工具页还没有可显示的运行记录。" : "This CLI tool page has no run to display."}
              conversation={conversationModel}
              hideExportControl={headerExportVisible}
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
              preface={null}
              noSessionsLabel={t("noSessionsYet")}
              notices={activeRuntimeNotices}
              sessionsPending={sessionsQuery.isPending}
              toolApproval={toolApproval}
              transientErrorMessage={sessionDetailErrorMessage}
              workspaceActiveTab={conversationWorkspaceTab}
              onApproveToolApproval={handleApproveToolApproval}
              onApproveToolForSession={handleApproveToolForSession}
              onRejectToolApproval={handleRejectToolApproval}
            />
            </FollowupQueueTogglePauseContext.Provider>
            )}
          />
        )}
      />
      )}
      rightResizeHandle={
      !sessionBrowserVisible && (verifiedCompanionMode || (ordinaryChangeRail && (changeRail.show || changeRailOpened))) && responsiveLayout.rightVisible ? (ordinaryChangeRail ? (statusRailCollapsed ? null : <PaneResizeHandle
        label={t("resizeRightPanel")}
        className={styles.resizeHandleRight}
        active={dragState?.side === "right"}
        valueNow={rightPanelWidth}
        valueMin={MIN_RIGHT_PANEL_WIDTH}
        valueMax={MAX_RIGHT_PANEL_WIDTH}
        onPointerDown={(event) => handleResizeStart("right", event)}
        onKeyDown={(event) => handleResizeKeyDown("right", event)}
      />) : <PaneCollapseHandle
        side="right"
        collapsed={statusRailCollapsed}
        separatorLabel={t("resizeRightPanel")}
        collapseLabel={verifiedCompanionMode ? (lang === "zh" ? "收起状态栏" : "Collapse status rail") : (lang === "zh" ? "收起改动" : "Collapse changes")}
        expandLabel={verifiedCompanionMode ? (lang === "zh" ? "展开状态栏" : "Expand status rail") : (lang === "zh" ? "展开改动" : "Expand changes")}
        className={styles.resizeHandleRight}
        active={dragState?.side === "right"}
        valueNow={rightPanelWidth}
        valueMin={MIN_RIGHT_PANEL_WIDTH}
        valueMax={MAX_RIGHT_PANEL_WIDTH}
        onToggle={() => setRightPaneCollapsed((current) => !current)}
        onPointerDown={(event) => handleResizeStart("right", event)}
        onKeyDown={(event) => handleResizeKeyDown("right", event)}
      />) : null
      }
      conversationIndex={financeSurface ? null : verifiedCompanionMode ? (
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
        onCollapseConversationIndex={() => {
          if (conversationIndexOverlayOpen) {
            closeResponsiveOverlayPane();
          } else {
            setLeftRailCollapsed(true);
            window.requestAnimationFrame(() => document.getElementById("chat-conversation-index-toggle")?.focus());
          }
        }}
        conversationIndexOverlayOpen={conversationIndexOverlayOpen}
        lang={lang}
        locale={locale}
        t={t}
        standardGroupRoomActive={standardGroupRoomActive}
        rightIndexPanel={rightIndexPanel}
        setRightIndexPanel={setRightIndexPanel}
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
        sessionListPreferences={sessionListPrefs}
        onSessionListPreferencesChange={(patch) => setSessionListPrefs(current => ({ ...current, ...patch }))}
        onOpenSearchAgent={(agent) => { if (!handleOpenAgent(agent)) handleCreateAgentSession(agent); }}
        onOpenSearchTeam={(team) => navigate(teamWorkspaceRoute(team.teamId))}
        showArchivedSessions={showArchivedSessions}
        onToggleShowArchivedSessions={() => setShowArchivedSessions((current) => !current)}
        groupComposerOpen={groupComposerOpen}
        createGroupRoomPending={createGroupRoomMutation.isPending}
        createSessionPending={createSessionMutation.isPending || !selectedChatAgent}
        createAgentButtonRef={agentCreateTriggerRef}
        onCreateAgent={handleCreateAgent}
        onCreateSession={() => {
          if (selectedChatAgent) {
            handleCreateAgentSession(selectedChatAgent);
          }
        }}
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
        onOpenDirectSession={handleOpenDirectSession}
        onPrefetchDirectSession={handlePrefetchDirectSession}
        activeSessionId={activeSessionId}
        onSetActiveTab={setActiveTab}
        sessionIdsNeedingApproval={sessionIdsNeedingApproval}
        runtimeRunningSessionIds={runtimeRunningSessionIds}
        teams={teams}
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
            promptSnapshot={detail?.agentPromptSnapshot}
            promptAssembly={detail?.lastPromptAssembly}
            lastLlmPayloadTrace={lastLlmPayloadTrace}
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
      <ConversationRerunFileChoiceDialog
        open={Boolean(rerunFileChoice)}
        language={lang === "en" ? "en" : "zh"}
        paths={rerunFileChoice?.paths ?? []}
        pending={Boolean(rerunFileChoice?.restoring)}
        error={rerunFileChoice?.error ?? ""}
        onOpenChange={(open) => {
          if (!open) dismissRerunFileChoice();
        }}
        onRestoreAndRerun={() => {
          void confirmRerunFileRestore();
        }}
        onRerunOnly={keepFilesAndRerun}
      />
    </ActiveTurnLayersStoreProvider>
  );
}
