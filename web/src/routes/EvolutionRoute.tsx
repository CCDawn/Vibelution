import "../design/route-css/evolution.tailwind.css";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowUpRight,
  ChevronDown,
  ChevronRight,
  LibraryBig,
  LoaderCircle,
  Play,
  Save,
  Sparkles,
  Pencil,
  Trash2,
  TriangleAlert,
  Wrench,
  X,
} from "lucide-react";
import { lazy, Suspense, type CSSProperties, type KeyboardEvent, type PointerEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import {
  EvolutionActiveRun,
  EvolutionActiveRunAgentBinding,
  EvolutionActiveRunStreamEvent,
  EvolutionActionState,
  ConfigSummary,
  EvolutionRunActionResponse,
  EvolutionWorkbench,
  EvolutionProposalBulkDeleteResponse,
  EvolutionProposalDeleteResponse,
  EvolutionProposalDetail,
  EvolutionProposalUpdateResponse,
  EvolutionLibraryEntry,
  EvolutionWorkspaceSnapshot,
  SupervisedWorktreeRun,
  SelfEvolutionOverview,
  SelfObservationRun,
  SelfObservationRunStartRequest,
  SelfEvolutionTransaction,
  SelfEvolutionHistoryDeleteResponse,
  EvolutionRun,
  EvolutionRoleConversationSession,
  EvolutionClosedLoopRecord,
  EvolutionWorkflowStep,
} from "../api/types";
import { resolvePollingInterval, usePageVisibility } from "../app/pollingPolicy";
import { PaneCollapseHandle } from "../components/layout/PaneCollapseHandle";
import {
  migrateLegacyNumericPanes,
  type PaneSpec,
} from "../components/layout/paneLayoutPersistence";
import {
  migrateLegacyNumericHeight,
  type PaneHeightSpec,
} from "../components/layout/paneHeightPersistence";
import { PaneHeightResizeHandle } from "../components/layout/PaneHeightResizeHandle";
import { usePersistedPaneHeight } from "../components/layout/usePersistedPaneHeight";
import { usePersistedPaneResize } from "../components/layout/usePersistedPaneResize";
import { WORKBENCH_LAYOUT_IDS } from "../components/layout/workbenchLayoutIds";
import {
  VButton,
  VCheckbox,
  VContextualHint,
  VInput,
  VMetricStrip,
  VRouteHeader,
  VSection,
  VStateSurface,
  VStringSelect,
  VSurface,
  VTextarea,
  VTooltip,
} from "../components/vui";
import { useAppI18n } from "../i18n/useAppI18n";
import { useShellStore } from "../store/shellStore";
import { SupervisedApprovalDecisionPanel } from "./SupervisedApprovalDecisionPanel";
import { useEvolutionProposalMutations } from "./evolution/useEvolutionProposalMutations";
import { useEvolutionRunMutations } from "./evolution/useEvolutionRunMutations";
import {
  activeSupervisedWorkflowStep,
  buildSupervisedStartPlaceholder,
  canOpenProposalSourceRun,
  clampScore,
  compactCaseObject,
  compactTimestamp,
  datasetBenchmarkDetail,
  datasetCatalogStatusLabel,
  datasetUsabilityLabel,
  displaySupervisedRunStatus,
  displaySupervisedRunSummary,
  displaySupervisedTechnicalText,
  formatTurnRange,
  hasSupervisedAgentBindings,
  isLocalSupervisedStartPlaceholder,
  isSelfEvolutionCandidateItem,
  LOCAL_SUPERVISED_RUN_PREFIX,
  proposalDisplaySourceRun,
  proposalEditDraftFromDetail,
  SUPERVISED_RUN_MEMBER_ROLES,
  SUPERVISED_WORKFLOW_STEPS,
  supervisedMemberAgentManagementRoute,
  supervisedMemberChatRoute,
  supervisedDatasetLimitFromInput,
  supervisedMemberModelId,
  supervisedMemberModelLabel,
  supervisedPreflightIssue,
  supervisedProposalStatusLabel,
  supervisedRoleConversationSession,
  supervisedRunBucketLabel,
  supervisedWorkflowStepLabel,
  toLimitInput,
  type ProposalEditDraft,
  type SupervisedClosedLoopRecord,
  type SupervisedMemberRole,
  type SupervisedMentalModelMode,
  type SupervisedPreflightIssue,
  type SupervisedRunMember,
  type SupervisedWorkflowCard,
  type SupervisedWorkflowDefinition,
  type SupervisedWorkflowStepId,
} from "./evolution/evolutionRouteModel";

import { SupervisedWorkspaceControls } from "./SupervisedWorkspaceControls";
import { SupervisedAgentConversationPanel } from "./SupervisedAgentConversationPanel";
import { type SupervisedWorkspaceWorkflowStep } from "./SupervisedWorkspaceTabs";
import {
  isSelfEvolutionWorktreeRun,
  selectRecentSupervisedWorktreeRun,
} from "./supervisedWorktreeReview";
import {
  isLiveSupervisedRunStatus,
  parseRunStreamSnapshot,
  selectRunSnapshotWithRunId,
  selectSupervisedRunStreamTarget,
  shouldIgnoreActiveRunSnapshot,
} from "./evolutionLiveRun";
import { supervisedDecisionLabel } from "./supervisedRunRecordLabel";
import { buildSupervisedRunControlSummary } from "./supervisedRunSummary";
import { buildSupervisedCaseTraceItems, type SupervisedCaseTraceItem, type SupervisedCaseTraceTone } from "./supervisedCaseTrace";
import type {
  EvolutionActiveRunClosedLoopLedger,
  EvolutionActiveRunMonitorEventItem,
  EvolutionActiveRunMonitorMetric,
  EvolutionActiveRunMonitorRunView,
} from "./EvolutionActiveRunMonitorPanel";
import { EvolutionSelfTrackBoundary } from "./EvolutionSelfTrackBoundary";
import { createEvolutionWorkspaceCache } from "./evolutionWorkspaceCache";
import { modelDisplayLabel } from "./agentDisplay";
import styles from "./EvolutionRoute.styles";

/** U3: supervised secondary view panels — live/runs/library packs stay off each other's graph. */
const EvolutionActiveRunMonitorPanel = lazy(() =>
  import("./EvolutionActiveRunMonitorPanel").then((module) => ({
    default: module.EvolutionActiveRunMonitorPanel,
  })),
);
const EvolutionRunRecordsPanel = lazy(() =>
  import("./EvolutionRunRecordsPanel").then((module) => ({
    default: module.EvolutionRunRecordsPanel,
  })),
);
const EvolutionProposalActionBandsPanel = lazy(() =>
  import("./EvolutionProposalActionBandsPanel").then((module) => ({
    default: module.EvolutionProposalActionBandsPanel,
  })),
);

type RunFilter = "all" | "success" | "failed";
type LibraryView = "items" | "pending";
type LibraryStatusFilter =
  | "all"
  | "proposed"
  | "applied"
  | "active"
  | "superseded"
  | "rolled_back"
  | "missing";
type LibraryDeleteFilter = "all" | "deletable" | "blocked";
type DatasetCatalogFilter = "all" | "runnable" | "blocked" | "roadmap";
type EvolutionRouteTrack = "supervised" | "self";
type SupervisedRouteView = "live" | "runs" | "library";
type EvolutionRouteProps = {
  forcedTrack?: EvolutionRouteTrack;
  forcedView?: SupervisedRouteView;
};
const CASE_TRACE_TURN_CLASS: Record<SupervisedCaseTraceTone, string> = {
  input: styles.caseTraceTurn_input,
  thought: styles.caseTraceTurn_thought,
  tool: styles.caseTraceTurn_tool,
  assistant: styles.caseTraceTurn_assistant,
  error: styles.caseTraceTurn_error,
};
const SELF_OVERVIEW_REFETCH_INTERVAL_MS = 12_000;
const SELF_OVERVIEW_STALE_TIME_MS = 10_000;

type SupervisedSourceOption =
  | {
      value: string;
      kind: "dataset";
      name: string;
      label: string;
      detail: string;
      caseCount: number | null;
      dataset: NonNullable<EvolutionWorkbench["datasets"]>[number];
    }
  | {
      value: string;
      kind: "bundle";
      name: string;
      label: string;
      detail: string;
      caseCount: number;
      bundle: EvolutionWorkbench["bundles"][number];
    };

const LIBRARY_STATUS_FILTERS: LibraryStatusFilter[] = [
  "all",
  "proposed",
  "applied",
  "active",
  "superseded",
  "rolled_back",
  "missing",
];
const EMPTY_RUNS: EvolutionRun[] = [];
const EMPTY_LIBRARY_ENTRIES: EvolutionLibraryEntry[] = [];
const EMPTY_WORKTREE_RUNS: SupervisedWorktreeRun[] = [];
const EMPTY_AGENT_BINDINGS: Record<string, EvolutionActiveRunAgentBinding> = {};
const EVOLUTION_LAYOUT_ID = WORKBENCH_LAYOUT_IDS.evolution;
const EVOLUTION_RUNS_QUEUE_WIDTH_KEY = "vibelution.evolution.runs-queue-width";
const EVOLUTION_LIBRARY_LIST_WIDTH_KEY = "vibelution.evolution.library-list-width";
const EVOLUTION_LIVE_LAUNCH_WIDTH_KEY = "vibelution.evolution.live-launch-width";
const EVOLUTION_LIVE_RUN_WIDTH_KEY = "vibelution.evolution.live-run-width";
const EVOLUTION_RUNS_QUEUE_PANE: PaneSpec = {
  id: "runs-queue",
  defaultWidth: 380,
  minWidth: 300,
  maxWidth: 520,
};
const EVOLUTION_LIBRARY_LIST_PANE: PaneSpec = {
  id: "library-list",
  defaultWidth: 360,
  minWidth: 280,
  maxWidth: 520,
};
const EVOLUTION_LIVE_LAUNCH_PANE: PaneSpec = {
  id: "live-launch",
  defaultWidth: 360,
  minWidth: 320,
  maxWidth: 520,
};
const EVOLUTION_LIVE_RUN_PANE: PaneSpec = {
  id: "live-run",
  defaultWidth: 380,
  minWidth: 320,
  maxWidth: 560,
};
const EVOLUTION_WIDTH_PANES: PaneSpec[] = [
  EVOLUTION_RUNS_QUEUE_PANE,
  EVOLUTION_LIBRARY_LIST_PANE,
  EVOLUTION_LIVE_LAUNCH_PANE,
  EVOLUTION_LIVE_RUN_PANE,
];
const EVOLUTION_LIVE_IO_HEIGHT_KEY = "vibelution.evolution.live-io-height";
const EVOLUTION_LIVE_IO_HEIGHT_PANE: PaneHeightSpec = {
  id: "live-io",
  defaultHeight: 340,
  minHeight: 260,
  maxHeight: 780,
};
const EVOLUTION_HEIGHT_PANES: PaneHeightSpec[] = [EVOLUTION_LIVE_IO_HEIGHT_PANE];
export function EvolutionRoute({ forcedTrack, forcedView }: EvolutionRouteProps) {
  const {
    lang,
    t,
    statusLabel,
    intakeModeLabel,
    viewLabel,
    decisionLabel,
    riskLabel,
    workbenchSourceLabel,
    proposalActionLabel,
    sourceKindLabel,
  } = useAppI18n({ domains: ["evolution"] });
  const displayDecisionLabel = (decision: string) => supervisedDecisionLabel(decision, lang, decisionLabel);
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const evolutionWorkspaceCache = useMemo(() => createEvolutionWorkspaceCache(queryClient), [queryClient]);
  const evolutionTrack = useShellStore((state) => state.evolutionTrack);
  const setEvolutionTrack = useShellStore((state) => state.setEvolutionTrack);
  const rawEvolutionView = useShellStore((state) => state.evolutionView);
  const setEvolutionView = useShellStore((state) => state.setEvolutionView);
  const evolutionView = forcedView ?? (rawEvolutionView === "overview" ? "live" : rawEvolutionView);
  const pageVisible = usePageVisibility();
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [runFilter, setRunFilter] = useState<RunFilter>("all");
  const [libraryView, setLibraryView] = useState<LibraryView>("items");
  const [selectedLibraryItemId, setSelectedLibraryItemId] = useState<string | null>(null);
  const [selectedPendingItemId, setSelectedPendingItemId] = useState<string | null>(null);
  const [selectedRunIds, setSelectedRunIds] = useState<string[]>([]);
  const [selectedProposalRunIds, setSelectedProposalRunIds] = useState<string[]>([]);
  const [librarySearchInput, setLibrarySearchInput] = useState("");
  const [libraryStatusFilter, setLibraryStatusFilter] = useState<LibraryStatusFilter>("all");
  const [libraryDeleteFilter, setLibraryDeleteFilter] = useState<LibraryDeleteFilter>("all");
  const [formInitialized, setFormInitialized] = useState(false);
  const [sourceKind, setSourceKind] = useState<"dataset" | "bundle">("dataset");
  const [datasetName, setDatasetName] = useState("");
  const [selectedDatasetCatalogFilter, setSelectedDatasetCatalogFilter] = useState<DatasetCatalogFilter>("runnable");
  const [datasetLimitInput, setDatasetLimitInput] = useState("");
  const datasetLimitInputRef = useRef<HTMLInputElement | null>(null);
  const [bundleNameInput, setBundleNameInput] = useState("");
  const [keepWorktree, setKeepWorktree] = useState(false);
  const [supervisedMentalModelMode, setSupervisedMentalModelMode] = useState<SupervisedMentalModelMode>("follow");
  const [selectedSupervisedWorkflowStepId, setSelectedSupervisedWorkflowStepId] = useState<SupervisedWorkflowStepId | null>(null);
  const [selectedSupervisedAgentRole, setSelectedSupervisedAgentRole] = useState<SupervisedMemberRole | null>(null);
  const [liveActiveRun, setLiveActiveRun] = useState<EvolutionActiveRun | null>(null);
  const [recentSupervisedWorktreeRunId, setRecentSupervisedWorktreeRunId] = useState<string | null>(null);
  const [selfGoalInput, setSelfGoalInput] = useState("");
  const [selfGoalInitialized, setSelfGoalInitialized] = useState(false);
  const [selectedSelfObservationRunId, setSelectedSelfObservationRunId] = useState("");
  const [actionFeedback, setActionFeedback] = useState("");
  const [selfActionFeedback, setSelfActionFeedback] = useState("");
  const [runRecordsFeedback, setRunRecordsFeedback] = useState("");
  const [libraryFeedback, setLibraryFeedback] = useState("");
  const [proposalEditOpen, setProposalEditOpen] = useState(false);
  const [proposalEditDraft, setProposalEditDraft] = useState<ProposalEditDraft>({
    improvementType: "",
    expectedEffect: "",
    summary: "",
    candidatePrompt: "",
    baselinePrompt: "",
    editNote: "",
  });
  const [proposalEditFeedback, setProposalEditFeedback] = useState("");
  useEffect(() => {
    migrateLegacyNumericPanes(EVOLUTION_LAYOUT_ID, {
      "runs-queue": EVOLUTION_RUNS_QUEUE_WIDTH_KEY,
      "library-list": EVOLUTION_LIBRARY_LIST_WIDTH_KEY,
      "live-launch": EVOLUTION_LIVE_LAUNCH_WIDTH_KEY,
      "live-run": EVOLUTION_LIVE_RUN_WIDTH_KEY,
    });
  }, []);
  const {
    layoutRef: evolutionLayoutRef,
    widths: evolutionPaneWidths,
    draggingPaneId: evolutionDraggingPaneId,
    startResize: startEvolutionPaneResize,
    onResizeKeyDown: onEvolutionPaneResizeKeyDown,
  } = usePersistedPaneResize({
    layoutId: EVOLUTION_LAYOUT_ID,
    panes: EVOLUTION_WIDTH_PANES,
    preserveMainMinWidth: 360,
  });
  const runsQueueWidth = evolutionPaneWidths["runs-queue"] ?? EVOLUTION_RUNS_QUEUE_PANE.defaultWidth;
  const libraryListWidth = evolutionPaneWidths["library-list"] ?? EVOLUTION_LIBRARY_LIST_PANE.defaultWidth;
  const liveLaunchWidth = evolutionPaneWidths["live-launch"] ?? EVOLUTION_LIVE_LAUNCH_PANE.defaultWidth;
  const liveRunWidth = evolutionPaneWidths["live-run"] ?? EVOLUTION_LIVE_RUN_PANE.defaultWidth;
  // Synchronous one-time migrate so the first height resolve sees shared storage.
  migrateLegacyNumericHeight(
    EVOLUTION_LAYOUT_ID,
    EVOLUTION_LIVE_IO_HEIGHT_PANE.id,
    EVOLUTION_LIVE_IO_HEIGHT_KEY,
  );
  const {
    heights: evolutionPaneHeights,
    draggingPaneId: evolutionHeightDraggingPaneId,
    startResize: startEvolutionHeightResize,
    onResizeKeyDown: onEvolutionHeightResizeKeyDown,
  } = usePersistedPaneHeight({
    layoutId: EVOLUTION_LAYOUT_ID,
    panes: EVOLUTION_HEIGHT_PANES,
  });
  const liveIoHeight = evolutionPaneHeights["live-io"] ?? EVOLUTION_LIVE_IO_HEIGHT_PANE.defaultHeight;
  const [runsQueueCollapsed, setRunsQueueCollapsed] = useState(false);
  const [libraryListCollapsed, setLibraryListCollapsed] = useState(false);
  const [liveLaunchCollapsed, setLiveLaunchCollapsed] = useState(false);
  const [liveRunCollapsed, setLiveRunCollapsed] = useState(false);
  const [expandedCaseTraceItems, setExpandedCaseTraceItems] = useState<Record<string, boolean>>({});
  const configQuery = useQuery({
    queryKey: queryKeys.configPublic(),
    queryFn: () => fetchJson<ConfigSummary>("/api/config/public"),
    staleTime: 30_000,
    refetchInterval: resolvePollingInterval(pageVisible, 30_000),
    refetchIntervalInBackground: false,
  });
  const modelLabelsById = useMemo(
    () => new Map(Object.entries(configQuery.data?.modelLabels ?? {})),
    [configQuery.data?.modelLabels],
  );
  const resolveModelLabel = useCallback(
    (modelId: string) => modelLabelsById.get(modelId),
    [modelLabelsById],
  );
  const selfTrackEnabled = forcedTrack === "self" || (configQuery.data?.modeAvailability.self_evolution ?? false);
  const supervisedTrackEnabled = forcedTrack === "supervised" || (configQuery.data?.modeAvailability.supervised_evolution ?? true);
  const activeTrack = forcedTrack ?? (
    evolutionTrack === "self" && selfTrackEnabled
      ? "self"
      : supervisedTrackEnabled
        ? "supervised"
        : selfTrackEnabled
          ? "self"
          : "supervised"
  );
  const selfTrackQueriesEnabled = activeTrack === "self";
  const supervisedTrackQueriesEnabled = activeTrack === "supervised";

  const workspaceSnapshotQuery = useQuery({
    queryKey: [...queryKeys.evolutionWorkspaceSnapshot(), selfTrackQueriesEnabled ? "include-self" : "default"] as const,
    queryFn: () => fetchJson<EvolutionWorkspaceSnapshot>(
      selfTrackQueriesEnabled
        ? "/api/evolution/workspace-snapshot?includeSelf=true"
        : "/api/evolution/workspace-snapshot",
    ),
    // R3: idle workspace — slower poll; fast only when an active run is present (see below after data).
    refetchInterval: (query) => {
      const snapshot = query.state.data as EvolutionWorkspaceSnapshot | undefined;
      const hasActiveRun = Boolean(snapshot?.activeRun?.runId);
      return resolvePollingInterval(pageVisible, hasActiveRun ? 4_000 : 12_000);
    },
    refetchIntervalInBackground: false,
    enabled: supervisedTrackQueriesEnabled || selfTrackQueriesEnabled,
  });
  const workbenchCatalogQuery = useQuery({
    queryKey: queryKeys.evolutionWorkbench(),
    queryFn: () => fetchJson<EvolutionWorkbench>("/api/evolution/workbench"),
    refetchInterval: resolvePollingInterval(pageVisible, 15_000),
    refetchIntervalInBackground: false,
    enabled: supervisedTrackQueriesEnabled,
  });
  const selfOverviewQuery = useQuery({
    queryKey: queryKeys.evolutionSelfOverview(),
    queryFn: () => fetchJson<SelfEvolutionOverview>("/api/evolution/self/overview"),
    staleTime: SELF_OVERVIEW_STALE_TIME_MS,
    refetchInterval: resolvePollingInterval(pageVisible, SELF_OVERVIEW_REFETCH_INTERVAL_MS),
    refetchIntervalInBackground: false,
    enabled: selfTrackQueriesEnabled,
  });
  const selfTransactionsQuery = useQuery({
    queryKey: queryKeys.evolutionSelfTransactions(),
    queryFn: () => fetchJson<SelfEvolutionTransaction[]>("/api/evolution/self/transactions"),
    refetchInterval: resolvePollingInterval(pageVisible, 12_000),
    refetchIntervalInBackground: false,
    enabled: selfTrackQueriesEnabled,
  });
  const selectedSelfObservationRunQuery = useQuery({
    queryKey: queryKeys.evolutionSelfObservationRun(selectedSelfObservationRunId || "__none__"),
    queryFn: () =>
      fetchJson<SelfObservationRun>(`/api/evolution/self/observation-runs/${encodeURIComponent(selectedSelfObservationRunId)}`),
    // R3: 2s only while the selected observation run is still active/in-flight.
    refetchInterval: (query) => {
      const run = query.state.data as SelfObservationRun | undefined;
      const status = String(run?.status || "").toLowerCase();
      const active = Boolean(status) && !["completed", "failed", "cancelled", "archived", "done", "success"].includes(status);
      return resolvePollingInterval(pageVisible, active ? 2_000 : 10_000);
    },
    refetchIntervalInBackground: false,
    enabled: Boolean(selfTrackQueriesEnabled && selectedSelfObservationRunId),
  });
  const {
    startWorktreeRunMutation,
    startSelfWorktreeRunMutation,
    startSelfObservationMutation,
    selfObservationActionMutation,
    deleteSelfHistoryMutation,
    actionMutation,
    approvalWorktreeActionMutation,
  } = useEvolutionRunMutations({
    lang,
    t,
    statusLabel,
    locationPathname: location.pathname,
    locationSearch: location.search,
    getStartPayload: () => ({
      sourceKind,
      datasetName,
      datasetLimit: supervisedDatasetLimitFromInput(
        sourceKind,
        datasetLimitInputRef.current?.value ?? datasetLimitInput,
      ),
      bundleName: bundleNameInput,
      keepWorktree,
      mentalModelMode: supervisedMentalModelMode,
      currentIntakeMode,
      placeholderAgentBindings:
        activeRunSnapshot?.agentBindings
        ?? workspaceSnapshotQuery.data?.currentAgentBindings
        ?? EMPTY_AGENT_BINDINGS,
    }),
    getSelfStartPayload: () => ({
      goal: selfGoalInput.trim(),
      bundleName:
        bundleNameInput.trim()
        || workbenchCatalogQuery.data?.defaultBundleName
        || workbenchCatalogQuery.data?.bundles?.[0]?.name
        || workspaceSnapshotQuery.data?.workbench?.defaultBundleName
        || workspaceSnapshotQuery.data?.workbench?.bundles?.[0]?.name
        || "",
    }),
    setActionFeedback,
    setSelfActionFeedback,
    setLiveActiveRun,
    setSelectedSelfObservationRunId,
    buildSupervisedStartPlaceholder,
    isLocalSupervisedStartPlaceholder,
    isSelfEvolutionWorktreeRun,
    afterWorktreeRunChanged: () => evolutionWorkspaceCache.afterWorktreeRunChanged(),
    afterSelfEvolutionChanged: () => evolutionWorkspaceCache.afterSelfEvolutionChanged(),
    afterSupervisedWorkspaceChanged: () => evolutionWorkspaceCache.afterSupervisedWorkspaceChanged(),
  });

  const invalidateSelfEvolution = async () => {
    await evolutionWorkspaceCache.afterSelfEvolutionChanged();
  };

  const workspaceSnapshot = workspaceSnapshotQuery.data;
  const activeSelfObservationRunId = workspaceSnapshot?.selfObservationActiveRun?.runId ?? "";
  useEffect(() => {
    if (activeSelfObservationRunId) {
      setSelectedSelfObservationRunId(activeSelfObservationRunId);
    }
  }, [activeSelfObservationRunId]);
  const runs = workspaceSnapshot?.runs ?? EMPTY_RUNS;
  const libraryItems = workspaceSnapshot?.library?.items ?? EMPTY_LIBRARY_ENTRIES;
  const pendingItems = workspaceSnapshot?.library?.pending ?? EMPTY_LIBRARY_ENTRIES;
  const overview = workspaceSnapshot?.overview;
  const workbenchControl = workbenchCatalogQuery.data;
  const workbenchState = overview?.workbench ?? workbenchControl?.savedState ?? workspaceSnapshot?.workbench?.savedState;
  const workbenchStorage = workbenchControl?.storage ?? workbenchState?.storage ?? workspaceSnapshot?.workbench?.storage;
  const supervisedEvidenceRootLabel = workbenchStorage?.relativeEvidenceRoot || "workspace/supervised_evolution";
  const supervisedEvidenceRootTitle = workbenchStorage?.activeEvidenceRoot || workbenchStorage?.formalEvidenceRoot || supervisedEvidenceRootLabel;
  const activeRunSnapshot = selectRunSnapshotWithRunId(workspaceSnapshot?.activeRun);
  const latestSupervisedRunSnapshot = selectRunSnapshotWithRunId(workspaceSnapshot?.latestRun);
  const currentSupervisedAgentBindings = workspaceSnapshot?.currentAgentBindings ?? EMPTY_AGENT_BINDINGS;
  const activeWorktreeRun = workspaceSnapshot?.worktreeActiveRun ?? null;
  const supervisedWorktreeLiveRun = activeWorktreeRun && !isSelfEvolutionWorktreeRun(activeWorktreeRun)
    ? activeWorktreeRun
    : null;
  const worktreeRuns = workspaceSnapshot?.worktreeRuns ?? EMPTY_WORKTREE_RUNS;
  const supervisedWorktreeLiveRunId = supervisedWorktreeLiveRun?.runId ?? "";
  useEffect(() => {
    if (supervisedWorktreeLiveRunId) {
      setRecentSupervisedWorktreeRunId(supervisedWorktreeLiveRunId);
    }
  }, [supervisedWorktreeLiveRunId]);
  const recentSupervisedWorktreeRun = selectRecentSupervisedWorktreeRun(
    worktreeRuns,
    recentSupervisedWorktreeRunId,
  );
  const selfWorktreeRuns = workspaceSnapshot?.selfWorktreeRuns ?? worktreeRuns.filter((run) => isSelfEvolutionWorktreeRun(run));
  const selfWorktreeRun =
    workspaceSnapshot?.selfWorktreeActiveRun
    ?? (isSelfEvolutionWorktreeRun(activeWorktreeRun) ? activeWorktreeRun : null)
    ?? null;
  const reviewCandidateWorktree = activeWorktreeRun ?? worktreeRuns[0] ?? null;
  const reviewCandidateGate = reviewCandidateWorktree?.reviewGate ?? reviewCandidateWorktree?.mergeAnalysis?.reviewGate;
  const highlightedReviewPending = isSelfEvolutionWorktreeRun(reviewCandidateWorktree)
    && Boolean(reviewCandidateGate?.required)
    && String(reviewCandidateGate?.status || "").trim().toLowerCase() !== "approved";
  const selfOverview = selfOverviewQuery.data ?? workspaceSnapshot?.selfOverview;
  const selfTransactions = selfTransactionsQuery.data ?? workspaceSnapshot?.selfTransactions ?? [];
  const selfObservationRun = workspaceSnapshot?.selfObservationActiveRun
    ?? selectedSelfObservationRunQuery.data
    ?? null;
  const selfTrackLoading = selfTrackQueriesEnabled
    && !selfOverview
    && (selfOverviewQuery.isLoading || workspaceSnapshotQuery.isLoading);
  const latestRun = runs[0] ?? null;
  const supervisedClosedLoopRecord: SupervisedClosedLoopRecord | null =
    workspaceSnapshot?.latestClosedLoopRecord
    ?? latestSupervisedRunSnapshot?.closedLoopRecord
    ?? null;
  const showTrackToggle = !forcedTrack && selfTrackEnabled && supervisedTrackEnabled;
  const routeEyebrow = activeTrack === "self" ? t("navSelfEvolution") : t("navSupervisedEvolution");
  const routeTitle =
    activeTrack === "self" ? t("selfEvolutionMode") : t("supervisedEvolutionMode");
  const routeSubtitle =
    activeTrack === "self" ? t("selfEvolutionSubtitle") : t("supervisedEvolutionSubtitle");
  const hideSupervisedToolbarIntro = activeTrack === "supervised";
  const showRouteToolbar = activeTrack !== "self";
  const currentIntakeMode =
    overview?.intakeMode === "auto"
      ? "auto"
      : configQuery.data?.intakeMode === "auto"
        ? "auto"
        : "manual_review";
  const overviewCurrentStatus = overview?.currentStatus ?? null;
  const overviewRecentRuns = overview?.recentRuns ?? [];
  const overviewLatestRunId = overviewCurrentStatus?.latestRunId || overviewRecentRuns[0]?.id || latestRun?.id || "";
  const effectiveActiveRunSnapshot = shouldIgnoreActiveRunSnapshot(activeRunSnapshot, liveActiveRun)
    ? null
    : activeRunSnapshot;
  const visibleLiveRunSnapshot = liveActiveRun && (
    isLiveSupervisedRunStatus(liveActiveRun.status)
    || ["done", "failed", "cancelled"].includes(String(liveActiveRun.status || "").toLowerCase())
  )
    ? liveActiveRun
    : null;
  const monitoredRun = effectiveActiveRunSnapshot
    ?? visibleLiveRunSnapshot;
  const supervisedWorkflowRun = supervisedWorktreeLiveRun ?? monitoredRun ?? recentSupervisedWorktreeRun;
  const supervisedMembersRun = monitoredRun;
  const supervisedMembersUseRunBindings = hasSupervisedAgentBindings(supervisedWorkflowRun?.agentBindings);
  const supervisedMembersBindings = supervisedMembersUseRunBindings
    ? supervisedWorkflowRun?.agentBindings ?? EMPTY_AGENT_BINDINGS
    : currentSupervisedAgentBindings;
  const supervisedMembersSource = supervisedMembersUseRunBindings ? "run" : "current_config";
  const runningRun = effectiveActiveRunSnapshot ?? (liveActiveRun && isLiveSupervisedRunStatus(liveActiveRun.status)
    ? liveActiveRun
    : null);
  const runLocked = Boolean(runningRun && isLiveSupervisedRunStatus(runningRun.status));
  const worktreeRunLocked = Boolean(
    activeWorktreeRun
    && ["queued", "running", "paused", "stopping"].includes(String(activeWorktreeRun.status || "").toLowerCase()),
  );
  const supervisedStartSubmitting = startWorktreeRunMutation.isPending || isLocalSupervisedStartPlaceholder(liveActiveRun);
  const supervisedPrimaryRunning = runLocked || worktreeRunLocked;
  const supervisedStartButtonLabel = supervisedStartSubmitting
    ? (lang === "zh" ? "提交中" : "Submitting")
    : supervisedPrimaryRunning
      ? (lang === "zh" ? "监督运行中" : "Supervised running")
      : t("startSupervisedRun");
  const monitoredCaseTranscript = monitoredRun?.currentCaseIo?.transcript ?? [];
  const monitoredCaseConversationMessages = monitoredRun?.currentCaseIo?.conversationMessages ?? [];
  const monitoredCaseTraceItems = useMemo(
    () =>
      buildSupervisedCaseTraceItems(monitoredCaseTranscript, {
        input: lang === "zh" ? "当前 case 输入" : "Case input",
        thought: lang === "zh" ? "思考过程" : "Reasoning trace",
        tool: lang === "zh" ? "工具调用" : "Tool call",
        assistant: lang === "zh" ? "回答" : "Answer",
        error: lang === "zh" ? "错误 / 恢复" : "Error / recovery",
        raw: lang === "zh" ? "内容" : "Content",
        state: lang === "zh" ? "状态" : "State",
      }),
    [lang, monitoredCaseTranscript],
  );
  const caseTraceTimelineRef = useRef<HTMLDivElement | null>(null);
  const latestCaseTraceKey = monitoredCaseTraceItems.at(-1)?.key ?? "";
  useEffect(() => {
    const timeline = caseTraceTimelineRef.current;
    if (!timeline || monitoredCaseTraceItems.length === 0) {
      return;
    }
    timeline.scrollTop = timeline.scrollHeight;
  }, [latestCaseTraceKey, monitoredCaseTraceItems.length]);
  const monitoredPreflightIssue = supervisedPreflightIssue(monitoredRun, lang);
  const worktreeRunStopping = String(supervisedWorktreeLiveRun?.status || "").trim().toLowerCase() === "stopping";
  const monitoredRunIdentity = monitoredRun?.sessionId || monitoredRun?.runId || "";
  const monitoredCaseLabel = monitoredRun?.currentCaseId
    ? `${monitoredRun.currentCaseIndex ?? "--"}/${monitoredRun.caseTotal ?? "--"} ${monitoredRun.currentCaseId}`
    : "--";
  const monitoredTaskLabel = monitoredRun?.currentTask || monitoredRun?.latestMessage || "--";
  const monitoredStatusLabel = monitoredRun?.decision === "INCONCLUSIVE"
    ? displayDecisionLabel(monitoredRun.decision)
    : statusLabel(monitoredRun?.status || "");
  const supervisedMemberReturnTo = `${location.pathname}${location.search}` || "/supervised-evolution";
  const supervisedMemberReturnLabel = lang === "zh" ? "返回监督进化" : "Back to supervised evolution";
  const supervisedMembersRunIdentity = supervisedWorkflowRun?.runId || monitoredRun?.sessionId || "";
  useEffect(() => {
    setSelectedSupervisedWorkflowStepId(null);
    setSelectedSupervisedAgentRole(null);
  }, [supervisedMembersRunIdentity]);
  const backendWorkflowSteps = supervisedWorkflowRun?.workflowSteps ?? [];
  const backendWorkflowCurrent = backendWorkflowSteps.find((step) => step.current);
  const supervisedRunMembers = useMemo<SupervisedRunMember[]>(() => {
    const bindings = supervisedMembersBindings;
    const roleSessions = supervisedMembersRun?.roleConversationSessions ?? {};
    const currentRole = String(supervisedMembersRun?.currentRole || backendWorkflowCurrent?.role || "").trim().toLowerCase();
    const currentAgentId = String(supervisedMembersRun?.currentAgentBinding?.agentId || "").trim();
    return SUPERVISED_RUN_MEMBER_ROLES.map((role) => {
      const binding = bindings[role] ?? {};
      const conversationSession = roleSessions[role]
        ?? supervisedRoleConversationSession(backendWorkflowSteps, role);
      const conversationSessionId = String(conversationSession?.conversationSessionId || "").trim();
      const agentId = String(binding.agentId || "").trim();
      const roleText = String(binding.roleLabel || "").trim() || runRoleLabel(role);
      const displayName = String(binding.displayName || binding.agentCode || agentId || "").trim();
      const modelId = supervisedMemberModelId(binding);
      const isActive =
        currentRole === role
        || (Boolean(currentAgentId) && Boolean(agentId) && currentAgentId === agentId);
      return {
        role,
        label: roleText,
        name: displayName || (lang === "zh" ? "未配置" : "Not configured"),
        model: supervisedMemberModelLabel(binding, resolveModelLabel),
        modelId,
        agentId,
        status: isActive ? "active" : agentId ? "configured" : "missing",
        conversationSession,
        chatRoute: supervisedMemberChatRoute(conversationSessionId, supervisedMemberReturnTo, supervisedMemberReturnLabel),
        configRoute: agentId ? supervisedMemberAgentManagementRoute(agentId, supervisedMemberReturnTo) : "",
      };
    });
  }, [
    lang,
    resolveModelLabel,
    supervisedMemberReturnLabel,
    supervisedMemberReturnTo,
    supervisedMembersBindings,
    backendWorkflowCurrent?.role,
    supervisedWorkflowRun?.workflowSteps,
    supervisedMembersRun?.currentAgentBinding?.agentId,
    supervisedMembersRun?.currentRole,
    supervisedMembersRun?.roleConversationSessions,
  ]);
  const supervisedRunMemberByRole = useMemo(
    () => new Map(supervisedRunMembers.map((member) => [member.role, member])),
    [supervisedRunMembers],
  );
  const supervisedRuntimeWorkflowStepId = (
    SUPERVISED_WORKFLOW_STEPS.some((step) => step.id === backendWorkflowCurrent?.id)
      ? backendWorkflowCurrent?.id
      : activeSupervisedWorkflowStep(supervisedMembersRun)
  ) as SupervisedWorkflowStepId | null;
  const supervisedWorkflowCards = SUPERVISED_WORKFLOW_STEPS.map((definition): SupervisedWorkflowCard => {
    const backendStep = backendWorkflowSteps.find((step) => step.id === definition.id);
    const member = definition.role ? supervisedRunMemberByRole.get(definition.role) : undefined;
    const candidateMember = supervisedRunMemberByRole.get("candidate");
    const fallbackSessionId =
      definition.id === "improve" || definition.id === "rerun_score"
        ? candidateMember?.conversationSession?.conversationSessionId || ""
        : member?.conversationSession?.conversationSessionId || "";
    const conversationSessionId = String(backendStep?.conversationSessionId || fallbackSessionId || "").trim();
    const chatRoute = backendStep?.chatRoute || supervisedMemberChatRoute(conversationSessionId, supervisedMemberReturnTo, supervisedMemberReturnLabel);
    const fallbackStatus = definition.id === supervisedRuntimeWorkflowStepId ? "running" : "pending";
    return {
      id: definition.id,
      label: backendStep?.label || supervisedWorkflowStepLabel(definition, lang),
      ownerKind: backendStep?.ownerKind || (definition.role ? "agent" : "human"),
      role: backendStep?.role ?? definition.role,
      status: backendStep?.status || fallbackStatus,
      current: backendStep?.current ?? definition.id === supervisedRuntimeWorkflowStepId,
      summary: backendStep?.summary || (
        definition.id === "approval"
          ? (lang === "zh" ? "最终运行结果、改进提案和样本评审会集中在这里。" : "Final result, proposal, and sample review are gathered here.")
          : member?.conversationSession?.latestMessage || member?.model || ""
      ),
      livePreview: backendStep?.livePreview || member?.conversationSession?.latestMessage || monitoredRun?.latestMessage || "",
      metrics: backendStep?.metrics || {},
      conversationSessionId,
      conversationTurnId: backendStep?.conversationTurnId || member?.conversationSession?.conversationTurnId || "",
      chatRoute,
      conversationMessages: backendStep?.conversationMessages ?? [],
      member,
    };
  });
  const supervisedSelectedWorkflowStepId = selectedSupervisedWorkflowStepId ?? supervisedRuntimeWorkflowStepId;
  const supervisedSelectedWorkflowStep =
    supervisedWorkflowCards.find((step) => step.id === supervisedSelectedWorkflowStepId) ?? supervisedWorkflowCards[0];
  const supervisedWorkflowManualSelection = Boolean(
    selectedSupervisedWorkflowStepId && selectedSupervisedWorkflowStepId !== supervisedRuntimeWorkflowStepId,
  );
  const normalizedSupervisedRuntimeRole = String(
    supervisedMembersRun?.currentRole
    || backendWorkflowCurrent?.role
    || monitoredRun?.currentRole
    || "",
  ).trim().toLowerCase() as SupervisedMemberRole;
  const supervisedRunIsLive = Boolean(
    supervisedWorkflowRun && isLiveSupervisedRunStatus(supervisedWorkflowRun.status),
  );
  const supervisedActiveAgentRole = supervisedRunIsLive
    ? SUPERVISED_RUN_MEMBER_ROLES.includes(normalizedSupervisedRuntimeRole)
      ? normalizedSupervisedRuntimeRole
      : supervisedRunMembers.find((member) => member.status === "active")?.role ?? null
    : null;
  const supervisedSelectedAgentRole = selectedSupervisedAgentRole
    && supervisedRunMemberByRole.has(selectedSupervisedAgentRole)
    ? selectedSupervisedAgentRole
    : supervisedActiveAgentRole
      ?? supervisedRunMembers.find((member) => member.agentId)?.role
      ?? supervisedRunMembers[0]?.role
      ?? "baseline";
  const supervisedSelectedAgentMember =
    supervisedRunMemberByRole.get(supervisedSelectedAgentRole)
    ?? supervisedRunMembers[0];
  const supervisedSelectedAgentWorkflowSteps = supervisedWorkflowCards.filter(
    (step) => step.role === supervisedSelectedAgentRole,
  );
  const supervisedSelectedAgentWorkflowStep =
    supervisedSelectedAgentWorkflowSteps.find((step) => step.current)
    ?? [...supervisedSelectedAgentWorkflowSteps].reverse().find((step) => step.conversationMessages?.length)
    ?? supervisedSelectedAgentWorkflowSteps[0];
  const supervisedSelectedAgentFallbackMessages =
    supervisedSelectedAgentRole === normalizedSupervisedRuntimeRole && monitoredCaseConversationMessages.length > 0
      ? monitoredCaseConversationMessages
      : supervisedSelectedAgentWorkflowStep?.conversationMessages ?? [];
  const supervisedSelectedAgentTaskSummary =
    supervisedSelectedAgentMember?.conversationSession?.latestMessage
    || supervisedSelectedAgentWorkflowStep?.summary
    || supervisedSelectedAgentWorkflowStep?.livePreview
    || monitoredRun?.currentTask
    || "";
  const supervisedApprovalSelected = selectedSupervisedWorkflowStepId === "approval";
  const selectedWorkflowIsRuntimeStep = supervisedSelectedWorkflowStep.id === supervisedRuntimeWorkflowStepId;
  const selectedWorkflowTaskSummary =
    supervisedSelectedWorkflowStep.summary
    || supervisedSelectedWorkflowStep.livePreview
    || monitoredRun?.currentCasePrompt
    || monitoredRun?.currentTask
    || "";
  const supervisedLiveConversationSupplement = supervisedSelectedWorkflowStep.id === "approval" ? null : (
    <div className={styles.supervisedConversationEvidence}>
      {selectedWorkflowIsRuntimeStep && monitoredRun?.currentCasePrompt ? (
        <details className={`${styles.rawBlock} ${styles.collapsibleEvidence}`}>
          <summary>{t("currentCasePrompt")}</summary>
          <pre className={styles.ioContent}>{monitoredRun.currentCasePrompt}</pre>
        </details>
      ) : null}
      {selectedWorkflowIsRuntimeStep && monitoredPreflightIssue ? (
        <div className={styles.casePreflightIssue}>
          <strong>{monitoredPreflightIssue.title}</strong>
          <span>{monitoredPreflightIssue.detail}</span>
          {monitoredPreflightIssue.reason ? <small>{monitoredPreflightIssue.reason}</small> : null}
        </div>
      ) : null}
      {selectedWorkflowIsRuntimeStep && monitoredCaseTraceItems.length > 0 ? (
        <div className={styles.supervisedConversationTrace}>
          <div ref={caseTraceTimelineRef} className={styles.caseTraceTimeline}>
            <div className={styles.caseTraceStack}>
              {monitoredCaseTraceItems.map((entry) => {
                const expanded = caseTraceItemExpanded(entry);
                return (
                  <article
                    key={entry.key}
                    className={`${styles.caseTraceTurn} ${CASE_TRACE_TURN_CLASS[entry.tone]}`}
                  >
                    <VButton
                      type="button"
                      contentLayout="plain"
                      className={styles.caseTraceSummary}
                      aria-expanded={expanded}
                      onClick={() => toggleCaseTraceItem(entry)}
                    >
                      <span className={styles.caseTraceIcon}>{caseTraceIcon(entry)}</span>
                      <span className={styles.caseTraceMessage}>
                        <span className={styles.caseTraceTitle}>{entry.title}</span>
                        <span className={styles.caseTracePreview}>{entry.preview}</span>
                      </span>
                      <span className={styles.caseTraceMeta}>
                        {entry.status ? (
                          <span className={styles.caseTraceStatus}>{statusLabel(entry.status)}</span>
                        ) : null}
                        {entry.timestamp ? (
                          <span className={styles.caseTraceTime}>{compactTimestamp(entry.timestamp)}</span>
                        ) : null}
                      </span>
                      <span className={styles.caseTraceChevron}>
                        {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                      </span>
                    </VButton>
                    {expanded ? (
                      <div className={styles.caseTraceBody}>
                        {entry.sections.map((section, sectionIndex) => renderCaseTraceSection(section, sectionIndex))}
                      </div>
                    ) : null}
                  </article>
                );
              })}
            </div>
          </div>
        </div>
      ) : null}
      {selectedWorkflowIsRuntimeStep && monitoredRun?.currentCaseIo?.latestOutput ? (
        <details className={`${styles.rawBlock} ${styles.collapsibleEvidence} ${styles.caseRawEvidence}`}>
          <summary>{currentCaseOutputLabel(monitoredRun)}</summary>
          <pre className={styles.ioContent}>{monitoredRun.currentCaseIo.latestOutput}</pre>
        </details>
      ) : null}
    </div>
  );
  const supervisedClosedLoopDecisionLabel = supervisedClosedLoopRecord?.decision
    ? displayDecisionLabel(supervisedClosedLoopRecord.decision)
    : statusLabel(supervisedClosedLoopRecord?.status || "");
  const supervisedClosedLoopProposalCount = supervisedClosedLoopRecord ? supervisedClosedLoopRecord.evidence.proposalPaths.length : 0;
  const supervisedClosedLoopLineageLabel = supervisedClosedLoopRecord?.evidence.lineageIndexPath
    ? (lang === "zh" ? "已记录" : "Recorded")
    : "--";
  const supervisedMembersRunStatusLabel = supervisedMembersRun?.decision === "INCONCLUSIVE"
    ? displayDecisionLabel(supervisedMembersRun.decision)
    : statusLabel(supervisedMembersRun?.status || "");
  const supervisedMembersIdleStatusLabel = workspaceSnapshot?.currentAgentBindingStatus === "error"
    ? lang === "zh" ? "配置异常" : "Config issue"
    : workspaceSnapshot?.currentAgentBindingStatus === "partial"
      ? lang === "zh" ? "待完善" : "Partial"
      : lang === "zh" ? "当前配置" : "Current config";
  const monitoredControlSummary = monitoredRun
    ? buildSupervisedRunControlSummary(monitoredRun, lang, {
      statusLabel,
      roleLabel: runRoleLabel,
    })
    : null;
  const supervisedWorkflowTabSummary = (step: SupervisedWorkflowCard | undefined) => {
    if (!supervisedWorkflowRun) {
      return {
        status: statusLabel("idle"),
        detail: lang === "zh" ? "等待启动" : "Waiting to start",
        count: 0,
      };
    }
    if (!step) {
      return {
        status: statusLabel("idle"),
        detail: lang === "zh" ? "等待启动" : "Waiting to start",
        count: 0,
      };
    }
    const scoreDelta = typeof step.metrics?.scoreDelta === "number" ? step.metrics.scoreDelta : null;
    const score = typeof step.metrics?.score === "number" ? step.metrics.score : null;
    const changedFiles = typeof step.metrics?.changedFiles === "number"
      ? step.metrics.changedFiles
      : typeof step.metrics?.changedFileCount === "number"
        ? step.metrics.changedFileCount
        : null;
    const total = typeof step.metrics?.total === "number" ? step.metrics.total : null;
    const approvalActions = step.id === "approval"
      ? Number(Boolean(reviewCandidateWorktree?.actionStates?.approveReview?.enabled))
        + Number(Boolean(reviewCandidateWorktree?.actionStates?.merge?.enabled))
      : null;
    return {
      status: statusLabel(step.status),
      detail: step.livePreview || step.summary || (lang === "zh" ? "等待实时输出" : "Waiting for live output"),
      count: scoreDelta !== null
        ? `Δ ${scoreDelta}`
        : score !== null
          ? score
          : changedFiles !== null
            ? changedFiles
            : total !== null
              ? total
              : approvalActions !== null
                ? approvalActions
                : step.current
                  ? 1
                  : 0,
    };
  };
  const supervisedTabSummaries = {
    baseline_eval: supervisedWorkflowTabSummary(supervisedWorkflowCards[0]),
    improve: supervisedWorkflowTabSummary(supervisedWorkflowCards[1]),
    rerun_score: supervisedWorkflowTabSummary(supervisedWorkflowCards[2]),
    approval: supervisedWorkflowTabSummary(supervisedWorkflowCards[3]),
  };
  const handleSupervisedWorkflowStepSelect = useCallback((stepId: SupervisedWorkspaceWorkflowStep) => {
    setSelectedSupervisedWorkflowStepId(stepId);
    const definition = SUPERVISED_WORKFLOW_STEPS.find((step) => step.id === stepId);
    if (definition?.role) {
      setSelectedSupervisedAgentRole(definition.role);
    }
    if (evolutionView !== "live") {
      goToSupervisedView("live");
    }
  }, [evolutionView]);
  const handleSupervisedAgentSelect = useCallback((role: SupervisedMemberRole) => {
    setSelectedSupervisedAgentRole(role);
    if (role === "baseline") {
      setSelectedSupervisedWorkflowStepId("baseline_eval");
    } else if (role === "candidate") {
      setSelectedSupervisedWorkflowStepId(
        supervisedRuntimeWorkflowStepId === "rerun_score" ? "rerun_score" : "improve",
      );
    } else {
      setSelectedSupervisedWorkflowStepId(null);
    }
    if (evolutionView !== "live") {
      goToSupervisedView("live");
    }
  }, [evolutionView, supervisedRuntimeWorkflowStepId]);
  const handleFollowSupervisedAgent = useCallback(() => {
    setSelectedSupervisedAgentRole(null);
    setSelectedSupervisedWorkflowStepId(null);
  }, []);
  const terminateWorktreeAction = supervisedWorktreeLiveRun?.actionStates?.terminate;
  const terminateSupervisedAction = terminateWorktreeAction;
  const canTerminateSupervisedRun = Boolean(supervisedWorktreeLiveRun && terminateWorktreeAction?.enabled);
  const terminateSupervisedPending = approvalWorktreeActionMutation.isPending;
  const handleTerminateSupervisedRun = () => {
    if (supervisedWorktreeLiveRun) {
      approvalWorktreeActionMutation.mutate({ runId: supervisedWorktreeLiveRun.runId, action: "terminate" });
    }
  };
  const supervisedControlError =
    approvalWorktreeActionMutation.error?.message
    ?? startWorktreeRunMutation.error?.message
    ?? "";
  const terminateSupervisedDisabledReason = disabledReason(terminateSupervisedAction);
  const supervisedActiveRunMonitorMetrics: EvolutionActiveRunMonitorMetric[] = monitoredRun
    ? [
      {
        id: "session",
        label: t("activeRunSession"),
        value: monitoredRunIdentity,
        title: monitoredRunIdentity,
      },
      {
        id: "phase",
        label: t("activeRunPhase"),
        value: monitoredControlSummary?.stageLabel || statusLabel(monitoredRun.currentPhase || monitoredRun.status),
      },
      {
        id: "case",
        label: t("activeRunCurrentCase"),
        value: monitoredCaseLabel,
        title: monitoredCaseLabel,
      },
      {
        id: "role",
        label: t("activeRunCurrentRole"),
        value: monitoredRun.currentRole || "--",
      },
      {
        id: "result",
        label: t("activeRunResult"),
        value: monitoredControlSummary?.resultLabel || monitoredTaskLabel,
      },
      {
        id: "updated",
        label: t("latestLiveMessage"),
        value: compactTimestamp(monitoredRun.updatedAt),
      },
    ]
    : [];
  const supervisedActiveRunMonitorEvents: EvolutionActiveRunMonitorEventItem[] = monitoredRun
    ? monitoredRun.eventTail.map((item) => ({
      key: `${item.timestamp}-${item.event}-${item.summary}`,
      title: formatRunEventTitle(item),
      statusLabel: statusLabel(item.status),
      summary: formatRunEventSummary(item),
      timestamp: compactTimestamp(item.timestamp),
    }))
    : [];
  const supervisedClosedLoopLedger: EvolutionActiveRunClosedLoopLedger | null = supervisedClosedLoopRecord
    ? {
      eyebrow: lang === "zh" ? "闭环记录库" : "Closed-loop ledger",
      title: supervisedClosedLoopRecord.runId,
      statusLabel: supervisedClosedLoopDecisionLabel || "--",
      statusTone: supervisedClosedLoopRecord.status === "failed" ? "primary" : "secondary",
      description: displaySupervisedTechnicalText(
        supervisedClosedLoopRecord.policySummary
        || supervisedClosedLoopRecord.reason
        || supervisedClosedLoopRecord.nextAction.description,
        supervisedClosedLoopRecord.decision,
        lang,
        decisionLabel,
      ) || "--",
      evidence: [
        {
          id: "review",
          label: lang === "zh" ? "审查入口" : "Review entry",
          value: supervisedClosedLoopRecord.nextAction.label || "--",
        },
        {
          id: "sessions",
          label: lang === "zh" ? "Agent 会话" : "Agent sessions",
          value: supervisedClosedLoopRecord.counts.roleSessionCount,
        },
        {
          id: "proposal-evidence",
          label: lang === "zh" ? "提案证据" : "Proposal evidence",
          value: supervisedClosedLoopProposalCount,
        },
        {
          id: "lineage",
          label: "lineage",
          value: supervisedClosedLoopLineageLabel,
        },
      ],
      action: {
        label: lang === "zh" ? "审查入口" : "Review",
        title: supervisedClosedLoopRecord.nextAction.description,
        onClick: () => {
          setLibraryView("pending");
          goToSupervisedView("library");
        },
      },
    }
    : null;
  const supervisedActiveRunMonitorRun: EvolutionActiveRunMonitorRunView | null = monitoredRun
    ? {
      termination: {
        disabled: !canTerminateSupervisedRun,
        pending: terminateSupervisedPending,
        title: terminateSupervisedDisabledReason || t("terminateSupervisedRun"),
        ariaLabel: t("terminateSupervisedRun"),
        onClick: handleTerminateSupervisedRun,
      },
      openSessionAction: monitoredRun.sessionId
        ? {
          label: t("openLatestRuns"),
          onClick: () => openRun(monitoredRun.sessionId),
        }
        : null,
      feedback: actionFeedback,
      error: supervisedControlError,
      warning: !canTerminateSupervisedRun && terminateSupervisedDisabledReason && worktreeRunStopping
        ? terminateSupervisedDisabledReason
        : null,
      controlSummary: {
        status: monitoredRun.status,
        decision: monitoredRun.decision,
        tone: monitoredControlSummary?.tone,
        headline: monitoredControlSummary?.headline || monitoredRun.latestMessage,
        reason: monitoredControlSummary?.reason,
        nextActionLabel: t("nextRecommendedAction"),
        nextAction: monitoredControlSummary?.nextAction,
      },
      metrics: supervisedActiveRunMonitorMetrics,
      timelineTitle: t("activeRunTimeline"),
      events: supervisedActiveRunMonitorEvents,
    }
    : null;
  const supervisedActiveRunMonitorIdleMetrics: EvolutionActiveRunMonitorMetric[] = [
    {
      id: "latest-run",
      label: t("latestRun"),
      value: overviewLatestRunId || "--",
    },
    {
      id: "pending-candidates",
      label: t("pendingCandidates"),
      value: pendingItems.length,
    },
    {
      id: "selected-bundle",
      label: t("selectedBundle"),
      value: workbenchState?.bundleName || "--",
    },
  ];
  const supervisedActiveRunMonitorIdleRelated: EvolutionActiveRunMonitorMetric[] = [
    {
      id: "latest-score",
      label: t("latestScore"),
      value: overviewRecentRuns[0] ? clampScore(overviewRecentRuns[0].score) : latestRun ? clampScore(latestRun.candidateScore) : "--",
    },
    {
      id: "selected-dataset",
      label: t("selectedDataset"),
      value: workbenchState?.datasetName || "--",
    },
  ];
  const selfRunLocked = Boolean(
    selfWorktreeRun
    && ["queued", "running", "paused", "stopping"].includes(String(selfWorktreeRun.status || "").trim().toLowerCase()),
  );
  const selectedDataset = workbenchControl?.datasets.find((item) => item.name === datasetName) ?? null;
  const datasetCatalog = workbenchControl?.datasetCatalog ?? workbenchControl?.datasets ?? [];
  const primaryDatasets = useMemo(
    () => (workbenchControl?.datasets ?? []).filter((item) => item.selectable !== false && item.effective),
    [workbenchControl?.datasets],
  );
  const datasetCatalogGroups = useMemo(() => {
    const runnable = datasetCatalog.filter((item) => item.selectable !== false && item.effective && item.visibility === "primary");
    const roadmap = datasetCatalog.filter(
      (item) => String(item.defaultVisibility || "").trim() === "roadmap" || item.usabilityStatus === "roadmap_only",
    );
    const blocked = datasetCatalog.filter((item) => !runnable.includes(item) && !roadmap.includes(item));
    return {
      all: datasetCatalog,
      runnable,
      blocked,
      roadmap,
    };
  }, [datasetCatalog]);
  const visibleDatasetCatalog = datasetCatalogGroups[selectedDatasetCatalogFilter] ?? datasetCatalogGroups.all;
  const hiddenDatasetCount = Math.max(0, datasetCatalog.length - primaryDatasets.length);
  const availableBundles = workbenchControl?.bundles ?? [];
  const selectedBundleExists = availableBundles.some((item) => item.name === bundleNameInput);
  const supervisedStartDisabledReason = runLocked || worktreeRunLocked
    ? t("runningLockHint")
    : !workbenchControl
      ? (lang === "zh" ? "监督运行控制暂不可用。" : "Supervised run controls are unavailable.")
      : startWorktreeRunMutation.isPending
        ? (lang === "zh" ? "监督运行正在启动。" : "The supervised run is starting.")
        : sourceKind === "dataset" && !datasetName
          ? (lang === "zh" ? "先选择数据集。" : "Choose a dataset first.")
          : sourceKind === "bundle" && !selectedBundleExists
            ? (lang === "zh" ? "先选择有效的评测包。" : "Choose a valid evaluation bundle first.")
            : undefined;
  const supervisedMembersHint = supervisedMembersSource === "current_config"
    ? (lang === "zh" ? "当前 Agent 配置；启动后锁定为本轮绑定。" : "Current Agent config; a run locks its own bindings after start.")
    : undefined;
  const workbenchCatalogLoading = supervisedTrackQueriesEnabled && !workbenchControl && workbenchCatalogQuery.isFetching;
  const workbenchCatalogUnavailable = supervisedTrackQueriesEnabled && !workbenchControl && workbenchCatalogQuery.isError;
  const sourceCatalogCountLabel = workbenchCatalogLoading
    ? (lang === "zh" ? "加载中" : "Loading")
    : String(primaryDatasets.length + availableBundles.length);
  const supervisedSourceOptions = useMemo<SupervisedSourceOption[]>(() => {
    const datasetOptions: SupervisedSourceOption[] = primaryDatasets.map((item) => ({
      value: `dataset:${item.name}`,
      kind: "dataset",
      name: item.name,
      label: item.name,
      detail: datasetBenchmarkDetail(item, lang),
      caseCount: item.caseCount,
      dataset: item,
    }));
    const bundleOptions: SupervisedSourceOption[] = availableBundles.map((item) => ({
      value: `bundle:${item.name}`,
      kind: "bundle",
      name: item.name,
      label: item.name,
      detail: `${item.benchmark || item.declaredName || "--"} · ${lang === "zh" ? "评测包，直接运行" : "bundle, run directly"}`,
      caseCount: item.caseCount,
      bundle: item,
    }));
    return [...datasetOptions, ...bundleOptions];
  }, [availableBundles, lang, primaryDatasets]);
  const selectedSourceValue = sourceKind === "bundle" ? `bundle:${bundleNameInput}` : `dataset:${datasetName}`;
  const selectedSourceOption = supervisedSourceOptions.find((item) => item.value === selectedSourceValue) ?? null;
  const selectedSourceKindLabel = selectedSourceOption?.kind === "dataset"
    ? sourceKindLabel("dataset")
    : sourceKindLabel("bundle");
  const selectedSourceCaseText = `${selectedSourceOption?.caseCount ?? "--"} cases`;
  const selectedSourceDataset = selectedSourceOption?.kind === "dataset" ? selectedSourceOption.dataset : null;
  const selectedSourceBundle = selectedSourceOption?.kind === "bundle" ? selectedSourceOption.bundle : null;
  const selectedSourceStatusText =
    selectedSourceDataset
      ? (selectedSourceDataset.usabilityReason || selectedSourceDataset.description || "--")
      : (selectedSourceBundle?.benchmark || selectedSourceBundle?.declaredName || "--");
  const selectedSourceEvaluationMode = selectedSourceDataset
    ? String(selectedSourceDataset.evaluationMode || "").trim()
    : "";
  const selectedSourceEvaluationText =
    selectedSourceEvaluationMode === "agent_judged"
      ? (lang === "zh"
        ? `${selectedSourceDataset?.scoreLabel || "纯 agent 裁决分数"}；不需要官方 Harbor/Docker 判分器`
        : `${selectedSourceDataset?.scoreLabel || "Agent-judged score"}; no official Harbor/Docker verifier required`)
      : selectedSourceEvaluationMode === "custom_harness"
        ? (lang === "zh"
          ? `${selectedSourceDataset?.scoreLabel || "Vibelution 自定义分数"}；非官方 Terminal-Bench 成绩`
          : `${selectedSourceDataset?.scoreLabel || "Vibelution custom score"}; not an official Terminal-Bench score`)
        : "";
  const selectedSourceOfficialWarning =
    selectedSourceDataset
      && (
        String(selectedSourceDataset.evaluationMode || "").trim() === "custom_harness"
        || String(selectedSourceDataset.officialVerifierStatus || "").trim() === "harbor_pending"
      )
      ? t("sourceOfficialVerifierWarning")
      : "";
  const selectedSourcePlannedCases = sourceKind === "dataset" && datasetLimitInput.trim()
    ? `${datasetLimitInput.trim()} / ${selectedSourceOption?.caseCount ?? "--"}`
    : selectedSourceCaseText;
  const configuredSupervisedAgentCount = supervisedRunMembers.filter((member) => Boolean(member.agentId)).length;
  const renderSupervisedRunPlan = () => {
    if (!supervisedWorkflowRun) {
      return (
        <div className={styles.supervisedRunPlan} role="status">
          <div className={styles.supervisedRunPlanLead}>
            <span className={styles.secondaryPill}>{lang === "zh" ? "运行前计划" : "Run plan"}</span>
            <h3>{lang === "zh" ? "准备开始监督进化" : "Ready to start supervised evolution"}</h3>
            <p>
              {lang === "zh"
                ? "开始后将依次完成基线评测、候选 worktree 改良、复跑评分和用户审批；结果不会自动写入运行时。"
                : "The run proceeds through baseline evaluation, candidate worktree improvement, rerun scoring, and user approval; results are not written to runtime automatically."}
            </p>
          </div>
          <div className={styles.supervisedRunPlanGrid}>
            <article>
              <span>{lang === "zh" ? "评测来源" : "Evaluation source"}</span>
              <strong>{selectedSourceOption?.label || "--"}</strong>
            </article>
            <article>
              <span>{lang === "zh" ? "计划样本" : "Planned cases"}</span>
              <strong>{selectedSourcePlannedCases}</strong>
            </article>
            <article>
              <span>{lang === "zh" ? "监督成员" : "Supervised members"}</span>
              <strong>{configuredSupervisedAgentCount} / {SUPERVISED_RUN_MEMBER_ROLES.length}</strong>
            </article>
            <article>
              <span>{lang === "zh" ? "生效方式" : "Runtime effect"}</span>
              <strong>{lang === "zh" ? "用户审批后决定" : "Decided after approval"}</strong>
            </article>
          </div>
          <div className={styles.supervisedRunPlanActions}>
            <VButton
              type="button"
              variant="primary"
              className={`${styles.inlineAction} ${styles.supervisedPrimaryAction}`}
              isDisabled={
                runLocked
                || worktreeRunLocked
                || !workbenchControl
                || startWorktreeRunMutation.isPending
                || (sourceKind === "dataset" && !datasetName)
                || (sourceKind === "bundle" && !selectedBundleExists)
              }
              onClick={() => startWorktreeRunMutation.mutate()}
              tooltip={t("launchSupervisedRunHint")}
              disabledReason={supervisedStartDisabledReason}
              icon={
                supervisedStartSubmitting || supervisedPrimaryRunning
                  ? <LoaderCircle size={15} />
                  : <Play size={15} />
              }
            >
              {supervisedStartButtonLabel}
            </VButton>
            <span>{lang === "zh" ? "运行参数可在左侧调整。" : "Adjust run parameters in the left rail."}</span>
          </div>
          <p className={styles.supervisedRunPlanHint}>
            {lang === "zh"
              ? "运行启动后，这里会切换为当前 Agent 的真实会话轨迹。"
              : "After launch, this area switches to the active Agent's real conversation trace."}
          </p>
        </div>
      );
    }
    return null;
  };
  const normalizedLibrarySearch = librarySearchInput.trim().toLowerCase();
  const filterLibraryEntries = (entries: EvolutionLibraryEntry[]) =>
    entries.filter((item) => {
      if (libraryStatusFilter !== "all" && item.proposalStatus !== libraryStatusFilter) {
        return false;
      }
      if (libraryDeleteFilter === "deletable" && !item.canDelete) {
        return false;
      }
      if (libraryDeleteFilter === "blocked" && item.canDelete) {
        return false;
      }
      if (!normalizedLibrarySearch) {
        return true;
      }
      const searchHaystack = [
        item.title,
        item.sourceRun,
        item.sourceSelfRunId ?? "",
        item.targetLabel,
        item.targetKey,
        item.headline,
        item.changeSummary,
        item.summary,
        item.reason ?? "",
      ]
        .join(" ")
        .toLowerCase();
      return searchHaystack.includes(normalizedLibrarySearch);
    });
  const filteredLibraryItems = useMemo(
    () => filterLibraryEntries(libraryItems),
    [libraryItems, libraryStatusFilter, libraryDeleteFilter, normalizedLibrarySearch],
  );
  const filteredPendingItems = useMemo(
    () => filterLibraryEntries(pendingItems),
    [pendingItems, libraryStatusFilter, libraryDeleteFilter, normalizedLibrarySearch],
  );
  const visibleLibraryEntries = libraryView === "items"
    ? filteredLibraryItems
    : filteredPendingItems;
  const currentLibraryEntries = libraryView === "items"
    ? libraryItems
    : pendingItems;
  const hasLibraryFilters = Boolean(normalizedLibrarySearch)
    || libraryStatusFilter !== "all"
    || libraryDeleteFilter !== "all";
  const selectedLibraryItem =
    filteredLibraryItems.find((item) => item.id === selectedLibraryItemId) ?? filteredLibraryItems[0] ?? null;
  const selectedPendingItem =
    filteredPendingItems.find((item) => item.id === selectedPendingItemId) ?? filteredPendingItems[0] ?? null;
  const selectedProposalSummary = libraryView === "items" ? selectedLibraryItem : selectedPendingItem;
  const selectedProposalIsSelfCandidate = isSelfEvolutionCandidateItem(selectedProposalSummary);
  const selectedProposalDisplaySourceRun = proposalDisplaySourceRun(selectedProposalSummary);
  const selectedProposalCanOpenSourceRun = canOpenProposalSourceRun(selectedProposalSummary);
  const selectedProposalRunId = selectedProposalSummary?.sourceRun ?? null;
  const libraryPaneEmpty = currentLibraryEntries.length === 0;
  const libraryFilteredEmpty = !libraryPaneEmpty && visibleLibraryEntries.length === 0;
  const libraryDeletableCount = currentLibraryEntries.filter((item) => item.canDelete).length;
  const libraryBlockedCount = currentLibraryEntries.length - libraryDeletableCount;
  const proposalDetailQuery = useQuery({
    queryKey: queryKeys.evolutionProposal(selectedProposalRunId ?? "__none__"),
    queryFn: () =>
      fetchJson<EvolutionProposalDetail>(`/api/evolution/proposals/${selectedProposalRunId}`),
    enabled:
      activeTrack === "supervised"
      && evolutionView === "library"
      && !selectedProposalIsSelfCandidate
      && Boolean(selectedProposalRunId),
    // R3: library detail is not a hot live run surface.
    refetchInterval: resolvePollingInterval(pageVisible, 15_000),
    refetchIntervalInBackground: false,
  });
  const {
    updateProposalMutation,
    deleteProposalMutation,
    bulkDeleteMutation,
    deleteRunRecordMutation,
    bulkDeleteRunRecordsMutation,
  } = useEvolutionProposalMutations({
    libraryView,
    selectedProposalRunId,
    selectedRunId,
    selectedLibraryItemId,
    selectedPendingItemId,
    setProposalEditFeedback,
    setProposalEditDraft,
    setProposalEditOpen,
    setLibraryFeedback,
    setRunRecordsFeedback,
    setSelectedProposalRunIds,
    setSelectedRunIds,
    setSelectedRunId,
    setSelectedLibraryItemId,
    setSelectedPendingItemId,
    proposalEditDraftFromDetail,
    afterProposalChanged: (sessionId: string) => evolutionWorkspaceCache.afterProposalChanged(sessionId),
  });

  useEffect(() => {
    if (!proposalDetailQuery.data) {
      return;
    }
    setProposalEditDraft(proposalEditDraftFromDetail(proposalDetailQuery.data));
    setProposalEditOpen(false);
    setProposalEditFeedback("");
  }, [proposalDetailQuery.data?.sessionId]);

  useEffect(() => {
    if (formInitialized || !workbenchControl) {
      return;
    }
    const savedState = workbenchControl.savedState;
    const bundleNames = new Set((workbenchControl.bundles ?? []).map((item) => item.name));
    const fallbackBundle = workbenchControl.defaultBundleName || workbenchControl.bundles[0]?.name || "";
    const savedBundle = savedState.bundleName && bundleNames.has(savedState.bundleName) ? savedState.bundleName : fallbackBundle;
    setSourceKind(savedState.source === "bundle" && savedBundle ? "bundle" : "dataset");
    const defaultDatasetName = primaryDatasets[0]?.name || workbenchControl.datasets[0]?.name || "";
    const savedDatasetKnown = workbenchControl.datasets.some((item) => item.name === savedState.datasetName);
    const savedDatasetSelectable = primaryDatasets.some((item) => item.name === savedState.datasetName);
    setDatasetName(savedDatasetKnown && savedDatasetSelectable ? savedState.datasetName : defaultDatasetName);
    setDatasetLimitInput(toLimitInput(savedState.datasetLimit));
    setBundleNameInput(savedBundle);
    setKeepWorktree(Boolean(savedState.keepWorktree));
    setFormInitialized(true);
  }, [formInitialized, primaryDatasets, workbenchControl]);

  useEffect(() => {
    if (!formInitialized || !workbenchControl || sourceKind !== "dataset") {
      return;
    }
    if (datasetName && primaryDatasets.some((item) => item.name === datasetName)) {
      return;
    }
    const fallback = primaryDatasets[0]?.name || "";
    if (fallback && datasetName !== fallback) {
      setDatasetName(fallback);
    }
  }, [datasetName, formInitialized, primaryDatasets, sourceKind, workbenchControl]);

  useEffect(() => {
    if (!formInitialized || !workbenchControl || sourceKind !== "bundle") {
      return;
    }
    const bundleNames = new Set((workbenchControl.bundles ?? []).map((item) => item.name));
    if (!bundleNameInput || !bundleNames.has(bundleNameInput)) {
      setBundleNameInput(workbenchControl.defaultBundleName || workbenchControl.bundles[0]?.name || "");
    }
  }, [bundleNameInput, formInitialized, sourceKind, workbenchControl]);

  useEffect(() => {
    const datasetParam = new URLSearchParams(location.search).get("dataset");
    if (!datasetParam || activeTrack !== "supervised") {
      return;
    }
    const known = workbenchControl?.datasets.some((item) => item.name === datasetParam);
    if (!known) {
      return;
    }
    setSourceKind("dataset");
    setDatasetName(datasetParam);
  }, [activeTrack, location.search, workbenchControl]);

  useEffect(() => {
    if (activeRunSnapshot) {
      setLiveActiveRun(activeRunSnapshot);
      return;
    }
    setLiveActiveRun((current) => {
      if (current && ["done", "failed", "cancelled"].includes(String(current.status || "").toLowerCase())) {
        return current;
      }
      return null;
    });
  }, [activeRunSnapshot]);

  useEffect(() => {
    if (!forcedTrack || evolutionTrack === forcedTrack) {
      return;
    }
    setEvolutionTrack(forcedTrack);
  }, [evolutionTrack, forcedTrack, setEvolutionTrack]);

  useEffect(() => {
    if (!forcedView && rawEvolutionView === "overview") {
      setEvolutionView("live");
    }
  }, [forcedView, rawEvolutionView, setEvolutionView]);

  useEffect(() => {
    if (selfGoalInitialized || !workspaceSnapshot?.selfOverview?.goal) {
      return;
    }
    setSelfGoalInput(workspaceSnapshot.selfOverview.goal);
    setSelfGoalInitialized(true);
  }, [selfGoalInitialized, workspaceSnapshot?.selfOverview?.goal]);

  useEffect(() => {
    if (!pageVisible) {
      return;
    }
    const streamLiveRun = isLocalSupervisedStartPlaceholder(liveActiveRun) ? null : liveActiveRun;
    const target = selectSupervisedRunStreamTarget(activeRunSnapshot, streamLiveRun);
    if (!target) {
      return;
    }

    const source = new EventSource("/api/evolution/active-run/events");
    const handleSnapshot = (message: MessageEvent) => {
      const snapshot = parseRunStreamSnapshot<EvolutionActiveRun>(message.data, "supervised stream");
      if (!snapshot) {
        return;
      }
      const payload = JSON.parse(message.data) as EvolutionActiveRunStreamEvent;
      setLiveActiveRun(snapshot);
      if (payload.terminal) {
        void evolutionWorkspaceCache.afterSupervisedRunTerminal();
        source.close();
      }
    };

    source.addEventListener("supervised_run", handleSnapshot as EventListener);
    source.onerror = () => {
      source.close();
      void evolutionWorkspaceCache.refreshSupervisedActiveRun();
    };

    return () => {
      source.removeEventListener("supervised_run", handleSnapshot as EventListener);
      source.close();
    };
  }, [
    activeRunSnapshot?.runId,
    activeRunSnapshot?.status,
    liveActiveRun?.runId,
    liveActiveRun?.status,
    pageVisible,
    evolutionWorkspaceCache,
  ]);

  useEffect(() => {
    const visibleDeletableIds = new Set(
      visibleLibraryEntries.filter((item) => item.canDelete).map((item) => item.sourceRun),
    );
    setSelectedProposalRunIds((current) => {
      const next = current.filter((item) => visibleDeletableIds.has(item));
      if (
        next.length === current.length
        && next.every((item, index) => item === current[index])
      ) {
        return current;
      }
      return next;
    });
  }, [visibleLibraryEntries]);

  const filteredRuns = useMemo(() => {
    if (runFilter === "all") {
      return runs;
    }
    return runs.filter((run) => run.status === runFilter);
  }, [runFilter, runs]);
  const hasRuns = runs.length > 0;
  const hasFilteredRuns = filteredRuns.length > 0;
  const filteredRunsEmpty = hasRuns && !hasFilteredRuns;
  const runSuccessCount = runs.filter((run) => run.status === "success").length;
  const runFailedCount = runs.filter((run) => run.status === "failed").length;
  const runPendingCount = runs.filter((run) => run.status === "waiting").length;
  const visibleDeletableRunIds = useMemo(
    () => filteredRuns.filter((run) => run.canDelete).map((run) => run.id),
    [filteredRuns],
  );
  const selectedRunIdSet = useMemo(() => new Set(selectedRunIds), [selectedRunIds]);
  const runDeletableCount = visibleDeletableRunIds.length;
  const runBlockedDeleteCount = filteredRuns.length - runDeletableCount;
  const allVisibleDeletableRunsSelected =
    visibleDeletableRunIds.length > 0
    && visibleDeletableRunIds.every((runId) => selectedRunIdSet.has(runId));
  const runHeaderMessage = !hasRuns
    ? t("noRunsRecordedHint")
    : filteredRunsEmpty
      ? t("runFilterEmptyHint")
      : t("runQueueHint");
  const libraryHeaderMessage = libraryPaneEmpty
    ? (libraryView === "items" ? t("emptyLibraryItems") : t("emptyPendingItems"))
    : libraryFilteredEmpty
      ? t("noProposalMatches")
      : t("chooseProposalDetail");
  const runsWorkspaceStyle = useMemo(
    () =>
      ({
        "--evolution-runs-queue-width": runsQueueCollapsed ? "0px" : `${runsQueueWidth}px`,
      }) as CSSProperties,
    [runsQueueCollapsed, runsQueueWidth],
  );
  const libraryWorkspaceStyle = useMemo(
    () =>
      ({
        "--evolution-library-list-width": libraryListCollapsed ? "0px" : `${libraryListWidth}px`,
      }) as CSSProperties,
    [libraryListCollapsed, libraryListWidth],
  );
  const liveWorkspaceStyle = useMemo(
    () =>
      ({
        "--evolution-live-launch-width": liveLaunchCollapsed ? "0px" : `${liveLaunchWidth}px`,
        "--evolution-live-run-width": liveRunCollapsed ? "0px" : `${liveRunWidth}px`,
        "--evolution-live-io-height": `${liveIoHeight}px`,
      }) as CSSProperties,
    [liveIoHeight, liveLaunchCollapsed, liveLaunchWidth, liveRunCollapsed, liveRunWidth],
  );
  const resizeLiveLaunchLabel = lang === "zh" ? "调整启动卡片宽度" : "Resize launch card";
  const resizeLiveRunLabel = lang === "zh" ? "调整当前任务卡片宽度" : "Resize active run card";
  const resizeLiveIoLabel = lang === "zh" ? "调整 CASE 输出高度" : "Resize case output height";
  const resizeRunsQueueLabel = lang === "zh" ? "调整运行列表宽度" : "Resize run list";
  const resizeLibraryListLabel = lang === "zh" ? "调整提案列表宽度" : "Resize proposal list";

  const selectedRun = useMemo(() => {
    return filteredRuns.find((run) => run.id === selectedRunId) ?? filteredRuns[0] ?? null;
  }, [filteredRuns, selectedRunId]);

  useEffect(() => {
    const visibleDeletableIds = new Set(visibleDeletableRunIds);
    setSelectedRunIds((current) => {
      const next = current.filter((runId) => visibleDeletableIds.has(runId));
      if (
        next.length === current.length
        && next.every((runId, index) => runId === current[index])
      ) {
        return current;
      }
      return next;
    });
  }, [visibleDeletableRunIds]);

  const relatedLibraryItems = selectedRun
    ? libraryItems.filter((item) => item.sourceRun === selectedRun.id)
    : [];
  const relatedPendingItems = selectedRun
    ? pendingItems.filter((item) => item.sourceRun === selectedRun.id)
    : [];
  const relatedProposalCount = relatedLibraryItems.length + relatedPendingItems.length;

  function goToSupervisedView(view: SupervisedRouteView) {
    if (forcedTrack === "supervised" && forcedView) {
      navigate(
        view === "live"
          ? "/supervised-evolution"
          : view === "runs"
            ? "/supervised-evolution/runs"
            : "/supervised-evolution/library",
      );
      return;
    }
    setEvolutionView(view);
  }

  function openRun(runId: string | null) {
    if (!runId) {
      return;
    }
    setSelectedRunId(runId);
    goToSupervisedView("runs");
  }

  function openProposalFromRun(item: EvolutionLibraryEntry, view: LibraryView) {
    goToSupervisedView("library");
    setLibraryView(view);
    setLibraryFeedback("");
    if (view === "items") {
      setSelectedLibraryItemId(item.id);
      setSelectedPendingItemId(null);
    } else {
      setSelectedPendingItemId(item.id);
      setSelectedLibraryItemId(null);
    }
  }

  function formatAvailableActions(actions: string[] | undefined) {
    if (!actions || actions.length === 0) {
      return "--";
    }
    return actions.map((action) => proposalActionLabel(action)).join(", ");
  }

  function disabledReason(state: EvolutionActionState | undefined) {
    if (!state || state.enabled) {
      return "";
    }
    return state.reason || "";
  }

  function runRoleLabel(role: string | undefined) {
    const normalized = String(role || "").trim().toLowerCase();
    if (normalized === "baseline") {
      return t("roleBaseline");
    }
    if (normalized === "candidate") {
      return t("roleCandidate");
    }
    if (normalized === "reviewer") {
      return lang === "zh" ? "评审" : "Reviewer";
    }
    if (normalized === "auditor") {
      return lang === "zh" ? "审计" : "Auditor";
    }
    if (normalized === "judge") {
      return lang === "zh" ? "裁决" : "Judge";
    }
    return normalized || "--";
  }

  function supervisedAgentRoleDescription(role: SupervisedMemberRole) {
    if (role === "baseline") {
      return lang === "zh" ? "执行当前策略" : "Run the current strategy";
    }
    if (role === "candidate") {
      return lang === "zh" ? "反思、改良与候选复跑" : "Reflect, improve, and rerun";
    }
    if (role === "judge") {
      return lang === "zh" ? "独立评分与裁决" : "Independent scoring and judgment";
    }
    if (role === "reviewer") {
      return lang === "zh" ? "复核改进证据" : "Review improvement evidence";
    }
    return lang === "zh" ? "核对运行证据" : "Audit run evidence";
  }

  function formatRunEventTitle(event: EvolutionActiveRun["eventTail"][number]) {
    const normalized = String(event.event || "").trim().toLowerCase();
    if (normalized === "queued") {
      return t("runEventQueued");
    }
    if (normalized === "session_start") {
      return t("runEventStarted");
    }
    if (normalized === "role_start") {
      return t("runEventCaseStarted");
    }
    if (normalized === "role_finish") {
      return t("runEventCaseFinished");
    }
    if (normalized === "pause_requested") {
      return t("runEventPauseRequested");
    }
    if (normalized === "run_paused") {
      return t("runEventPaused");
    }
    if (normalized === "run_resumed") {
      return t("runEventResumed");
    }
    if (normalized === "stop_requested") {
      return t("runEventStopRequested");
    }
    if (normalized === "run_cancelled") {
      return t("runEventCancelled");
    }
    if (normalized === "session_error") {
      return t("runEventError");
    }
    if (normalized === "session_finish") {
      return t("runEventFinished");
    }
    if (normalized === "run_completed") {
      return t("runEventCompleted");
    }
    if (normalized === "run_failed") {
      return t("runEventFailed");
    }
    return event.title || event.event;
  }

  function formatRunEventSummary(event: EvolutionActiveRun["eventTail"][number]) {
    const eventType = String(event.event || "").trim().toLowerCase();
    const casePrefix =
      event.caseIndex && event.caseTotal
        ? lang === "zh"
          ? `第 ${event.caseIndex}/${event.caseTotal} 个 case`
          : `Case ${event.caseIndex}/${event.caseTotal}`
        : "";
    const roleText = runRoleLabel(event.role);
    const reasonText = String(event.reason || "").trim();
    const elapsedText =
      typeof event.elapsedSeconds === "number" && Number.isFinite(event.elapsedSeconds)
        ? event.elapsedSeconds.toFixed(1)
        : "";

    if (eventType === "queued") {
      if (String(event.sourceKind || "").trim().toLowerCase() === "dataset") {
        const limitText =
          typeof event.datasetLimit === "number" && event.datasetLimit > 0
            ? String(event.datasetLimit)
            : lang === "zh"
              ? "全部"
              : "all";
        return lang === "zh"
          ? `已加入队列，来源数据集 ${event.datasetName || "--"}，样本上限 ${limitText}，bundle ${event.bundleName || "--"}。`
          : `Queued from dataset ${event.datasetName || "--"} with limit ${limitText} and bundle ${event.bundleName || "--"}.`;
      }
      return lang === "zh"
        ? `已加入队列，来源 bundle ${event.bundleName || "--"}。`
        : `Queued from bundle ${event.bundleName || "--"}.`;
    }

    if (eventType === "session_start") {
      return lang === "zh"
        ? `监督会话 ${event.sessionId || "--"} 已启动，bundle ${event.bundleName || "--"}，共 ${event.caseTotal ?? 0} 个 case。`
        : `Session ${event.sessionId || "--"} started with bundle ${event.bundleName || "--"} across ${event.caseTotal ?? 0} cases.`;
    }

    if (eventType === "role_start") {
      return lang === "zh"
        ? `${casePrefix || "当前 case"} ${event.caseId || "--"} 开始执行 ${roleText}，场景 ${event.scenario || "--"}，模式 ${event.mode || "--"}。`
        : `${casePrefix || "Current case"} ${event.caseId || "--"} started for ${roleText} in scenario ${event.scenario || "--"} and mode ${event.mode || "--"}.`;
    }

    if (eventType === "role_finish") {
      const statusText = statusLabel(event.resultStatus || event.status);
      return lang === "zh"
        ? `${casePrefix || "当前 case"} ${event.caseId || "--"} 的 ${roleText} 已完成，结果 ${statusText}${reasonText ? `，原因：${reasonText}` : ""}${elapsedText ? `，耗时 ${elapsedText}s` : ""}。`
        : `${casePrefix || "Current case"} ${event.caseId || "--"} finished for ${roleText} with ${statusText}${reasonText ? `, reason: ${reasonText}` : ""}${elapsedText ? `, elapsed ${elapsedText}s` : ""}.`;
    }

    if (eventType === "session_error") {
      const errorLabel = String(event.errorType || "").trim() || (lang === "zh" ? "异常" : "error");
      return lang === "zh"
        ? `${casePrefix || "当前 case"} ${event.caseId || "--"} 的 ${roleText} 出现 ${errorLabel}：${reasonText || event.summary}`
        : `${casePrefix || "Current case"} ${event.caseId || "--"} hit ${errorLabel} during ${roleText}: ${reasonText || event.summary}`;
    }

    if (
      eventType === "pause_requested"
      || eventType === "run_paused"
      || eventType === "run_resumed"
      || eventType === "stop_requested"
      || eventType === "run_cancelled"
    ) {
      return event.summary;
    }

    if (eventType === "session_finish" || eventType === "run_completed") {
      const decisionText = event.decision ? displayDecisionLabel(event.decision) : "--";
      return lang === "zh"
        ? `治理结论为 ${decisionText}${reasonText ? `，原因：${reasonText}` : ""}。`
        : `The governance result is ${decisionText}${reasonText ? `, reason: ${reasonText}` : ""}.`;
    }

    if (eventType === "run_failed") {
      return lang === "zh"
        ? `这一轮监督运行失败了：${reasonText || event.summary}`
        : `This supervised run failed: ${reasonText || event.summary}`;
    }

    return event.summary;
  }

  function caseIoEntryLabel(kind: string, label: string, status?: string) {
    const normalizedKind = String(kind || "").trim().toLowerCase();
    const normalizedLabel = String(label || "").trim();
    const normalizedStatus = String(status || "").trim().toLowerCase();
    if (normalizedKind === "tool") {
      return normalizedLabel || t("ioEntryTool");
    }
    if (normalizedKind === "assistant") {
      return t("ioEntryAssistant");
    }
    if (normalizedKind === "error") {
      if (normalizedStatus === "recovered") {
        return t("ioEntryRecoveredError");
      }
      return normalizedLabel || t("ioEntryError");
    }
    return normalizedLabel || t("ioEntryPrompt");
  }

  function currentCaseOutputLabel(run: EvolutionActiveRun | null) {
    const outputKind = String(run?.currentCaseIo?.latestOutputKind || "").trim().toLowerCase();
    const outputLabel = String(run?.currentCaseIo?.latestOutputLabel || "").trim();
    if (outputKind === "tool") {
      return outputLabel || t("ioEntryTool");
    }
    if (outputKind === "assistant") {
      return t("ioEntryAssistant");
    }
    if (outputKind === "error") {
      return outputLabel || t("ioEntryError");
    }
    return t("currentCaseOutput");
  }

  function caseTraceIcon(item: SupervisedCaseTraceItem) {
    if (item.tone === "tool") {
      return <Wrench size={15} />;
    }
    if (item.tone === "assistant") {
      return <Sparkles size={15} />;
    }
    if (item.tone === "error") {
      return <TriangleAlert size={15} />;
    }
    if (item.tone === "input") {
      return <Play size={14} />;
    }
    return <Activity size={15} />;
  }

  function caseTraceItemExpanded(item: SupervisedCaseTraceItem) {
    return expandedCaseTraceItems[item.key] ?? item.defaultOpen;
  }

  function toggleCaseTraceItem(item: SupervisedCaseTraceItem) {
    setExpandedCaseTraceItems((current) => ({
      ...current,
      [item.key]: !(current[item.key] ?? item.defaultOpen),
    }));
  }

  function renderCaseTraceSection(section: SupervisedCaseTraceItem["sections"][number], index: number) {
    if (section.kind === "state") {
      return (
        <div key={`${section.label}-${index}`} className={styles.caseTraceStateGrid}>
          {section.rows.map((row) => (
            <dl key={`${section.label}-${row.label}`} className={styles.caseTraceStateRow}>
              <dt>{row.label}</dt>
              <dd>{row.value}</dd>
            </dl>
          ))}
        </div>
      );
    }
    return (
      <div
        key={`${section.label}-${index}`}
        className={
          section.kind === "json"
            ? `${styles.caseTraceSection} ${styles.caseTraceSectionJson}`
            : styles.caseTraceSection
        }
      >
        <span>{section.label}</span>
        <pre>{section.content}</pre>
      </div>
    );
  }

  function triggerRunAction(sessionId: string, action: string) {
    setActionFeedback("");
    actionMutation.mutate({ sessionId, action });
  }

  function toggleRunSelection(run: EvolutionRun) {
    if (!run.canDelete) {
      return;
    }
    setRunRecordsFeedback("");
    setSelectedRunIds((current) =>
      current.includes(run.id)
        ? current.filter((item) => item !== run.id)
        : [...current, run.id],
    );
  }

  function selectVisibleRunRecords() {
    setRunRecordsFeedback("");
    setSelectedRunIds(visibleDeletableRunIds);
  }

  function triggerRunRecordDelete(sessionId: string) {
    setRunRecordsFeedback("");
    deleteRunRecordMutation.mutate(sessionId);
  }

  function triggerBulkRunRecordDelete() {
    if (selectedRunIds.length === 0) {
      return;
    }
    setRunRecordsFeedback("");
    bulkDeleteRunRecordsMutation.mutate(selectedRunIds);
  }

  function toggleProposalSelection(item: EvolutionLibraryEntry) {
    if (!item.canDelete) {
      return;
    }
    const sessionId = item.sourceRun;
    setSelectedProposalRunIds((current) =>
      current.includes(sessionId)
        ? current.filter((item) => item !== sessionId)
        : [...current, sessionId],
    );
  }

  function proposalSelected(sessionId: string) {
    return selectedProposalRunIds.includes(sessionId);
  }

  function triggerProposalDelete(sessionId: string) {
    setLibraryFeedback("");
    deleteProposalMutation.mutate(sessionId);
  }

  function beginProposalEdit(detail: EvolutionProposalDetail) {
    setProposalEditDraft(proposalEditDraftFromDetail(detail));
    setProposalEditFeedback("");
    setProposalEditOpen(true);
  }

  function cancelProposalEdit(detail: EvolutionProposalDetail) {
    setProposalEditDraft(proposalEditDraftFromDetail(detail));
    setProposalEditFeedback("");
    setProposalEditOpen(false);
  }

  function updateProposalEditDraft(field: keyof ProposalEditDraft, value: string) {
    setProposalEditDraft((current) => ({ ...current, [field]: value }));
  }

  function triggerProposalUpdate(sessionId: string) {
    setProposalEditFeedback("");
    updateProposalMutation.mutate({ sessionId, draft: proposalEditDraft });
  }

  function triggerBulkDelete() {
    if (selectedProposalRunIds.length === 0) {
      return;
    }
    setLibraryFeedback("");
    bulkDeleteMutation.mutate(selectedProposalRunIds);
  }

  function clearLibraryFilters() {
    setLibrarySearchInput("");
    setLibraryStatusFilter("all");
    setLibraryDeleteFilter("all");
  }

  function handleRunsResizeStart(event: PointerEvent<any>) {
    if (runsQueueCollapsed) {
      return;
    }
    startEvolutionPaneResize("runs-queue", event as PointerEvent<HTMLDivElement>, { direction: 1 });
  }

  function handleRunsResizeKeyDown(event: KeyboardEvent<any>) {
    if (runsQueueCollapsed) {
      return;
    }
    onEvolutionPaneResizeKeyDown("runs-queue", event as KeyboardEvent<HTMLDivElement>, { direction: 1 });
  }

  function handleLiveLaunchResizeStart(event: PointerEvent<any>) {
    if (liveLaunchCollapsed) {
      return;
    }
    startEvolutionPaneResize("live-launch", event as PointerEvent<HTMLDivElement>, { direction: 1 });
  }

  function handleLiveLaunchResizeKeyDown(event: KeyboardEvent<any>) {
    if (liveLaunchCollapsed) {
      return;
    }
    onEvolutionPaneResizeKeyDown("live-launch", event as KeyboardEvent<HTMLDivElement>, { direction: 1 });
  }

  function handleLiveRunResizeStart(event: PointerEvent<any>) {
    if (liveRunCollapsed) {
      return;
    }
    startEvolutionPaneResize("live-run", event as PointerEvent<HTMLDivElement>, { direction: -1 });
  }

  function handleLiveRunResizeKeyDown(event: KeyboardEvent<any>) {
    if (liveRunCollapsed) {
      return;
    }
    onEvolutionPaneResizeKeyDown("live-run", event as KeyboardEvent<HTMLDivElement>, { direction: -1 });
  }

  function handleLiveIoResizeStart(event: PointerEvent<any>) {
    startEvolutionHeightResize("live-io", event, { direction: 1 });
  }

  function handleLiveIoResizeKeyDown(event: KeyboardEvent<any>) {
    onEvolutionHeightResizeKeyDown("live-io", event, { direction: 1 });
  }

  function handleLibraryResizeStart(event: PointerEvent<any>) {
    if (libraryListCollapsed) {
      return;
    }
    startEvolutionPaneResize("library-list", event as PointerEvent<HTMLDivElement>, { direction: 1 });
  }

  function handleLibraryResizeKeyDown(event: KeyboardEvent<any>) {
    if (libraryListCollapsed) {
      return;
    }
    onEvolutionPaneResizeKeyDown("library-list", event as KeyboardEvent<HTMLDivElement>, { direction: 1 });
  }

  function renderReviewList(lines: string[]) {
    if (lines.length === 0) {
      return <p>--</p>;
    }
    return (
      <ul className={styles.detailList}>
        {lines.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    );
  }

  function renderRawJson(title: string, payload: Record<string, unknown> | null) {
    return (
      <details className={styles.rawBlock}>
        <summary>{title}</summary>
        <pre className={styles.rawJson}>{JSON.stringify(payload ?? {}, null, 2)}</pre>
      </details>
    );
  }

  function renderSelfEvolutionCandidateDetail(item: EvolutionLibraryEntry) {
    const evidenceRefs = item.evidenceRefs ?? [];
    const allowedUses = item.allowedDownstreamUses ?? [];
    const blockedUses = item.blockedDownstreamUses ?? [];
    return (
      <>
        <div className={styles.detailHeader}>
          <div>
            <p className={styles.eyebrow}>{t("pendingReview")}</p>
            <h2 className={styles.detailTitle}>{item.title}</h2>
          </div>
          <span className={styles.statusPill}>{item.outcomeSemantics.proposalStatusLabel}</span>
        </div>

        <div className={styles.detailSection}>
          <h3>{t("reviewHeadline")}</h3>
          <p className={styles.reviewLead}>{item.headline || item.summary}</p>
          <VTooltip content={item.reason || item.outcomeSemantics.runtimeExplanation} width="wide">
            <p tabIndex={0}>
              {displaySupervisedTechnicalText(item.reason || item.outcomeSemantics.runtimeExplanation, item.decision, lang, decisionLabel)}
            </p>
          </VTooltip>
        </div>

        <div className={styles.detailSection}>
          <h3>{t("resultLayersTitle")}</h3>
          <div className={styles.relatedList}>
            <article className={styles.relatedRow}>
              <strong>{t("sourceRun")}</strong>
              <span>{proposalDisplaySourceRun(item) || "--"}</span>
            </article>
            <article className={styles.relatedRow}>
              <strong>candidate_id</strong>
              <span>{item.id}</span>
            </article>
            <article className={styles.relatedRow}>
              <strong>{t("proposalUpdatedAt")}</strong>
              <span>{compactTimestamp(item.updatedAt)}</span>
            </article>
            <article className={styles.relatedRow}>
              <strong>{t("proposalLayer")}</strong>
              <span>{item.outcomeSemantics.proposalStatusLabel}</span>
            </article>
            <article className={styles.relatedRow}>
              <strong>{t("runtimeLayer")}</strong>
              <span>{item.outcomeSemantics.runtimeEffectLabel}</span>
            </article>
            <article className={styles.relatedRow}>
              <strong>{t("targetLabelTitle")}</strong>
              <span>{item.targetLabel || item.candidateType || item.targetKey || "--"}</span>
            </article>
            <article className={styles.relatedRow}>
              <strong>{t("availableActions")}</strong>
              <span>{formatAvailableActions(item.availableActions)}</span>
            </article>
          </div>
          <VTooltip content={item.outcomeSemantics.runtimeExplanation} width="wide">
            <p className={styles.noticeText} tabIndex={0}>
              {displaySupervisedTechnicalText(item.outcomeSemantics.runtimeExplanation, item.decision, lang, decisionLabel)}
            </p>
          </VTooltip>
        </div>

        <div className={styles.detailSection}>
          <h3>{t("currentStateTitle")}</h3>
          <div className={styles.relatedList}>
            <article className={styles.relatedRow}>
              <strong>review_state</strong>
              <span>{item.reviewState || "--"}</span>
            </article>
            <article className={styles.relatedRow}>
              <strong>{t("riskLevel")}</strong>
              <span>{item.riskLevel ? riskLabel(item.riskLevel) : "--"}</span>
            </article>
            <article className={styles.relatedRow}>
              <strong>supervised_required</strong>
              <span>{item.supervisedRequired ? "true" : "false"}</span>
            </article>
            <article className={styles.relatedRow}>
              <strong>candidate_only</strong>
              <span>{item.candidateOnly ? "true" : "false"}</span>
            </article>
            <article className={styles.relatedRow}>
              <strong>auto_apply</strong>
              <span>{item.autoApply ? "true" : "false"}</span>
            </article>
            <article className={styles.relatedRow}>
              <strong>allowed_downstream_uses</strong>
              <span>{allowedUses.length > 0 ? allowedUses.join(", ") : "--"}</span>
            </article>
            <article className={styles.relatedRow}>
              <strong>blocked_downstream_uses</strong>
              <span>{blockedUses.length > 0 ? blockedUses.join(", ") : "--"}</span>
            </article>
          </div>
        </div>

        <div className={styles.detailSection}>
          <h3>{t("deleteAndCleanup")}</h3>
          <div className={styles.relatedList}>
            <article className={styles.relatedRow}>
              <strong>{item.canDelete ? t("deletionAllowed") : t("deletionBlocked")}</strong>
              <span>{item.canDelete ? t("deleteProposal") : item.deleteBlockReason || "--"}</span>
            </article>
          </div>
        </div>

        <div className={styles.detailSection}>
          <h3>{t("evidencePaths")}</h3>
          <div className={styles.relatedList}>
            {evidenceRefs.length > 0 ? (
              evidenceRefs.map((path) => (
                <article key={path} className={styles.relatedRow}>
                  <strong>evidence</strong>
                  <span className={styles.pathText}>{path}</span>
                </article>
              ))
            ) : (
              <article className={styles.relatedRow}>
                <strong>evidence</strong>
                <span>--</span>
              </article>
            )}
            {item.sourceExperienceId ? (
              <article className={styles.relatedRow}>
                <strong>source_experience_id</strong>
                <span>{item.sourceExperienceId}</span>
              </article>
            ) : null}
            {item.sourceReflectionId ? (
              <article className={styles.relatedRow}>
                <strong>source_reflection_id</strong>
                <span>{item.sourceReflectionId}</span>
              </article>
            ) : null}
            {item.txnId ? (
              <article className={styles.relatedRow}>
                <strong>txn_id</strong>
                <span>{item.txnId}</span>
              </article>
            ) : null}
          </div>
        </div>

        <div className={styles.detailSection}>
          <div className={styles.rawBlockStack}>
            {renderRawJson("candidate_payload", item.payload ?? null)}
            {renderRawJson("provenance", item.provenance ?? null)}
          </div>
        </div>
      </>
    );
  }

  return (
    <div
      ref={evolutionLayoutRef}
      className={activeTrack === "self" ? `${styles.page} ${styles.selfPage}` : styles.page}
      data-vui-recipe="evolution-workbench"
      data-vui-layout-id={EVOLUTION_LAYOUT_ID}
    >
      {showRouteToolbar ? (
        <VRouteHeader
          aria-label={routeTitle}
          hideIntro={hideSupervisedToolbarIntro}
          className={
            hideSupervisedToolbarIntro
              ? styles.toolbarSupervisedFocus
              : styles.toolbar
          }
          eyebrow={routeEyebrow}
          title={routeTitle}
          meta={routeSubtitle}
          actions={(
            <div
            className={
              hideSupervisedToolbarIntro
                ? styles.toolbarControlsSupervisedFocus
                : styles.toolbarControls
            }
          >
            {showTrackToggle ? (
              <div className={styles.segmented}>
                {([
                  { key: "supervised", label: t("supervisedEvolutionMode") },
                  { key: "self", label: t("selfEvolutionMode") },
                ] as const).map((track) => (
                  <VButton
                    key={track.key}
                    type="button"
                    className={
                      activeTrack === track.key
                        ? `${styles.segmentButton} ${styles.segmentButtonActive}`
                        : styles.segmentButton
                    }
                    onPress={() => setEvolutionTrack(track.key)}
                  >
                    {track.label}
                  </VButton>
                ))}
              </div>
            ) : null}

            {activeTrack === "supervised" ? (
              <SupervisedWorkspaceControls
                activeView={evolutionView}
                activeWorkflowStepId={supervisedSelectedWorkflowStepId}
                onWorkflowStepSelect={handleSupervisedWorkflowStepSelect}
                overviewIntakeMode={overview?.intakeMode}
                configIntakeMode={configQuery.data?.intakeMode}
                tabSummaries={supervisedTabSummaries}
              />
            ) : null}
            </div>
          )}
        />
      ) : null}

      {activeTrack === "self" ? (
        <EvolutionSelfTrackBoundary
          lang={lang}
          overview={selfOverview}
          worktreeRun={selfWorktreeRun}
          observationRun={selfObservationRun ?? null}
          goalInput={selfGoalInput}
          onGoalInputChange={setSelfGoalInput}
          onStartRun={() => startSelfWorktreeRunMutation.mutate()}
          onStartObservation={(payload) => startSelfObservationMutation.mutate(payload)}
          onTerminateObservation={(runId) => selfObservationActionMutation.mutate({ runId, action: "terminate" })}
          onWorktreeAction={(runId, action) => approvalWorktreeActionMutation.mutate({ runId, action })}
          onDeleteHistoryGroups={(txnIds) => deleteSelfHistoryMutation.mutate(txnIds)}
          startPending={startSelfWorktreeRunMutation.isPending}
          observationStartPending={startSelfObservationMutation.isPending}
          observationActionPending={selfObservationActionMutation.isPending}
          worktreeActionPending={approvalWorktreeActionMutation.isPending}
          deleteHistoryPending={deleteSelfHistoryMutation.isPending}
          startWorktreeError={startSelfWorktreeRunMutation.error?.message ?? ""}
          observationStartError={startSelfObservationMutation.error?.message ?? ""}
          observationActionError={selfObservationActionMutation.error?.message ?? ""}
          worktreeActionError={approvalWorktreeActionMutation.error?.message ?? ""}
          deleteHistoryError={deleteSelfHistoryMutation.error?.message ?? ""}
          actionFeedback={selfActionFeedback}
          runLocked={selfRunLocked}
          worktreeRunLocked={worktreeRunLocked}
          transactions={selfTransactions}
          loading={selfTrackLoading}
        />
      ) : null}

      {activeTrack === "supervised" && evolutionView === "live" ? (
        <div className={styles.overviewGrid} style={liveWorkspaceStyle}>
          <section
            className={
              liveLaunchCollapsed
                ? `${styles.dashboardLaunch} ${styles.liveLaunchStack} ${styles.paneCollapsed}`
                : `${styles.dashboardLaunch} ${styles.liveLaunchStack}`
            }
            aria-hidden={liveLaunchCollapsed}
          >
            <VSurface
              as="section"
              className={`${styles.surface} ${styles.launchSurface} ${styles.supervisedRunConsole}`}
              elevation="panel"
              padding="none"
              tone="panel"
            >
              <div className={`${styles.surfaceHeaderCompact} ${styles.supervisedRunConsoleHeader}`}>
                <div>
                  <p className={styles.eyebrow}>{t("supervisedControl")}</p>
                  <h2 className={styles.sectionTitle}>{lang === "zh" ? "监督运行控制台" : "Supervised run console"}</h2>
                </div>
                <div className={styles.supervisedRunConsoleStatus}>
                  <span className={styles.secondaryPill}>
                    {lang === "zh" ? "来源" : "Source"} {sourceCatalogCountLabel}
                  </span>
                  <span className={styles.secondaryPill}>
                    {supervisedMembersRun ? supervisedMembersRunStatusLabel : supervisedMembersIdleStatusLabel}
                  </span>
                </div>
              </div>

              <VSection
                className={styles.sourceInventorySection}
                eyebrow={lang === "zh" ? "运行前检查" : "Preflight"}
                title={lang === "zh" ? "监督运行来源" : "Supervised run sources"}
              >
                <VMetricStrip
                  ariaLabel={lang === "zh" ? "监督运行来源概览" : "Supervised run source overview"}
                  className={styles.sourceInventoryBar}
                  metrics={[
                    { id: "datasets", label: lang === "zh" ? "数据集" : "Datasets", value: workbenchCatalogLoading ? "--" : primaryDatasets.length },
                    { id: "bundles", label: lang === "zh" ? "评测包" : "Bundles", value: workbenchCatalogLoading ? "--" : availableBundles.length },
                    { id: "evidence", label: lang === "zh" ? "证据根" : "Evidence", value: supervisedEvidenceRootLabel, detail: supervisedEvidenceRootTitle },
                    ...(hiddenDatasetCount > 0 ? [{ id: "hidden", label: lang === "zh" ? "隐藏" : "Hidden", value: hiddenDatasetCount }] : []),
                  ]}
                />
              </VSection>
              {datasetCatalog.length > 0 ? (
                <details className={styles.datasetCatalogPanel}>
                  <summary className={styles.datasetCatalogSummary}>
                    <span>
                      <strong>{t("datasetCatalog")}</strong>
                      <span>
                        {datasetCatalog.length} · {lang === "zh" ? "可运行" : "runnable"} {datasetCatalogGroups.runnable.length}
                      </span>
                    </span>
                    <span>{lang === "zh" ? "展开管理" : "Manage"}</span>
                  </summary>
                  <div className={styles.datasetCatalogBody}>
                    <div className={styles.datasetCatalogFilterRow} role="tablist" aria-label={t("datasetCatalog")}>
                      {([
                        ["all", t("datasetCatalogAll"), datasetCatalogGroups.all.length],
                        ["runnable", t("datasetCatalogRunnable"), datasetCatalogGroups.runnable.length],
                        ["blocked", t("datasetCatalogBlocked"), datasetCatalogGroups.blocked.length],
                        ["roadmap", t("datasetCatalogRoadmap"), datasetCatalogGroups.roadmap.length],
                      ] as Array<[DatasetCatalogFilter, string, number]>).map(([filter, label, count]) => (
                        <VButton
                          key={filter}
                          type="button"
                          className={
                            selectedDatasetCatalogFilter === filter
                              ? `${styles.datasetCatalogFilterButton} ${styles.datasetCatalogFilterButtonActive}`
                              : styles.datasetCatalogFilterButton
                          }
                          onClick={() => setSelectedDatasetCatalogFilter(filter)}
                          aria-pressed={selectedDatasetCatalogFilter === filter}
                        >
                          {label} {count}
                        </VButton>
                      ))}
                    </div>
                    <div className={styles.datasetCatalogList}>
                      {visibleDatasetCatalog.length > 0 ? (
                        visibleDatasetCatalog.map((item) => {
                          const statusText = datasetCatalogStatusLabel(item, lang);
                          const reason = item.visibility === "primary"
                            ? item.usabilityReason
                            : (item.visibilityReason || item.usabilityReason);
                          return (
                            <article key={item.name} className={styles.datasetCatalogItem}>
                              <div className={styles.datasetCatalogItemMain}>
                                <VTooltip content={item.name} width="wide">
                                  <strong tabIndex={0}>{item.name}</strong>
                                </VTooltip>
                                <span>{item.benchmarkFamily || item.taskType || item.bundleName || "--"}</span>
                              </div>
                              <span className={styles.datasetCatalogStatus}>{statusText}</span>
                              {reason ? (
                                <p>
                                  <span>{item.visibility === "primary" ? statusText : t("datasetCatalogHiddenReason")}</span>
                                  {reason}
                                </p>
                              ) : null}
                            </article>
                          );
                        })
                      ) : (
                        <p className={styles.datasetCatalogEmpty}>{lang === "zh" ? "当前筛选无条目。" : "No entries for this filter."}</p>
                      )}
                    </div>
                  </div>
                </details>
              ) : null}
              {workbenchCatalogUnavailable ? (
                <p className={styles.errorTextCompact}>
                  {lang === "zh" ? "评测来源暂时不可用，正在等待目录刷新。" : "Evaluation sources are temporarily unavailable while the catalog refreshes."}
                </p>
              ) : null}

              <div className={styles.supervisedRunConsoleGrid}>
                <div className={styles.supervisedRunSetup}>
                  <div className={styles.formGrid}>
                    <div className={sourceKind === "dataset" ? styles.compactFieldGrid : styles.formGrid}>
                      <div className={styles.formField}>
                        <div className={styles.formLabelWithHint}>
                          <label>{lang === "zh" ? "评测来源" : "Evaluation source"}</label>
                          <VContextualHint
                            content={lang === "zh" ? "数据集会先物化，评测包可直接运行。" : "A dataset is materialized first; a bundle runs directly."}
                            label={lang === "zh" ? "评测来源说明" : "Evaluation source help"}
                          />
                        </div>
                        <VStringSelect
                          ariaLabel={lang === "zh" ? "评测来源" : "Evaluation source"}
                          className={styles.selectInput}
                          value={selectedSourceValue}
                          options={supervisedSourceOptions.map((source) => ({
                            value: source.value,
                            label: source.kind === "dataset"
                              ? `${source.name} [${datasetUsabilityLabel(source.dataset, lang)}]`
                              : `${source.name} [${source.caseCount} cases]`,
                          }))}
                          onValueChange={(value) => {
                            const [nextKind, ...nameParts] = value.split(":");
                            const nextName = nameParts.join(":");
                            if (nextKind === "bundle") {
                              setSourceKind("bundle");
                              setBundleNameInput(nextName);
                              return;
                            }
                            setSourceKind("dataset");
                            setDatasetName(nextName);
                          }}
                        />
                      </div>
                      {sourceKind === "dataset" ? (
                        <div className={styles.formField}>
                          <div className={styles.formLabelWithHint}>
                            <label htmlFor="supervised-limit">{t("caseLimit")}</label>
                            <VContextualHint content={t("caseLimitHint")} label={`${t("caseLimit")}说明`} />
                          </div>
                          <VInput
                            ref={datasetLimitInputRef}
                            id="supervised-limit"
                            className={styles.textInput}
                            type="number"
                            min={1}
                            placeholder="all"
                            value={datasetLimitInput}
                            onChange={(event) => setDatasetLimitInput(event.target.value)}
                          />
                        </div>
                      ) : null}
                    </div>
                    {selectedSourceOption ? (
                      <div className={styles.sourceMetaCompact}>
                        <div className={styles.sourceMetaMain}>
                          <strong>{selectedSourceOption.label}</strong>
                          <span>{selectedSourceStatusText}</span>
                          {selectedSourceEvaluationText ? <span>{selectedSourceEvaluationText}</span> : null}
                        </div>
                        <span className={styles.sourceMetaSide}>
                          {selectedSourceKindLabel} · {selectedSourceCaseText}
                        </span>
                      </div>
                    ) : null}
                    {selectedSourceOfficialWarning ? (
                      <p className={styles.sourceWarningStrip}>{selectedSourceOfficialWarning}</p>
                    ) : null}
                    {workbenchControl && sourceKind === "bundle" && !selectedBundleExists ? (
                      <p className={styles.errorTextCompact}>
                        {lang === "zh" ? "请选择一个存在的监督评测包。" : "Choose an existing supervised bundle."}
                      </p>
                    ) : null}
                  </div>

                  <div className={styles.supervisedRunOptions}>
                    <VCheckbox
                      className={styles.checkboxRow}
                      isSelected={keepWorktree}
                      onChange={setKeepWorktree}
                    >
                      <span className={styles.checkboxLabel}>{lang === "zh" ? "保留 worktree" : "Keep worktree"}</span>
                    </VCheckbox>
                    <div className={styles.formField}>
                      <div className={styles.formLabelWithHint}>
                        <label>{t("supervisedMentalMode")}</label>
                        <VContextualHint content={t("supervisedMentalModeHint")} label={`${t("supervisedMentalMode")}说明`} />
                      </div>
                      <VStringSelect
                        ariaLabel={t("supervisedMentalMode")}
                        className={styles.selectInput}
                        value={supervisedMentalModelMode}
                        options={[
                          { value: "follow", label: t("supervisedMentalModeFollow") },
                          { value: "enabled", label: t("supervisedMentalModeEnabled") },
                          { value: "disabled", label: t("supervisedMentalModeDisabled") },
                        ]}
                        onValueChange={(value) => setSupervisedMentalModelMode(value as SupervisedMentalModelMode)}
                      />
                    </div>
                  </div>

                  <div className={styles.controlFooter}>
                    <div className={styles.controlActions}>
                      <VButton
                        type="button"
                        variant="primary"
                        className={`${styles.inlineAction} ${styles.supervisedPrimaryAction}`}
                        isDisabled={
                          runLocked
                          || worktreeRunLocked
                          || !workbenchControl
                          || startWorktreeRunMutation.isPending
                          || (sourceKind === "dataset" && !datasetName)
                          || (sourceKind === "bundle" && !selectedBundleExists)
                        }
                        onClick={() => startWorktreeRunMutation.mutate()}
                        tooltip={t("launchSupervisedRunHint")}
                        disabledReason={supervisedStartDisabledReason}
                        icon={
                          supervisedStartSubmitting || supervisedPrimaryRunning
                            ? <LoaderCircle size={15} />
                            : <Play size={15} />
                        }
                      >
                        {supervisedStartButtonLabel}
                      </VButton>
                    </div>
                    {runLocked || worktreeRunLocked ? <p className={styles.noticeText}>{t("runningLockHint")}</p> : null}
                    {supervisedControlError ? (
                      <p className={styles.errorText}>{supervisedControlError}</p>
                    ) : null}
                  </div>
                </div>

                <aside className={styles.supervisedWorkflowPanel}>
                  <div className={styles.supervisedMembersHeader}>
                    <div>
                      <p className={styles.eyebrow}>
                        {supervisedMembersSource === "run" ? lang === "zh" ? "运行步骤" : "Run steps" : lang === "zh" ? "当前步骤" : "Current steps"}
                      </p>
                      <h3 className={`${styles.sectionTitle} ${styles.formLabelWithHint}`}>
                        {supervisedWorkflowStepLabel(supervisedSelectedWorkflowStep, lang)}
                        {supervisedMembersHint ? (
                          <VContextualHint content={supervisedMembersHint} label={lang === "zh" ? "监督成员绑定说明" : "Supervised member binding help"} width="wide" />
                        ) : null}
                      </h3>
                    </div>
                    <div className={styles.supervisedMembersHeaderActions}>
                      {supervisedWorkflowManualSelection ? (
                        <VButton
                          type="button"
                          className={styles.supervisedWorkflowFollowButton}
                          onClick={() => setSelectedSupervisedWorkflowStepId(null)}
                          tooltip={lang === "zh" ? "回到当前执行阶段" : "Follow the current run stage"}
                        >
                          {lang === "zh" ? "跟随现场" : "Follow live"}
                        </VButton>
                      ) : null}
                      <span className={styles.secondaryPill}>{supervisedWorkflowCards.length}</span>
                    </div>
                  </div>
                  <div className={styles.workflowStepRail} aria-label={lang === "zh" ? "监督进化步骤导航" : "Supervised evolution step navigation"}>
                    {supervisedWorkflowCards.map((step) => {
                      const selected = step.id === supervisedSelectedWorkflowStep.id;
                      const current = step.id === supervisedRuntimeWorkflowStepId;
                      const member = step.member;
                      const stepRoute = step.chatRoute || (member && member.chatRoute) || "";
                      const stepMeta = step.role ? runRoleLabel(step.role) : (lang === "zh" ? "人工审批" : "Human approval");
                      const stepMetric = typeof step.metrics?.scoreDelta === "number"
                        ? `Δ ${step.metrics.scoreDelta}`
                          : typeof step.metrics?.score === "number"
                            ? String(step.metrics.score)
                            : statusLabel(step.status);
                      return (
                        <div
                          key={step.id}
                          className={current && !selected ? `${styles.workflowStepItem} ${styles.workflowStepItemCurrent}` : styles.workflowStepItem}
                        >
                          <VButton
                            type="button"
                            contentLayout="plain"
                            className={selected ? `${styles.workflowStepButton} ${styles.workflowStepButtonActive}` : styles.workflowStepButton}
                            aria-pressed={selected}
                            onClick={() => handleSupervisedWorkflowStepSelect(step.id)}
                            tooltip={lang === "zh" ? `查看${supervisedWorkflowStepLabel(step, lang)}` : `View ${supervisedWorkflowStepLabel(step, lang)}`}
                          >
                            <span className={styles.workflowStepMeta}>
                              <span>{current ? (lang === "zh" ? "当前" : "Live") : stepMetric}</span>
                              <span>{stepMeta}</span>
                            </span>
                            <strong>{supervisedWorkflowStepLabel(step, lang)}</strong>
                            <span className={styles.workflowStepPreview}>
                              {step.livePreview || step.summary || (lang === "zh" ? "等待实时输出" : "Waiting for live output")}
                            </span>
                          </VButton>
                          {stepRoute ? (
                            <VTooltip content={
                              member?.chatRoute
                                ? lang === "zh" ? `打开监督成员 ${member.name} 的会话` : `Open supervised member session for ${member.name}`
                                : lang === "zh" ? "打开监督会话" : "Open supervised session"
                            }>
                              <Link
                                className={styles.supervisedWorkflowSessionLink}
                                to={stepRoute}
                                aria-label={
                                member?.chatRoute
                                  ? lang === "zh" ? `打开监督成员 ${member.name} 的会话` : `Open supervised member session for ${member.name}`
                                  : lang === "zh" ? "打开监督会话" : "Open supervised session"
                                }
                              >
                                <span>{lang === "zh" ? "会话" : "Session"}</span>
                                <ArrowUpRight size={13} aria-hidden="true" />
                              </Link>
                            </VTooltip>
                          ) : member?.configRoute ? (
                            <VTooltip content={lang === "zh" ? `配置 ${member.name}` : `Configure ${member.name}`}>
                              <Link className={styles.supervisedWorkflowSessionLink} to={member.configRoute}>
                                <span>{lang === "zh" ? "配置" : "Config"}</span>
                                <ArrowUpRight size={13} aria-hidden="true" />
                              </Link>
                            </VTooltip>
                          ) : null}
                        </div>
                      );
                    })}
                  </div>
                </aside>
              </div>
            </VSurface>

          </section>

          <PaneCollapseHandle
            side="left"
            collapsed={liveLaunchCollapsed}
            separatorLabel={resizeLiveLaunchLabel}
            collapseLabel={lang === "zh" ? "收起启动卡片" : "Collapse launch card"}
            expandLabel={lang === "zh" ? "展开启动卡片" : "Expand launch card"}
            className={`${styles.resizeHandle} ${styles.liveResizeHandle} ${styles.liveResizeHandleLaunch}`}
            active={evolutionDraggingPaneId === "live-launch"}
            valueNow={liveLaunchWidth}
            valueMin={EVOLUTION_LIVE_LAUNCH_PANE.minWidth}
            valueMax={EVOLUTION_LIVE_LAUNCH_PANE.maxWidth}
            onToggle={() => setLiveLaunchCollapsed((current) => !current)}
            onPointerDown={handleLiveLaunchResizeStart}
            onKeyDown={handleLiveLaunchResizeKeyDown}
          />

          <Suspense fallback={<p className={styles.noticeText}>{t("loading")}</p>}>
            <EvolutionActiveRunMonitorPanel
              ariaHidden={liveRunCollapsed}
              className={
                liveRunCollapsed
                  ? `${styles.surface} ${styles.liveSurface} ${styles.dashboardRun} ${styles.paneCollapsed}`
                  : `${styles.surface} ${styles.liveSurface} ${styles.dashboardRun}`
              }
              header={{
                eyebrow: t("activeSupervisedRun"),
                title: monitoredRunIdentity || t("activeSupervisedRun"),
                titleTooltip: monitoredRunIdentity || undefined,
                statusLabel: monitoredRun ? monitoredStatusLabel : undefined,
                sourceKindLabel: monitoredRun ? sourceKindLabel(monitoredRun.sourceKind) : undefined,
                fallbackStatusLabel: workbenchSourceLabel(workbenchState?.source ?? "unknown"),
              }}
              run={supervisedActiveRunMonitorRun}
              idle={{
                notice: t("noActiveSupervisedRun"),
                closedLoop: supervisedClosedLoopLedger,
                metrics: supervisedActiveRunMonitorIdleMetrics,
                related: supervisedActiveRunMonitorIdleRelated,
                latestRunAction: {
                  label: t("openLatestRuns"),
                  disabled: !overviewLatestRunId,
                  onClick: () => openRun(overviewLatestRunId || null),
                },
                libraryAction: {
                  label: t("openLibraryQueue"),
                  onClick: () => {
                    setLibraryView("items");
                    goToSupervisedView("library");
                  },
                },
              }}
            />
          </Suspense>

          <PaneCollapseHandle
            side="right"
            collapsed={liveRunCollapsed}
            separatorLabel={resizeLiveRunLabel}
            collapseLabel={lang === "zh" ? "收起当前任务卡片" : "Collapse active run card"}
            expandLabel={lang === "zh" ? "展开当前任务卡片" : "Expand active run card"}
            className={`${styles.resizeHandle} ${styles.liveResizeHandle} ${styles.liveResizeHandleRun}`}
            active={evolutionDraggingPaneId === "live-run"}
            valueNow={liveRunWidth}
            valueMin={EVOLUTION_LIVE_RUN_PANE.minWidth}
            valueMax={EVOLUTION_LIVE_RUN_PANE.maxWidth}
            onToggle={() => setLiveRunCollapsed((current) => !current)}
            onPointerDown={handleLiveRunResizeStart}
            onKeyDown={handleLiveRunResizeKeyDown}
          />

          <VSurface
            as="section"
            className={`${styles.surface} ${styles.ioSurface} ${styles.dashboardIo}`}
            elevation="panel"
            padding="none"
            tone="panel"
          >
              <div className={styles.surfaceHeaderCompact}>
                <div>
                  <p className={styles.eyebrow}>
                    {!supervisedWorkflowRun
                      ? lang === "zh" ? "运行前计划" : "Run plan"
                      : supervisedApprovalSelected
                      ? supervisedWorkflowStepLabel(supervisedSelectedWorkflowStep, lang)
                      : lang === "zh" ? "Agent 对话" : "Agent conversations"}
                  </p>
                  {(supervisedApprovalSelected ? selectedWorkflowTaskSummary : supervisedSelectedAgentTaskSummary) ? (
                    <VTooltip
                      content={supervisedApprovalSelected ? selectedWorkflowTaskSummary : supervisedSelectedAgentTaskSummary}
                      width="wide"
                    >
                      <h2 className={`${styles.sectionTitle} ${styles.truncateText}`} tabIndex={0}>
                        {supervisedApprovalSelected
                          ? supervisedSelectedWorkflowStep.label || t("currentCaseOutput")
                          : !supervisedWorkflowRun
                            ? lang === "zh" ? "本轮监督进化" : "Supervised evolution run"
                          : supervisedSelectedAgentMember?.name || runRoleLabel(supervisedSelectedAgentRole)}
                      </h2>
                    </VTooltip>
                  ) : (
                    <h2 className={`${styles.sectionTitle} ${styles.truncateText}`}>
                      {supervisedApprovalSelected
                        ? supervisedSelectedWorkflowStep.label || t("currentCaseOutput")
                        : !supervisedWorkflowRun
                          ? lang === "zh" ? "本轮监督进化" : "Supervised evolution run"
                        : supervisedSelectedAgentMember?.name || runRoleLabel(supervisedSelectedAgentRole)}
                    </h2>
                  )}
                </div>
                <div className={styles.liveStatusRow}>
                  {supervisedWorkflowRun && !supervisedApprovalSelected ? (
                    <span className={styles.secondaryPill}>{runRoleLabel(supervisedSelectedAgentRole)}</span>
                  ) : null}
                  <span className={styles.secondaryPill}>
                    {!supervisedWorkflowRun
                      ? lang === "zh" ? "未开始" : "Not started"
                      : supervisedApprovalSelected
                      ? statusLabel(supervisedSelectedWorkflowStep.status)
                      : statusLabel(
                        supervisedSelectedAgentMember?.conversationSession?.status
                        || supervisedSelectedAgentMember?.status
                        || "idle",
                      )}
                  </span>
                  {monitoredRun?.currentCaseScenario && supervisedSelectedAgentRole === normalizedSupervisedRuntimeRole ? (
                    <span className={styles.secondaryPill}>{monitoredRun.currentCaseScenario}</span>
                  ) : null}
                  {monitoredRun?.currentCaseMode && supervisedSelectedAgentRole === normalizedSupervisedRuntimeRole ? (
                    <span className={styles.secondaryPill}>{monitoredRun.currentCaseMode}</span>
                  ) : null}
                </div>
              </div>

              <div className={styles.liveIoPane}>
                {!supervisedWorkflowRun ? renderSupervisedRunPlan() : supervisedApprovalSelected ? (
                  <SupervisedApprovalDecisionPanel
                    run={reviewCandidateWorktree}
                    lang={lang}
                    pending={approvalWorktreeActionMutation.isPending}
                    error={approvalWorktreeActionMutation.error?.message ?? ""}
                    onAction={(runId, action) => approvalWorktreeActionMutation.mutate({ runId, action })}
                  />
                ) : (
                  <SupervisedAgentConversationPanel
                    members={supervisedRunMembers}
                    selectedRole={supervisedSelectedAgentRole}
                    activeRole={supervisedActiveAgentRole}
                    fallbackMessages={supervisedSelectedAgentFallbackMessages}
                    taskSummary={supervisedSelectedAgentTaskSummary}
                    supplementalContent={
                      supervisedSelectedAgentRole === normalizedSupervisedRuntimeRole
                        ? supervisedLiveConversationSupplement
                        : undefined
                    }
                    isLive={supervisedRunIsLive}
                    lang={lang}
                    roleLabel={runRoleLabel}
                    roleDescription={supervisedAgentRoleDescription}
                    statusLabel={statusLabel}
                    onSelectRole={handleSupervisedAgentSelect}
                    onFollowLive={handleFollowSupervisedAgent}
                  />
                )}
              </div>

              <PaneHeightResizeHandle
                label={resizeLiveIoLabel}
                valueNow={liveIoHeight}
                valueMin={EVOLUTION_LIVE_IO_HEIGHT_PANE.minHeight}
                valueMax={EVOLUTION_LIVE_IO_HEIGHT_PANE.maxHeight}
                active={evolutionHeightDraggingPaneId === "live-io"}
                className={styles.liveIoResizeHandle}
                onPointerDown={handleLiveIoResizeStart}
                onKeyDown={handleLiveIoResizeKeyDown}
              />
          </VSurface>

        </div>
      ) : null}

      {activeTrack === "supervised" && evolutionView === "runs" ? (
        <div className={styles.viewStack}>
          <VSection
            className={`${styles.surface} ${styles.runsCommandStrip}`}
            eyebrow={t("recentRunPerformance")}
            title={t("runList")}
            actions={(
              <div className={styles.filterSegmented}>
                {(["all", "success", "failed"] as const).map((filter) => (
                  <VButton
                    key={filter}
                    type="button"
                    className={
                      runFilter === filter
                        ? `${styles.filterButton} ${styles.filterButtonActive}`
                        : styles.filterButton
                    }
                    onClick={() => setRunFilter(filter)}
                  >
                    {filter === "all" ? t("allRuns") : supervisedRunBucketLabel(filter, lang, statusLabel)}
                  </VButton>
                ))}
              </div>
            )}
          >

            <div className={styles.runsCommandMetrics}>
              <article className={styles.compactFact}>
                <span>{t("runs")}</span>
                <strong>{hasRuns ? `${filteredRuns.length} / ${runs.length}` : "0 / 0"}</strong>
              </article>
              <article className={styles.compactFact}>
                <span>{supervisedRunBucketLabel("success", lang, statusLabel)}</span>
                <strong>{runSuccessCount}</strong>
              </article>
              <article className={styles.compactFact}>
                <span>{supervisedRunBucketLabel("failed", lang, statusLabel)}</span>
                <strong>{runFailedCount}</strong>
              </article>
              <article className={styles.compactFact}>
                <span>{t("pendingReview")}</span>
                <strong>{runPendingCount}</strong>
              </article>
              <article className={styles.compactFact}>
                <span>{t("deletionAllowed")}</span>
                <strong>{runDeletableCount}</strong>
              </article>
              <article className={styles.compactFact}>
                <span>{t("selectedCount")}</span>
                <strong>{selectedRunIds.length}</strong>
              </article>
            </div>
          </VSection>

          <Suspense fallback={<p className={styles.noticeText}>{t("loading")}</p>}>
            <EvolutionRunRecordsPanel
              className={styles.runsWorkspace}
              style={runsWorkspaceStyle}
              lang={lang}
              labels={{ t, statusLabel, decisionLabel, riskLabel, proposalActionLabel }}
              separator={(
                <PaneCollapseHandle
                  side="left"
                  collapsed={runsQueueCollapsed}
                  separatorLabel={resizeRunsQueueLabel}
                  collapseLabel={lang === "zh" ? "收起运行列表" : "Collapse run list"}
                  expandLabel={lang === "zh" ? "展开运行列表" : "Expand run list"}
                  className={styles.resizeHandle}
                  active={evolutionDraggingPaneId === "runs-queue"}
                  valueNow={runsQueueWidth}
                  valueMin={EVOLUTION_RUNS_QUEUE_PANE.minWidth}
                  valueMax={EVOLUTION_RUNS_QUEUE_PANE.maxWidth}
                  onToggle={() => setRunsQueueCollapsed((current) => !current)}
                  onPointerDown={handleRunsResizeStart}
                  onKeyDown={handleRunsResizeKeyDown}
                />
              )}
              queueCollapsed={runsQueueCollapsed}
              filteredRuns={filteredRuns}
              hasRuns={hasRuns}
              hasFilteredRuns={hasFilteredRuns}
              filteredRunsEmpty={filteredRunsEmpty}
              runHeaderMessage={runHeaderMessage}
              selectedRun={selectedRun}
              selectedRunIds={selectedRunIds}
              visibleDeletableRunCount={visibleDeletableRunIds.length}
              allVisibleDeletableRunsSelected={allVisibleDeletableRunsSelected}
              relatedLibraryItems={relatedLibraryItems}
              relatedPendingItems={relatedPendingItems}
              relatedProposalCount={relatedProposalCount}
              runLocked={runLocked}
              runRecordsFeedback={runRecordsFeedback}
              deleteRunRecordError={deleteRunRecordMutation.error?.message ?? ""}
              bulkDeleteRunRecordsError={bulkDeleteRunRecordsMutation.error?.message ?? ""}
              bulkDeleteRunRecordsPending={bulkDeleteRunRecordsMutation.isPending}
              deleteRunRecordPending={deleteRunRecordMutation.isPending}
              actionFeedback={actionFeedback}
              actionError={actionMutation.error?.message ?? ""}
              actionPending={actionMutation.isPending}
              libraryFeedback={libraryFeedback}
              deleteProposalError={deleteProposalMutation.error?.message ?? ""}
              deleteProposalPending={deleteProposalMutation.isPending}
              onSelectVisibleRunRecords={selectVisibleRunRecords}
              onClearRunSelection={() => setSelectedRunIds([])}
              onBulkDeleteRunRecords={triggerBulkRunRecordDelete}
              onReturnToOverview={() => goToSupervisedView("live")}
              onShowAllRuns={() => setRunFilter("all")}
              onSelectRun={setSelectedRunId}
              onToggleRunSelection={toggleRunSelection}
              onRunAction={triggerRunAction}
              onOpenProposal={openProposalFromRun}
              onDeleteProposal={triggerProposalDelete}
              onDeleteRunRecord={triggerRunRecordDelete}
            />
          </Suspense>
        </div>
      ) : null}

      {activeTrack === "supervised" && evolutionView === "library" ? (
        <div className={`${styles.viewStack} ${styles.libraryViewStack}`}>
          <div className={styles.librarySummaryBar}>
            <section className={`${styles.surface} ${styles.summarySurface}`}>
              <div className={styles.surfaceHeaderCompact}>
                <div>
                  <p className={styles.eyebrow}>{t("recentLibraryAdditions")}</p>
                  <h2 className={styles.sectionTitle}>{t("library")}</h2>
                </div>
                <div className={styles.filterSegmented}>
                  {(["items", "pending"] as const).map((view) => (
                    <VButton
                      key={view}
                      type="button"
                      className={
                        libraryView === view
                          ? `${styles.filterButton} ${styles.filterButtonActive}`
                          : styles.filterButton
                      }
                      onClick={() => setLibraryView(view)}
                    >
                      {view === "items" ? t("libraryItems") : t("pendingReview")}
                    </VButton>
                  ))}
                </div>
              </div>
              <div className={styles.summaryMetricStrip}>
                <article className={styles.stripItem}>
                  <span>{t("libraryItems")}</span>
                  <strong>{libraryItems.length}</strong>
                </article>
                <article className={styles.stripItem}>
                  <span>{t("pendingReview")}</span>
                  <strong>{pendingItems.length}</strong>
                </article>
                <article className={styles.stripItem}>
                  <span>{t("intakeMode")}</span>
                  <strong>{intakeModeLabel(currentIntakeMode)}</strong>
                </article>
                <article className={styles.stripItem}>
                  <span>{t("selectedCount")}</span>
                  <strong>{selectedProposalRunIds.length}</strong>
                </article>
              </div>
              <p className={styles.noticeText}>{t("batchDeleteHint")}</p>
            </section>

            <section className={`${styles.surface} ${styles.summarySurface}`}>
              <div className={styles.surfaceHeaderCompact}>
                <div>
                  <p className={styles.eyebrow}>{t("selectedCount")}</p>
                  <h2 className={styles.sectionTitle}>
                    {libraryView === "items" ? t("libraryItems") : t("pendingReview")}
                  </h2>
                </div>
                <span className={styles.secondaryPill}>{selectedProposalRunIds.length}</span>
              </div>
              <p className={styles.statusLead}>{libraryHeaderMessage}</p>
              <div className={styles.statusMetricGrid}>
                <article className={styles.metricTile}>
                  <span>{t("filterResults")}</span>
                  <strong>{`${visibleLibraryEntries.length} / ${currentLibraryEntries.length}`}</strong>
                </article>
                <article className={styles.metricTile}>
                  <span>{t("selectedCount")}</span>
                  <strong>{selectedProposalRunIds.length}</strong>
                </article>
                <article className={styles.metricTile}>
                  <span>{t("deletionAllowed")}</span>
                  <strong>{libraryDeletableCount}</strong>
                </article>
                <article className={styles.metricTile}>
                  <span>{t("deletionBlocked")}</span>
                  <strong>{libraryBlockedCount}</strong>
                </article>
              </div>
              {hasLibraryFilters ? (
                <div className={styles.actionRow}>
                  <VButton
                    type="button"
                    className={styles.inlineAction}
                    onClick={clearLibraryFilters}
                  >
                    {t("clearFilters")}
                  </VButton>
                </div>
              ) : null}
            </section>

            <section className={`${styles.surface} ${styles.summarySurface}`}>
              <div className={styles.surfaceHeaderCompact}>
                <div>
                  <p className={styles.eyebrow}>{t("proposalStatus")}</p>
                  <h2 className={styles.sectionTitle}>
                    {selectedProposalSummary?.title
                      || (libraryView === "items" ? t("libraryItems") : t("pendingReview"))}
                  </h2>
                </div>
                <span className={selectedProposalSummary ? styles.statusPill : styles.secondaryPill}>
                  {selectedProposalSummary
                    ? selectedProposalSummary.outcomeSemantics.proposalStatusLabel
                    : intakeModeLabel(currentIntakeMode)}
                </span>
              </div>
              <p className={styles.statusLead}>
                {selectedProposalSummary
                  ? (selectedProposalSummary.summary || selectedProposalSummary.reason || selectedProposalSummary.headline)
                  : libraryHeaderMessage}
              </p>
              <div className={styles.relatedList}>
                <article className={styles.relatedRow}>
                  <strong>{t("latestRun")}</strong>
                  <span>{selectedProposalDisplaySourceRun || latestRun?.id || "--"}</span>
                </article>
                <article className={styles.relatedRow}>
                  <strong>{t("intakeMode")}</strong>
                  <span>{intakeModeLabel(currentIntakeMode)}</span>
                </article>
              </div>
              {selectedProposalSummary && selectedProposalCanOpenSourceRun ? (
                <div className={styles.actionRow}>
                  <VButton
                    type="button"
                    className={styles.inlineAction}
                    onClick={() => openRun(selectedProposalSummary.sourceRun)}
                  >
                    <ArrowUpRight size={15} />
                    {t("openSourceRun")}
                  </VButton>
                </div>
              ) : null}
            </section>
          </div>

          <div className={styles.masterDetail} style={libraryWorkspaceStyle}>
            <VSurface
              as="section"
              className={
                libraryListCollapsed
                  ? `${styles.surface} ${styles.listPanel} ${styles.paneCollapsed}`
                  : `${styles.surface} ${styles.listPanel}`
              }
              aria-hidden={libraryListCollapsed}
              elevation="panel"
              padding="none"
              tone="rail"
            >
              <>
                <div className={styles.bulkToolbar}>
                  <div className={styles.bulkToolbarText}>
                    <strong>{t("selectedCount")}</strong>
                    <span>{selectedProposalRunIds.length}</span>
                  </div>
                  <div className={styles.actionRow}>
                    <VButton
                      type="button"
                      className={styles.inlineAction}
                      isDisabled={selectedProposalRunIds.length === 0}
                      onClick={() => setSelectedProposalRunIds([])}
                    >
                      {t("clearSelection")}
                    </VButton>
                    <VButton
                      type="button"
                      variant="danger"
                      className={styles.inlineAction}
                      isDisabled={selectedProposalRunIds.length === 0 || bulkDeleteMutation.isPending}
                      onClick={triggerBulkDelete}
                    >
                      <Trash2 size={15} />
                      {t("deleteSelected")}
                    </VButton>
                  </div>
                </div>
                <div className={styles.libraryFilters}>
                  <div className={styles.filterRow}>
                    <label className={styles.filterField}>
                      <span>{t("proposalTarget")}</span>
                      <VInput
                        type="text"
                        className={styles.textInput}
                        value={librarySearchInput}
                        placeholder={t("proposalSearchPlaceholder")}
                        onChange={(event) => setLibrarySearchInput(event.target.value)}
                      />
                    </label>
                    <div className={styles.filterField}>
                      <span>{t("filterByStatus")}</span>
                      <VStringSelect
                        ariaLabel={t("filterByStatus")}
                        className={styles.selectInput}
                        value={libraryStatusFilter}
                        options={LIBRARY_STATUS_FILTERS.map((status) => ({
                          value: status,
                          label: status === "all" ? t("filterAll") : statusLabel(status),
                        }))}
                        onValueChange={(value) => setLibraryStatusFilter(value as LibraryStatusFilter)}
                      />
                    </div>
                    <div className={styles.filterField}>
                      <span>{t("filterByDeleteState")}</span>
                      <VStringSelect
                        ariaLabel={t("filterByDeleteState")}
                        className={styles.selectInput}
                        value={libraryDeleteFilter}
                        options={[
                          { value: "all", label: t("filterAll") },
                          { value: "deletable", label: t("filterDeletableOnly") },
                          { value: "blocked", label: t("filterBlockedOnly") },
                        ]}
                        onValueChange={(value) => setLibraryDeleteFilter(value as LibraryDeleteFilter)}
                      />
                    </div>
                  </div>
                  <div className={styles.filterMeta}>
                    <div className={styles.selectionSummary}>
                      <span>{t("filterResults")}</span>
                      <strong>{visibleLibraryEntries.length} / {currentLibraryEntries.length}</strong>
                    </div>
                    {hasLibraryFilters ? (
                      <VButton
                        type="button"
                        className={styles.inlineAction}
                        onClick={clearLibraryFilters}
                      >
                        {t("clearFilters")}
                      </VButton>
                    ) : null}
                  </div>
                </div>
                {libraryFeedback ? <p className={styles.feedbackText}>{libraryFeedback}</p> : null}
                {bulkDeleteMutation.error ? <p className={styles.errorText}>{bulkDeleteMutation.error.message}</p> : null}
                {libraryView === "items"
                ? libraryItems.length === 0
                  ? <VStateSurface className={styles.emptyState} title={t("emptyLibraryItems")} tone="empty" />
                  : filteredLibraryItems.length === 0
                    ? <VStateSurface className={styles.emptyState} title={t("noProposalMatches")} tone="empty" />
                    : filteredLibraryItems.map((item) => (
                      <article
                        key={item.id}
                        className={
                          selectedLibraryItem?.id === item.id
                            ? `${styles.proposalCard} ${styles.runItemActive}`
                            : styles.proposalCard
                        }
                      >
                        <div className={styles.selectionBar}>
                          <VCheckbox
                            className={styles.batchToggle}
                            isDisabled={!item.canDelete}
                            isSelected={proposalSelected(item.sourceRun)}
                            onChange={() => toggleProposalSelection(item)}
                          >
                            {t("selectForBatchDelete")}
                          </VCheckbox>
                          <span className={item.canDelete ? styles.secondaryPill : styles.statusPill}>
                            {item.canDelete ? t("deletionAllowed") : t("deletionBlocked")}
                          </span>
                        </div>
                        <VButton
                          type="button"
                          contentLayout="plain"
                          className={styles.proposalCardButton}
                          onClick={() => setSelectedLibraryItemId(item.id)}
                        >
                          <div className={styles.listRowTop}>
                            <strong>{item.title}</strong>
                            <span className={styles.secondaryPill}>{item.outcomeSemantics.proposalStatusLabel}</span>
                          </div>
                          <div className={styles.metaRow}>
                            <span>{displayDecisionLabel(item.decision)}</span>
                            <span>{proposalDisplaySourceRun(item)}</span>
                          </div>
                          <p className={styles.cardHeadline}>{item.changeSummary || item.headline}</p>
                          <p>{item.summary}</p>
                          <div className={styles.cardFooter}>
                            <span>{item.targetLabel || item.targetKey || "--"}</span>
                            <span>{compactTimestamp(item.updatedAt)}</span>
                          </div>
                        </VButton>
                      </article>
                    ))
                : pendingItems.length === 0
                  ? <VStateSurface className={styles.emptyState} title={t("emptyPendingItems")} tone="empty" />
                  : filteredPendingItems.length === 0
                    ? <VStateSurface className={styles.emptyState} title={t("noProposalMatches")} tone="empty" />
                    : filteredPendingItems.map((item) => (
                      <article
                        key={item.id}
                        className={
                          selectedPendingItem?.id === item.id
                            ? `${styles.proposalCard} ${styles.runItemActive}`
                            : styles.proposalCard
                        }
                      >
                        <div className={styles.selectionBar}>
                          <VCheckbox
                            className={styles.batchToggle}
                            isDisabled={!item.canDelete}
                            isSelected={proposalSelected(item.sourceRun)}
                            onChange={() => toggleProposalSelection(item)}
                          >
                            {t("selectForBatchDelete")}
                          </VCheckbox>
                          <span className={item.canDelete ? styles.secondaryPill : styles.statusPill}>
                            {item.canDelete ? t("deletionAllowed") : t("deletionBlocked")}
                          </span>
                        </div>
                        <VButton
                          type="button"
                          contentLayout="plain"
                          className={styles.proposalCardButton}
                          onClick={() => setSelectedPendingItemId(item.id)}
                        >
                          <div className={styles.listRowTop}>
                            <strong>{item.title}</strong>
                            <span className={styles.secondaryPill}>{item.outcomeSemantics.proposalStatusLabel}</span>
                          </div>
                          <div className={styles.metaRow}>
                            <span>{displayDecisionLabel(item.decision)}</span>
                            <span>{proposalDisplaySourceRun(item)}</span>
                          </div>
                          <p className={styles.cardHeadline}>{item.changeSummary || item.headline}</p>
                          <p>{item.reason || item.summary}</p>
                          <div className={styles.cardFooter}>
                            <span>{item.targetLabel || item.targetKey || "--"}</span>
                            <span>{compactTimestamp(item.updatedAt)}</span>
                          </div>
                        </VButton>
                      </article>
                    ))}
              </>
            </VSurface>

            <PaneCollapseHandle
              side="left"
              collapsed={libraryListCollapsed}
              separatorLabel={resizeLibraryListLabel}
              collapseLabel={lang === "zh" ? "收起提案列表" : "Collapse proposal list"}
              expandLabel={lang === "zh" ? "展开提案列表" : "Expand proposal list"}
              className={styles.resizeHandle}
              active={evolutionDraggingPaneId === "library-list"}
              valueNow={libraryListWidth}
              valueMin={EVOLUTION_LIBRARY_LIST_PANE.minWidth}
              valueMax={EVOLUTION_LIBRARY_LIST_PANE.maxWidth}
              onToggle={() => setLibraryListCollapsed((current) => !current)}
              onPointerDown={handleLibraryResizeStart}
              onKeyDown={handleLibraryResizeKeyDown}
            />

            <VSurface
              as="section"
              className={`${styles.surface} ${styles.detailPanel}`}
              elevation="panel"
              padding="none"
              tone="panel"
            >
              {selectedProposalSummary ? (
                selectedProposalIsSelfCandidate ? (
                  renderSelfEvolutionCandidateDetail(selectedProposalSummary)
                ) : proposalDetailQuery.data ? (
                  <>
                    <div className={styles.detailHeader}>
                      <div>
                        <p className={styles.eyebrow}>
                          {libraryView === "items" ? t("libraryItems") : t("pendingReview")}
                        </p>
                        <h2 className={styles.detailTitle}>{proposalDetailQuery.data.title}</h2>
                      </div>
                      <span className={styles.statusPill}>
                        {proposalDetailQuery.data.outcomeSemantics.proposalStatusLabel}
                      </span>
                    </div>

                    <div className={styles.detailSection}>
                      <h3>{t("reviewHeadline")}</h3>
                      <p className={styles.reviewLead}>{proposalDetailQuery.data.review.headline}</p>
                      <p>{proposalDetailQuery.data.review.changeSummary}</p>
                    </div>

                    <div className={styles.detailSection}>
                      <div className={styles.sectionHeadingRow}>
                        <h3>{t("editProposalTitle")}</h3>
                        {proposalEditOpen ? (
                          <div className={styles.actionRow}>
                            <VButton
                              type="button"
                              className={styles.inlineAction}
                              isDisabled={updateProposalMutation.isPending}
                              onClick={() => cancelProposalEdit(proposalDetailQuery.data)}
                            >
                              <X size={15} />
                              {t("cancelEdit")}
                            </VButton>
                            <VButton
                              type="button"
                              variant="primary"
                              className={styles.inlineAction}
                              isDisabled={!proposalDetailQuery.data.canEdit || updateProposalMutation.isPending}
                              onClick={() => triggerProposalUpdate(proposalDetailQuery.data.sourceRun)}
                            >
                              <Save size={15} />
                              {updateProposalMutation.isPending ? t("saving") : t("saveProposalEdit")}
                            </VButton>
                          </div>
                        ) : (
                          <VButton
                            type="button"
                            className={styles.inlineAction}
                            isDisabled={!proposalDetailQuery.data.canEdit}
                            onClick={() => beginProposalEdit(proposalDetailQuery.data)}
                          >
                            <Pencil size={15} />
                            {t("editProposal")}
                          </VButton>
                        )}
                      </div>
                      {!proposalDetailQuery.data.canEdit ? (
                        <p className={styles.noticeText}>{proposalDetailQuery.data.editBlockReason || t("proposalEditLocked")}</p>
                      ) : null}
                      {proposalDetailQuery.data.proposal.editedAt ? (
                        <p className={styles.noticeText}>
                          {t("proposalEditedAt")}: {compactTimestamp(proposalDetailQuery.data.proposal.editedAt)}
                        </p>
                      ) : null}
                      {proposalEditOpen ? (
                        <div className={styles.proposalEditGrid}>
                          <label className={styles.formField}>
                            <span>{t("proposalImprovementType")}</span>
                            <VInput
                              className={styles.textInput}
                              value={proposalEditDraft.improvementType}
                              onChange={(event) => updateProposalEditDraft("improvementType", event.target.value)}
                            />
                          </label>
                          <label className={styles.formField}>
                            <span>{t("proposalExpectedEffect")}</span>
                            <VTextarea
                              className={styles.textArea}
                              rows={3}
                              value={proposalEditDraft.expectedEffect}
                              onChange={(event) => updateProposalEditDraft("expectedEffect", event.target.value)}
                            />
                          </label>
                          <label className={styles.formField}>
                            <span>{t("proposalDraftSummary")}</span>
                            <VTextarea
                              className={styles.textArea}
                              rows={3}
                              value={proposalEditDraft.summary}
                              onChange={(event) => updateProposalEditDraft("summary", event.target.value)}
                            />
                          </label>
                          <label className={styles.formField}>
                            <span>{t("proposalCandidatePrompt")}</span>
                            <VTextarea
                              className={styles.textArea}
                              rows={6}
                              value={proposalEditDraft.candidatePrompt}
                              onChange={(event) => updateProposalEditDraft("candidatePrompt", event.target.value)}
                            />
                          </label>
                          <label className={styles.formField}>
                            <span>{t("proposalBaselinePrompt")}</span>
                            <VTextarea
                              className={styles.textArea}
                              rows={5}
                              value={proposalEditDraft.baselinePrompt}
                              onChange={(event) => updateProposalEditDraft("baselinePrompt", event.target.value)}
                            />
                          </label>
                          <label className={styles.formField}>
                            <span>{t("proposalEditNote")}</span>
                            <VInput
                              className={styles.textInput}
                              value={proposalEditDraft.editNote}
                              onChange={(event) => updateProposalEditDraft("editNote", event.target.value)}
                            />
                          </label>
                        </div>
                      ) : (
                        <div className={styles.relatedList}>
                          <article className={styles.relatedRow}>
                            <strong>{t("proposalImprovementType")}</strong>
                            <span>{proposalDetailQuery.data.proposal.improvementType || "--"}</span>
                          </article>
                          <article className={styles.relatedRow}>
                            <strong>{t("proposalExpectedEffect")}</strong>
                            <span>{proposalDetailQuery.data.proposal.expectedEffect || "--"}</span>
                          </article>
                          <article className={styles.relatedRow}>
                            <strong>{t("proposalDraftSummary")}</strong>
                            <span>{proposalDetailQuery.data.proposal.summary || proposalDetailQuery.data.review.changeSummary || "--"}</span>
                          </article>
                        </div>
                      )}
                      {proposalEditFeedback ? <p className={styles.feedbackText}>{proposalEditFeedback}</p> : null}
                      {updateProposalMutation.error ? <p className={styles.errorText}>{updateProposalMutation.error.message}</p> : null}
                    </div>

                    <div className={styles.detailSection}>
                      <h3>{t("whatChangedTitle")}</h3>
                      {renderReviewList(proposalDetailQuery.data.review.whatChanged)}
                    </div>

                    <div className={styles.detailSection}>
                      <h3>{t("whyCreatedTitle")}</h3>
                      {renderReviewList(proposalDetailQuery.data.review.whyCreated)}
                    </div>

                    <div className={styles.detailSection}>
                      <h3>{t("currentStateTitle")}</h3>
                      {renderReviewList([
                        ...proposalDetailQuery.data.review.currentState,
                        proposalDetailQuery.data.review.nextAction,
                      ])}
                    </div>

                    <div className={styles.detailSection}>
                      <h3>{t("resultLayersTitle")}</h3>
                      <div className={styles.relatedList}>
                        <article className={styles.relatedRow}>
                          <strong>{t("sourceRun")}</strong>
                          <span>{proposalDetailQuery.data.sourceRun}</span>
                        </article>
                        <article className={styles.relatedRow}>
                          <strong>{t("proposalUpdatedAt")}</strong>
                          <span>{compactTimestamp(proposalDetailQuery.data.updatedAt)}</span>
                        </article>
                        <article className={styles.relatedRow}>
                          <strong>{t("runLayer")}</strong>
                          <span>{proposalDetailQuery.data.runSemantics.runStatusLabel}</span>
                        </article>
                        <article className={styles.relatedRow}>
                          <strong>{t("decision")}</strong>
                          <span>
                            {displayDecisionLabel(
                              proposalDetailQuery.data.outcomeSemantics.decision || proposalDetailQuery.data.decision,
                            )}
                          </span>
                        </article>
                        <article className={styles.relatedRow}>
                          <strong>{t("proposalLayer")}</strong>
                          <span>{proposalDetailQuery.data.outcomeSemantics.proposalStatusLabel}</span>
                        </article>
                        <article className={styles.relatedRow}>
                          <strong>{t("runtimeLayer")}</strong>
                          <span>{proposalDetailQuery.data.outcomeSemantics.runtimeEffectLabel}</span>
                        </article>
                        <article className={styles.relatedRow}>
                          <strong>{t("targetLabelTitle")}</strong>
                          <span>
                            {proposalDetailQuery.data.targetLabel
                              || proposalDetailQuery.data.targetKey
                              || "--"}
                          </span>
                        </article>
                        <article className={styles.relatedRow}>
                          <strong>{t("baselineScore")}</strong>
                          <span>{proposalDetailQuery.data.supervised.baselineScore}</span>
                        </article>
                        <article className={styles.relatedRow}>
                          <strong>{t("candidateScore")}</strong>
                          <span>{proposalDetailQuery.data.supervised.candidateScore}</span>
                        </article>
                        <article className={styles.relatedRow}>
                          <strong>{t("scoreDelta")}</strong>
                          <span>{proposalDetailQuery.data.supervised.deltaScore}</span>
                        </article>
                        <article className={styles.relatedRow}>
                          <strong>{t("riskLevel")}</strong>
                          <span>{riskLabel(proposalDetailQuery.data.supervised.riskLevel)}</span>
                        </article>
                      </div>
                      <VTooltip content={proposalDetailQuery.data.outcomeSemantics.runtimeExplanation} width="wide">
                        <p className={styles.noticeText} tabIndex={0}>
                          {displaySupervisedTechnicalText(
                            proposalDetailQuery.data.outcomeSemantics.runtimeExplanation,
                            proposalDetailQuery.data.decision,
                            lang,
                            decisionLabel,
                          )}
                        </p>
                      </VTooltip>
                      <VTooltip content={proposalDetailQuery.data.supervised.decisionReason} width="wide">
                        <p tabIndex={0}>
                          {displaySupervisedTechnicalText(
                            proposalDetailQuery.data.supervised.decisionReason,
                            proposalDetailQuery.data.decision,
                            lang,
                            decisionLabel,
                          )}
                        </p>
                      </VTooltip>
                      {proposalDetailQuery.data.supervised.riskReasons.length > 0 ? (
                        <VTooltip content={proposalDetailQuery.data.supervised.riskReasons.join(" / ")} width="wide">
                          <p tabIndex={0}>
                            {displaySupervisedTechnicalText(
                              proposalDetailQuery.data.supervised.riskReasons.join(" / "),
                              proposalDetailQuery.data.decision,
                              lang,
                              decisionLabel,
                            )}
                          </p>
                        </VTooltip>
                      ) : null}
                      {proposalDetailQuery.data.supervised.caseDiagnostics.length > 0 ? (
                        <div className={styles.relatedList}>
                          {proposalDetailQuery.data.supervised.caseDiagnostics.slice(0, 3).map((item) => (
                            <article key={item.caseId || item.summary} className={styles.relatedRow}>
                              <strong>{item.caseId || "--"}</strong>
                              <span>{item.summary}</span>
                              {item.caseType && item.caseType !== "static" ? <span>{item.caseType}</span> : null}
                              {compactCaseObject(item.expectedFinalState) ? (
                                <span>expected final: {compactCaseObject(item.expectedFinalState)}</span>
                              ) : null}
                              {compactCaseObject(item.expectedInfeasibleOutcome) ? (
                                <span>expected infeasible: {compactCaseObject(item.expectedInfeasibleOutcome)}</span>
                              ) : null}
                            </article>
                          ))}
                        </div>
                      ) : null}
                    </div>

                    <Suspense fallback={<p className={styles.noticeText}>{t("loading")}</p>}>
                      <EvolutionProposalActionBandsPanel
                        proposal={proposalDetailQuery.data}
                        labels={{ t, proposalActionLabel }}
                        runLocked={runLocked}
                        actionFeedback={actionFeedback}
                        actionError={actionMutation.error?.message ?? ""}
                        actionPending={actionMutation.isPending}
                        deleteProposalError={deleteProposalMutation.error?.message ?? ""}
                        deleteProposalPending={deleteProposalMutation.isPending}
                        onRunAction={triggerRunAction}
                        onDeleteProposal={triggerProposalDelete}
                      />
                    </Suspense>

                    <div className={styles.detailSection}>
                      <h3>{t("evidencePaths")}</h3>
                      <div className={styles.relatedList}>
                        {Object.entries(proposalDetailQuery.data.paths)
                          .filter(([, value]) => Boolean(value))
                          .map(([key, value]) => (
                            <article key={key} className={styles.relatedRow}>
                              <strong>{key}</strong>
                              <span className={styles.pathText}>{value}</span>
                            </article>
                          ))}
                      </div>
                    </div>

                    <div className={styles.detailSection}>
                      <h3>{t("navEvolution")}</h3>
                      <VButton
                        type="button"
                        className={styles.inlineAction}
                        onClick={() => openRun(proposalDetailQuery.data.sourceRun)}
                      >
                        <ArrowUpRight size={15} />
                        {t("openSourceRun")}
                      </VButton>
                    </div>

                    <div className={styles.detailSection}>
                      <div className={styles.rawBlockStack}>
                        {renderRawJson(t("rawProposalJson"), proposalDetailQuery.data.rawProposal)}
                        {renderRawJson(t("rawGymDecisionJson"), proposalDetailQuery.data.rawGymDecision)}
                        {renderRawJson(t("rawSupervisedDecisionJson"), proposalDetailQuery.data.rawSupervisedDecision)}
                      </div>
                    </div>
                  </>
                ) : proposalDetailQuery.error ? (
                  <VStateSurface className={styles.emptyState} title={proposalDetailQuery.error.message} tone="error" />
                ) : (
                  <VStateSurface className={styles.emptyState} title={t("loadingRunDetails")} tone="loading" />
                )
              ) : (
                <VStateSurface className={styles.emptyState} title={t("chooseProposalDetail")} tone="empty" />
              )}
            </VSurface>
          </div>
        </div>
      ) : null}
    </div>
  );
}
