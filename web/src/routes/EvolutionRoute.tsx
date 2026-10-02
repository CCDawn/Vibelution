import "../design/route-css/evolution.tailwind.css";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { lazy, Suspense, type CSSProperties, type KeyboardEvent, type PointerEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { fetchPublicConfig } from "../api/config";
import {
  fetchEvolutionProposalDetail,
  fetchEvolutionWorkbench,
  fetchEvolutionWorkspaceSnapshot,
  fetchSelfEvolutionWorkspaceSnapshot,
  fetchSelfObservationRun,
  EVOLUTION_WORKBENCH_POLL_INTERVAL_MS,
} from "../api/evolution";
import { queryKeys } from "../api/queryKeys";
import {
  EvolutionActiveRun,
  EvolutionActiveRunAgentBinding,
  EvolutionActiveRunStreamEvent,
  EvolutionActionState,
  EvolutionRunActionResponse,
  EvolutionWorkbench,
  EvolutionProposalBulkDeleteResponse,
  EvolutionProposalDeleteResponse,
  EvolutionProposalDetail,
  EvolutionProposalUpdateResponse,
  EvolutionLibraryEntry,
  EvolutionWorkspaceSnapshot,
  SupervisedWorktreeRun,
  SelfEvolutionAutonomousLoopRun,
  SelfEvolutionWorkspaceSnapshot,
  SelfObservationRun,
  SelfObservationRunStartRequest,
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
import { usePersistedPaneResize } from "../components/layout/usePersistedPaneResize";
import { paneWidthCssVar } from "../components/layout/paneCssVariables";
import { WORKBENCH_LAYOUT_IDS } from "../components/layout/workbenchLayoutIds";
import {
  VButton,
  VDialog,
  VMetricStrip,
  VSection,
  VSurface,
  VTabs,
  VTooltip,
  VTrackWorkbenchPage,
} from "../components/vui";
import { useAppI18n } from "../i18n/useAppI18n";
import { useShellStore } from "../store/shellStore";
import { SupervisedApprovalDecisionPanel } from "./SupervisedApprovalDecisionPanel";
import { EvolutionBaselinePromotionStrip } from "./evolution/EvolutionBaselinePromotionStrip";
import { useEvolutionProposalMutations } from "./evolution/useEvolutionProposalMutations";
import { useEvolutionRunMutations } from "./evolution/useEvolutionRunMutations";
import { useSupervisedRunDetail } from "./evolution/useSupervisedRunDetail";
import { SupervisedStepResult } from "./evolution/SupervisedStepResult";
import {
  activeSupervisedWorkflowStep,
  buildSupervisedStartPlaceholder,
  canOpenProposalSourceRun,
  clampScore,
  compactCaseObject,
  compactTimestamp,
  datasetBenchmarkDetail,
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
  supervisedDatasetLimitError,
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

import { getEffectiveIntakeMode, SupervisedWorkspaceControls } from "./SupervisedWorkspaceControls";
import { SupervisedConversationWorkspace, type EvolutionWorkspaceRunGroup } from "./SupervisedConversationWorkspace";
import { buildUnifiedEvolutionRuns, evolutionRunTimestamp, isEvolutionRunHistory, selectUnifiedEvolutionRun } from "./unifiedEvolutionRuns";
import { SupervisedAgentConversationPanel } from "./SupervisedAgentConversationPanel";
import { type SupervisedWorkspaceWorkflowStep } from "./SupervisedWorkspaceTabs";
import {
  EvolutionDatasetCatalogPanel,
  type EvolutionDatasetCatalogFilter,
} from "./EvolutionDatasetCatalogPanel";
import { EvolutionSupervisedLiveSetupPanel } from "./EvolutionSupervisedLiveSetupPanel";
import {
  EvolutionSupervisedWorkflowMembersPanel,
  type EvolutionSupervisedWorkflowStepView,
} from "./EvolutionSupervisedWorkflowMembersPanel";
import { EvolutionSupervisedLiveIoPanel } from "./EvolutionSupervisedLiveIoPanel";
import { EvolutionSupervisedRunsView } from "./EvolutionSupervisedRunsView";
import { EvolutionSupervisedLibraryView } from "./EvolutionSupervisedLibraryView";
import { EvolutionSupervisedConversationEvidencePanel } from "./EvolutionSupervisedConversationEvidencePanel";
import {
  buildSupervisedWorktreeLedgerSummary,
  isSelfEvolutionWorktreeRun,
  readRecentSupervisedWorktreeRunId,
  rememberRecentSupervisedWorktreeRunId,
  selectRecentSupervisedWorktreeRun,
  supervisedApprovalWorkflowStatus,
  supervisedRunSessionStorage,
  supervisedWorktreeLedgerApprovalLabel,
} from "./supervisedWorktreeReview";
import {
  isLiveSupervisedRunStatus,
  isSupervisedStartLocked,
  isSupervisedRuntimeActivationBusy,
  parseRunStreamSnapshot,
  selectRunSnapshotWithRunId,
  selectSupervisedRunMonitorSource,
  selectSupervisedRunStreamTarget,
  shouldIgnoreActiveRunSnapshot,
} from "./evolutionLiveRun";
import { supervisedDecisionLabel } from "./supervisedRunRecordLabel";
import { buildSupervisedRunControlSummary } from "./supervisedRunSummary";
import { buildSupervisedCaseTraceItems } from "./supervisedCaseTrace";
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

const SelfEvolutionConversationWorkspace = lazy(() =>
  import("./SelfEvolutionConversationWorkspace").then((module) => ({ default: module.SelfEvolutionConversationWorkspace })),
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
type EvolutionRouteTrack = "supervised" | "self";
type SupervisedRouteView = "live" | "runs" | "library";
type EvolutionRouteProps = {
  forcedTrack?: EvolutionRouteTrack;
  forcedView?: SupervisedRouteView;
};
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
const EVOLUTION_WIDTH_PANES: PaneSpec[] = [
  EVOLUTION_RUNS_QUEUE_PANE,
  EVOLUTION_LIBRARY_LIST_PANE,
];
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
  // Legacy URLs choose the initial track; the workspace can switch without leaving its conversation.
  const [workspaceTrack, setWorkspaceTrack] = useState<EvolutionRouteTrack>(forcedTrack ?? evolutionTrack);
  const [workspaceRunKeys, setWorkspaceRunKeys] = useState<Record<EvolutionRouteTrack, string | null>>({ supervised: null, self: null });
  const [selfPhaseSelections, setSelfPhaseSelections] = useState<Record<string, string>>({});
  const [selfRunFeedback, setSelfRunFeedback] = useState<Record<string, string>>({});
  const [selfDetailsOpen, setSelfDetailsOpen] = useState(false);
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
  const [selectedDatasetCatalogFilter, setSelectedDatasetCatalogFilter] = useState<EvolutionDatasetCatalogFilter>("runnable");
  const [datasetLimitInput, setDatasetLimitInput] = useState("");
  const datasetLimitInputRef = useRef<HTMLInputElement | null>(null);
  const [bundleNameInput, setBundleNameInput] = useState("");
  const [approvalMode, setApprovalMode] = useState<"human" | "agent">("human");
  const [supervisedMentalModelMode, setSupervisedMentalModelMode] = useState<SupervisedMentalModelMode>("follow");
  const [supervisedSelections, setSupervisedSelections] = useState<Record<string, { step: SupervisedWorkflowStepId | null; role: SupervisedMemberRole | null }>>({});
  const [supervisedSetupOpen, setSupervisedSetupOpen] = useState(false);
  const [supervisedConfirmation, setSupervisedConfirmation] = useState<{runId:string;action:string} | null>(null);
  const [supervisedDialog, setSupervisedDialog] = useState<"source" | "settings" | null>(null);
  const supervisedDraftRef = useRef<{
    sourceKind: "dataset" | "bundle"; datasetName: string; bundleName: string;
    limit: string; approval: "human" | "agent"; mental: SupervisedMentalModelMode;
  } | null>(null);
  const [liveActiveRun, setLiveActiveRun] = useState<EvolutionActiveRun | null>(null);
  const [recentSupervisedWorktreeRunId, setRecentSupervisedWorktreeRunId] = useState<string | null>(
    () => readRecentSupervisedWorktreeRunId(supervisedRunSessionStorage()),
  );
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
    registerSplitContainer: registerEvolutionContainer,
    paneVariablesStyle: evolutionPaneVariablesStyle,
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
  const [runsQueueCollapsed, setRunsQueueCollapsed] = useState(false);
  const [libraryListCollapsed, setLibraryListCollapsed] = useState(false);

  const configQuery = useQuery({
    queryKey: queryKeys.configPublic(),
    queryFn: () => fetchPublicConfig(),
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
  const activeTrack: EvolutionRouteTrack = (
    workspaceTrack === "self" && selfTrackEnabled
      ? "self"
      : supervisedTrackEnabled
        ? "supervised"
        : selfTrackEnabled
          ? "self"
          : "supervised"
  );
  const selfTrackQueriesEnabled = activeTrack === "self";
  const supervisedTrackQueriesEnabled = activeTrack === "supervised";

  function changeWorkspaceTrack(track: EvolutionRouteTrack) {
    const currentRun = activeTrack === "supervised" ? selectedSupervisedWorkspaceRun : selectedSelfWorkspaceRun;
    setWorkspaceRunKeys((keys) => ({ ...keys, [activeTrack]: keys[activeTrack] ?? currentRun?.key ?? null }));
    setWorkspaceTrack(track);
    setEvolutionTrack(track);
    if (forcedView && forcedView !== "live") navigate(track === "self" ? "/self-evolution" : "/supervised-evolution");
    else setEvolutionView("live");
  }

  const workspaceSnapshotQuery = useQuery({
    queryKey: queryKeys.evolutionWorkspaceSnapshot(),
    queryFn: ({ signal }) => fetchEvolutionWorkspaceSnapshot<EvolutionWorkspaceSnapshot>({ signal }),
    // R3: idle workspace — slower poll; fast only when an active run is present (see below after data).
    refetchInterval: (query) => {
      const snapshot = query.state.data as EvolutionWorkspaceSnapshot | undefined;
      const hasActiveRun = Boolean(
        snapshot?.activeRun?.runId
        || snapshot?.worktreeActiveRun?.runId,
      );
      return resolvePollingInterval(pageVisible, hasActiveRun ? 4_000 : 12_000);
    },
    refetchIntervalInBackground: false,
    enabled: supervisedTrackEnabled,
  });
  const workbenchCatalogQuery = useQuery({
    queryKey: queryKeys.evolutionWorkbench(),
    queryFn: ({ signal }) => fetchEvolutionWorkbench<EvolutionWorkbench>({ signal }),
    // workbench 全量载荷（含 dataset catalog）低频刷新；高频运行态来自 workspace-snapshot
    // 内嵌的无 catalog workbench 投影，run 启动等变更仍会即时失效本查询。
    refetchInterval: resolvePollingInterval(pageVisible, EVOLUTION_WORKBENCH_POLL_INTERVAL_MS),
    refetchIntervalInBackground: false,
    enabled: supervisedTrackQueriesEnabled,
  });
  const selfWorkspaceSnapshotQuery = useQuery({
    queryKey: queryKeys.evolutionSelfWorkspaceSnapshot(),
    queryFn: ({ signal }) => fetchSelfEvolutionWorkspaceSnapshot<SelfEvolutionWorkspaceSnapshot>({ signal }),
    refetchInterval: (query) => {
      const snapshot = query.state.data as SelfEvolutionWorkspaceSnapshot | undefined;
      const hasActiveRun = Boolean(
        snapshot?.worktreeActiveRun?.runId
        || snapshot?.observationActiveRun?.runId
        || snapshot?.autonomousActiveRun?.runId,
      );
      return resolvePollingInterval(pageVisible, hasActiveRun ? 4_000 : 30_000);
    },
    refetchIntervalInBackground: false,
    enabled: selfTrackEnabled,
  });
  const selectedSelfObservationRunQuery = useQuery({
    queryKey: queryKeys.evolutionSelfObservationRun(selectedSelfObservationRunId || "__none__"),
    queryFn: () =>
      fetchSelfObservationRun<SelfObservationRun>(selectedSelfObservationRunId),
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
    startSelfObservationMutation,
    selfObservationActionMutation,
    startSelfAutonomousLoopMutation,
    selfAutonomousLoopActionMutation,
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
      keepWorktree: true,
      approvalMode,
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
    selectSupervisedWorktreeRun: (runId) => {
      setWorkspaceRunKeys((keys) => ({ ...keys, supervised: `supervised:worktree:${runId}` }));
      setRecentSupervisedWorktreeRunId(runId);
      rememberRecentSupervisedWorktreeRunId(supervisedRunSessionStorage(), runId);
    },
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
  const selfWorkspaceSnapshot = selfWorkspaceSnapshotQuery.data;
  const activeSelfObservationRunId = selfWorkspaceSnapshot?.observationActiveRun?.runId ?? "";
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
      rememberRecentSupervisedWorktreeRunId(supervisedRunSessionStorage(), supervisedWorktreeLiveRunId);
    }
  }, [supervisedWorktreeLiveRunId]);
  const recentSupervisedWorktreeSummary = selectRecentSupervisedWorktreeRun(
    worktreeRuns,
    recentSupervisedWorktreeRunId,
  );
  const recentRunDetail = useSupervisedRunDetail(recentSupervisedWorktreeSummary);
  const recentSupervisedWorktreeRun = recentRunDetail.run;
  const selfWorktreeRun = selfWorkspaceSnapshot?.worktreeActiveRun ?? null;
  const selfObservationRun = selfWorkspaceSnapshot?.observationActiveRun
    ?? selectedSelfObservationRunQuery.data
    ?? null;
  const unifiedRuns = buildUnifiedEvolutionRuns({
    supervisedWorktreeRuns: worktreeRuns,
    supervisedActiveWorktreeRun: activeWorktreeRun,
    supervisedActiveRun: activeRunSnapshot ?? liveActiveRun,
    supervisedLatestRun: latestSupervisedRunSnapshot,
    selfSnapshot: selfWorkspaceSnapshot,
    observationRun: selfObservationRun,
  });
  const selectedSupervisedWorkspaceRun = selectUnifiedEvolutionRun(unifiedRuns, "supervised", workspaceRunKeys.supervised);
  const selectedSelfWorkspaceRun = selectUnifiedEvolutionRun(unifiedRuns, "self", workspaceRunKeys.self);
  const selectedSupervisedDetail = useSupervisedRunDetail(selectedSupervisedWorkspaceRun?.worktreeRun ?? null);
  const selectedSelfDetail = useSupervisedRunDetail(selectedSelfWorkspaceRun?.worktreeRun ?? null);
  const reviewCandidateWorktree = selectedSupervisedDetail.run;
  const reviewCandidateGate = reviewCandidateWorktree?.reviewGate ?? reviewCandidateWorktree?.mergeAnalysis?.reviewGate;
  const highlightedReviewPending = isSelfEvolutionWorktreeRun(reviewCandidateWorktree)
    && Boolean(reviewCandidateGate?.required)
    && String(reviewCandidateGate?.status || "").trim().toLowerCase() !== "approved";
  const selfOverview = selfWorkspaceSnapshot?.overview;
  const selfTransactions = selfWorkspaceSnapshot?.transactions ?? [];
  const selfAutonomousRun: SelfEvolutionAutonomousLoopRun | null =
    selfWorkspaceSnapshot?.autonomousActiveRun
    ?? selfWorkspaceSnapshot?.autonomousLatestRun
    ?? null;
  const selfTrackLoading = selfTrackQueriesEnabled
    && !selfOverview
    && selfWorkspaceSnapshotQuery.isLoading;
  const latestRun = runs[0] ?? null;
  const supervisedClosedLoopRecord: SupervisedClosedLoopRecord | null =
    workspaceSnapshot?.latestClosedLoopRecord
    ?? latestSupervisedRunSnapshot?.closedLoopRecord
    ?? null;
  const supervisedWorktreeLedgerSummary = buildSupervisedWorktreeLedgerSummary(recentSupervisedWorktreeRun);
  const showTrackToggle = selfTrackEnabled && supervisedTrackEnabled;
  const routeEyebrow = activeTrack === "self" ? t("navSelfEvolution") : t("navSupervisedEvolution");
  const routeTitle =
    activeTrack === "self" ? t("selfEvolutionMode") : t("supervisedEvolutionMode");
  const routeSubtitle =
    activeTrack === "self" ? t("selfEvolutionSubtitle") : t("supervisedEvolutionSubtitle");
  const hideSupervisedToolbarIntro = activeTrack === "supervised";
  const showRouteToolbar = activeTrack !== "self" && evolutionView !== "live";
  const currentIntakeMode = getEffectiveIntakeMode(overview?.intakeMode, configQuery.data?.intakeMode);
  const overviewCurrentStatus = overview?.currentStatus ?? null;
  const overviewRecentRuns = overview?.recentRuns ?? [];
  const overviewLatestRunId = recentSupervisedWorktreeRun?.runId || overviewCurrentStatus?.latestRunId || overviewRecentRuns[0]?.id || latestRun?.id || "";
  const effectiveActiveRunSnapshot = shouldIgnoreActiveRunSnapshot(activeRunSnapshot, liveActiveRun)
    ? null
    : activeRunSnapshot;
  const monitoredRun = selectedSupervisedWorkspaceRun?.activeRun ?? null;
  const supervisedRunMonitorSource = selectSupervisedRunMonitorSource({
    worktreeRun: selectedSupervisedDetail.run,
    activeRun: monitoredRun,
    liveRun: null,
  });
  const monitoredWorktreeRun = supervisedRunMonitorSource?.kind === "worktree"
    ? supervisedRunMonitorSource.run
    : null;
  const supervisedWorkflowRun = selectedSupervisedDetail.run ?? monitoredRun;
  const supervisedMembersRun = monitoredRun && (
    !supervisedWorkflowRun || monitoredRun.runId === supervisedWorkflowRun.runId
  )
    ? monitoredRun
    : null;
  const supervisedMembersUseRunBindings = hasSupervisedAgentBindings(supervisedWorkflowRun?.agentBindings);
  const supervisedMembersBindings = supervisedMembersUseRunBindings
    ? supervisedWorkflowRun?.agentBindings ?? EMPTY_AGENT_BINDINGS
    : supervisedWorkflowRun ? EMPTY_AGENT_BINDINGS : currentSupervisedAgentBindings;
  const supervisedMembersSource = supervisedWorkflowRun ? "run" : "current_config";
  const runningRun = effectiveActiveRunSnapshot ?? (liveActiveRun && isLiveSupervisedRunStatus(liveActiveRun.status)
    ? liveActiveRun
    : null);
  const runLocked = Boolean(runningRun && isLiveSupervisedRunStatus(runningRun.status));
  const worktreeRunLocked = Boolean(
    (activeWorktreeRun ?? selfWorktreeRun)
    && ["queued", "running", "paused", "stopping"].includes(String((activeWorktreeRun ?? selfWorktreeRun)?.status || "").toLowerCase()),
  );
  const supervisedStartSubmitting = startWorktreeRunMutation.isPending || isLocalSupervisedStartPlaceholder(liveActiveRun);
  const activationLocked = isSupervisedRuntimeActivationBusy(
    activeWorktreeRun?.runtimeActivation?.status
    ?? selfWorktreeRun?.runtimeActivation?.status,
  );
  const startLocked = isSupervisedStartLocked({
    liveStatus: runningRun?.status,
    worktreeStatus: (activeWorktreeRun ?? selfWorktreeRun)?.status,
    activationStatus: activeWorktreeRun?.runtimeActivation?.status
      ?? selfWorktreeRun?.runtimeActivation?.status,
    submitting: supervisedStartSubmitting,
  });
  const supervisedPrimaryRunning = runLocked || worktreeRunLocked || activationLocked;
  const supervisedStartButtonLabel = supervisedStartSubmitting
    ? (lang === "zh" ? "提交中" : "Submitting")
    : activationLocked
      ? (lang === "zh" ? "激活中" : "Activating")
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
  const monitoredPreflightIssue = supervisedPreflightIssue(monitoredRun, lang);
  const worktreeRunStopping = String(supervisedWorktreeLiveRun?.status || "").trim().toLowerCase() === "stopping";
  const monitoredRunIdentity = monitoredWorktreeRun?.runId || monitoredRun?.sessionId || monitoredRun?.runId || "";
  const monitoredCaseLabel = monitoredRun?.currentCaseId
    ? `${monitoredRun.currentCaseIndex ?? "--"}/${monitoredRun.caseTotal ?? "--"} ${monitoredRun.currentCaseId}`
    : "--";
  const monitoredTaskLabel = monitoredRun?.currentTask || monitoredRun?.latestMessage || "--";
  const monitoredWorktreeDecision = String(
    monitoredWorktreeRun?.decision?.judgeDecision
    || monitoredWorktreeRun?.candidateJudgment?.decision
    || "",
  );
  const monitoredStatusLabel = monitoredWorktreeDecision === "INCONCLUSIVE"
    ? displayDecisionLabel(monitoredWorktreeDecision)
    : monitoredRun?.decision === "INCONCLUSIVE"
      ? displayDecisionLabel(monitoredRun.decision)
      : statusLabel(monitoredWorktreeRun?.status || monitoredRun?.status || "");
  const supervisedMemberReturnTo = `${location.pathname}${location.search}` || "/supervised-evolution";
  const supervisedMemberReturnLabel = lang === "zh" ? "返回监督进化" : "Back to supervised evolution";
  const supervisedMembersRunIdentity = supervisedWorkflowRun?.runId || monitoredRun?.sessionId || "";
  const selectedSupervisedWorkflowStepId = supervisedSelections[supervisedMembersRunIdentity]?.step ?? null;
  const selectedSupervisedAgentRole = supervisedSelections[supervisedMembersRunIdentity]?.role ?? null;
  const setSelectedSupervisedWorkflowStepId = useCallback((step: SupervisedWorkflowStepId | null) => {
    setSupervisedSelections((current) => ({ ...current, [supervisedMembersRunIdentity]: { role: current[supervisedMembersRunIdentity]?.role ?? null, step } }));
  }, [supervisedMembersRunIdentity]);
  const setSelectedSupervisedAgentRole = useCallback((role: SupervisedMemberRole | null) => {
    setSupervisedSelections((current) => ({ ...current, [supervisedMembersRunIdentity]: { step: current[supervisedMembersRunIdentity]?.step ?? null, role } }));
  }, [supervisedMembersRunIdentity]);
  const backendWorkflowSteps = supervisedWorkflowRun?.workflowSteps ?? [];
  const backendWorkflowCurrent = backendWorkflowSteps.find((step) => step.current);
  const supervisedRunMembers = useMemo<SupervisedRunMember[]>(() => {
    const bindings = supervisedMembersBindings;
    const roleSessions = supervisedMembersRun?.roleConversationSessions ?? {};
    const currentRole = String(supervisedMembersRun?.currentRole || backendWorkflowCurrent?.role || "").trim().toLowerCase();
    const currentAgentId = String(supervisedMembersRun?.currentAgentBinding?.agentId || "").trim();
    return SUPERVISED_RUN_MEMBER_ROLES.map((role) => {
      const binding = bindings[role === "baseline_rerun" ? "baseline" : role] ?? {};
      const conversationSession = roleSessions[role]
        ?? supervisedRoleConversationSession(backendWorkflowSteps, role);
      const conversationSessionId = String(conversationSession?.conversationSessionId || "").trim();
      const agentId = String(binding.agentId || "").trim();
      const roleText = String(binding.roleLabel || "").trim() || runRoleLabel(role);
      const displayName = String(binding.displayName || binding.agentCode || agentId || "").trim();
      const modelId = supervisedMemberModelId(binding);
      const isActive =
        currentRole === role
        || (!currentRole && Boolean(currentAgentId) && Boolean(agentId) && currentAgentId === agentId);
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
    const fallbackSessionId = member?.conversationSession?.conversationSessionId || "";
    const conversationSessionId = String(backendStep?.conversationSessionId || fallbackSessionId || "").trim();
    const chatRoute = backendStep?.chatRoute || supervisedMemberChatRoute(conversationSessionId, supervisedMemberReturnTo, supervisedMemberReturnLabel);
    const fallbackStatus = definition.id === supervisedRuntimeWorkflowStepId ? "running" : "pending";
    const backendStatus = backendStep?.status || fallbackStatus;
    return {
      id: definition.id,
      label: backendStep?.label || supervisedWorkflowStepLabel(definition, lang),
      ownerKind: backendStep?.ownerKind || (definition.role ? "agent" : "human"),
      role: backendStep?.role ?? definition.role,
      status: definition.id === "approval"
        ? supervisedApprovalWorkflowStatus(reviewCandidateWorktree, backendStatus)
        : backendStatus,
      current: backendStep?.current ?? definition.id === supervisedRuntimeWorkflowStepId,
      summary: backendStep?.summary || (
        definition.id === "approval"
          ? (lang === "zh" ? "Judge 复评结论与用户审批合入动作集中在这里。" : "The final Judge decision and user-approved merge are gathered here.")
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
  const selectedWorkflowRole = SUPERVISED_RUN_MEMBER_ROLES.includes(supervisedSelectedWorkflowStep.role as SupervisedMemberRole)
    ? supervisedSelectedWorkflowStep.role as SupervisedMemberRole : null;
  const supervisedSelectedAgentRole: SupervisedMemberRole = selectedSupervisedAgentRole
    && supervisedRunMemberByRole.has(selectedSupervisedAgentRole)
    ? selectedSupervisedAgentRole
    : selectedWorkflowRole
      ?? (supervisedSelectedWorkflowStep.id === "approval"
        ? (supervisedRunMemberByRole.get("reviewer")?.conversationSession?.conversationSessionId ? "reviewer" : "judge")
        : supervisedActiveAgentRole)
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
    (supervisedSelectedWorkflowStep.role === supervisedSelectedAgentRole ? supervisedSelectedWorkflowStep : undefined)
    ?? supervisedSelectedAgentWorkflowSteps.find((step) => step.current)
    ?? [...supervisedSelectedAgentWorkflowSteps].reverse().find((step) => step.conversationMessages?.length)
    ?? supervisedSelectedAgentWorkflowSteps[0];
  const supervisedSelectedAgentFallbackMessages =
    !supervisedWorkflowManualSelection && supervisedSelectedAgentRole === normalizedSupervisedRuntimeRole && monitoredCaseConversationMessages.length > 0
      ? monitoredCaseConversationMessages
      : supervisedSelectedAgentWorkflowStep?.conversationMessages ?? [];
  const supervisedSelectedAgentTaskSummary =
    supervisedSelectedAgentMember?.conversationSession?.latestMessage
    || supervisedSelectedAgentWorkflowStep?.summary
    || supervisedSelectedAgentWorkflowStep?.livePreview
    || monitoredRun?.currentTask
    || "";
  const supervisedApprovalSelected = supervisedSelectedWorkflowStep.id === "approval";
  const selectedWorkflowIsRuntimeStep = supervisedSelectedWorkflowStep.id === supervisedRuntimeWorkflowStepId;
  const selectedWorkflowTaskSummary =
    supervisedSelectedWorkflowStep.summary
    || supervisedSelectedWorkflowStep.livePreview
    || monitoredRun?.currentCasePrompt
    || monitoredRun?.currentTask
    || "";
  const supervisedLiveConversationSupplement = supervisedSelectedWorkflowStep.id === "approval" ? null : (
    <EvolutionSupervisedConversationEvidencePanel
      showCasePrompt={selectedWorkflowIsRuntimeStep}
      casePromptTitle={t("currentCasePrompt")}
      casePrompt={monitoredRun?.currentCasePrompt}
      preflightIssue={monitoredPreflightIssue}
      caseTraceItems={monitoredCaseTraceItems}
      statusLabel={statusLabel}
      formatTimestamp={compactTimestamp}
      showLatestOutput={selectedWorkflowIsRuntimeStep}
      latestOutputTitle={currentCaseOutputLabel(monitoredRun)}
      latestOutput={monitoredRun?.currentCaseIo?.latestOutput}
    />
  );
  const supervisedClosedLoopDecisionLabel = supervisedClosedLoopRecord?.decision
    ? displayDecisionLabel(supervisedClosedLoopRecord.decision)
    : statusLabel(supervisedClosedLoopRecord?.status || "");
  const supervisedClosedLoopProposalCount = supervisedClosedLoopRecord ? supervisedClosedLoopRecord.evidence.proposalPaths.length : 0;
  const supervisedClosedLoopLineageLabel = supervisedClosedLoopRecord?.evidence.lineageIndexPath
    ? (lang === "zh" ? "已记录" : "Recorded")
    : "--";
  const supervisedWorkflowDecision = (() => {
    const decision = supervisedWorkflowRun?.decision;
    if (typeof decision === "string") {
      return decision;
    }
    if (decision && typeof decision === "object") {
      const judgeDecision = String(decision.judgeDecision || "");
      if (judgeDecision) {
        return judgeDecision;
      }
    }
    if (supervisedWorkflowRun && "candidateJudgment" in supervisedWorkflowRun) {
      return String(supervisedWorkflowRun.candidateJudgment?.decision || "");
    }
    return "";
  })();
  const supervisedMembersRunStatusLabel = supervisedWorkflowDecision === "INCONCLUSIVE"
    ? displayDecisionLabel(supervisedWorkflowDecision)
    : statusLabel(supervisedWorkflowRun?.status || "");
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
  const monitoredWorktreeWorkflowStep = monitoredWorktreeRun?.workflowSteps?.find((step) => step.current) ?? null;
  const monitoredWorktreeRole = monitoredWorktreeWorkflowStep?.role || "";
  const monitoredWorktreeSummary = monitoredWorktreeRun
    ? {
      status: monitoredWorktreeRun.status,
      decision: monitoredWorktreeDecision,
      tone: ["failed", "cancelled"].includes(String(monitoredWorktreeRun.status).toLowerCase())
        ? "danger" as const
        : String(monitoredWorktreeRun.status).toLowerCase() === "paused"
          ? "warning" as const
          : ["done"].includes(String(monitoredWorktreeRun.status).toLowerCase())
            ? "success" as const
            : "running" as const,
      headline: monitoredWorktreeRun.latestMessage
        || monitoredWorktreeWorkflowStep?.livePreview
        || monitoredWorktreeWorkflowStep?.summary
        || (lang === "zh" ? "监督工作流正在推进。" : "The supervised workflow is progressing."),
      reason: monitoredWorktreeWorkflowStep?.summary || "",
      nextAction: lang === "zh"
        ? "可继续查看当前 Agent 的会话和阶段状态。"
        : "Continue reviewing the current Agent session and workflow stage.",
    }
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
      detail: step.current
        ? (lang === "zh" ? "进行中" : "In progress")
        : statusLabel(step.status),
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
    improve: supervisedWorkflowTabSummary(supervisedWorkflowCards[2]),
    rerun_score: supervisedWorkflowTabSummary(supervisedWorkflowCards[4]),
    approval: supervisedWorkflowTabSummary(supervisedWorkflowCards[5]),
  };
  const supervisedWorkspaceActiveStepId: SupervisedWorkspaceWorkflowStep | null =
    supervisedSelectedWorkflowStepId === "baseline_eval" || supervisedSelectedWorkflowStepId === "baseline_judge"
      ? "baseline_eval"
      : supervisedSelectedWorkflowStepId === "improve"
        ? "improve"
        : supervisedSelectedWorkflowStepId === "rerun_eval" || supervisedSelectedWorkflowStepId === "rerun_judge"
          ? "rerun_score"
          : supervisedSelectedWorkflowStepId === "approval"
            ? "approval"
            : null;
  const handleSupervisedWorkflowStepSelect = useCallback((stepId: SupervisedWorkspaceWorkflowStep | SupervisedWorkflowStepId) => {
    const resolvedStepId = stepId === "rerun_score" ? "rerun_judge" : stepId;
    setSelectedSupervisedWorkflowStepId(resolvedStepId);
    const definition = SUPERVISED_WORKFLOW_STEPS.find((step) => step.id === resolvedStepId);
    if (definition?.role) {
      setSelectedSupervisedAgentRole(definition.role);
    } else {
      setSelectedSupervisedAgentRole(null);
    }
    if (evolutionView !== "live") {
      goToSupervisedView("live");
    }
  }, [evolutionView, setSelectedSupervisedWorkflowStepId, setSelectedSupervisedAgentRole]);
  const handleSupervisedAgentSelect = useCallback((role: SupervisedMemberRole) => {
    setSelectedSupervisedAgentRole(role);
    if (role === "baseline") {
      setSelectedSupervisedWorkflowStepId("baseline_eval");
    } else if (role === "baseline_rerun") {
      setSelectedSupervisedWorkflowStepId("rerun_eval");
    } else if (role === "judge") {
      setSelectedSupervisedWorkflowStepId(
        supervisedRuntimeWorkflowStepId === "baseline_judge" ? "baseline_judge" : "rerun_judge",
      );
    } else {
      setSelectedSupervisedWorkflowStepId(null);
    }
    if (evolutionView !== "live") {
      goToSupervisedView("live");
    }
  }, [evolutionView, supervisedRuntimeWorkflowStepId, setSelectedSupervisedWorkflowStepId, setSelectedSupervisedAgentRole]);
  const handleFollowSupervisedAgent = useCallback(() => {
    setSelectedSupervisedAgentRole(null);
    setSelectedSupervisedWorkflowStepId(null);
  }, [setSelectedSupervisedAgentRole, setSelectedSupervisedWorkflowStepId]);
  const terminateWorktreeAction = supervisedWorktreeLiveRun?.actionStates?.terminate;
  const terminateSupervisedAction = terminateWorktreeAction;
  const canTerminateSupervisedRun = Boolean(supervisedWorkflowRun?.runId === supervisedWorktreeLiveRun?.runId && terminateWorktreeAction?.enabled);
  const terminateSupervisedPending = approvalWorktreeActionMutation.isPending;
  const handleTerminateSupervisedRun = () => {
    if (supervisedWorktreeLiveRun) {
      approvalWorktreeActionMutation.mutate({ runId: supervisedWorktreeLiveRun.runId, action: "terminate" });
    }
  };
  const supervisedControlError =
    (approvalWorktreeActionMutation.variables?.runId === selectedSupervisedWorkspaceRun?.runId ? approvalWorktreeActionMutation.error?.message : "")
    || ((supervisedSetupOpen || !selectedSupervisedWorkspaceRun) ? startWorktreeRunMutation.error?.message : "")
    || "";
  const terminateSupervisedDisabledReason = disabledReason(terminateSupervisedAction);
  const supervisedActiveRunMonitorMetrics: EvolutionActiveRunMonitorMetric[] = monitoredWorktreeRun
    ? [
      {
        id: "run",
        label: t("activeRunSession"),
        value: monitoredRunIdentity,
        title: monitoredRunIdentity,
      },
      {
        id: "phase",
        label: t("activeRunPhase"),
        value: statusLabel(monitoredWorktreeRun.phase || monitoredWorktreeRun.status),
      },
      {
        id: "cases",
        label: t("activeRunCurrentCase"),
        value: `${monitoredWorktreeRun.costEstimate.caseCount} cases`,
      },
      {
        id: "role",
        label: t("activeRunCurrentRole"),
        value: monitoredWorktreeRole ? runRoleLabel(monitoredWorktreeRole) : "--",
      },
      {
        id: "result",
        label: t("activeRunResult"),
        value: monitoredWorktreeDecision ? displayDecisionLabel(monitoredWorktreeDecision) : "--",
      },
      {
        id: "updated",
        label: t("latestLiveMessage"),
        value: compactTimestamp(monitoredWorktreeRun.updatedAt),
      },
    ]
    : monitoredRun
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
  const supervisedActiveRunMonitorEvents: EvolutionActiveRunMonitorEventItem[] = monitoredWorktreeRun
    ? (monitoredWorktreeRun.workflowSteps ?? []).map((step) => ({
      key: `${monitoredWorktreeRun.runId}-${step.id}-${step.status}`,
      title: step.label,
      statusLabel: statusLabel(step.status),
      summary: step.livePreview || step.summary || "--",
      timestamp: compactTimestamp(monitoredWorktreeRun.updatedAt),
    }))
    : monitoredRun
    ? monitoredRun.eventTail.map((item) => ({
      key: `${item.timestamp}-${item.event}-${item.summary}`,
      title: formatRunEventTitle(item),
      statusLabel: statusLabel(item.status),
      summary: formatRunEventSummary(item),
      timestamp: compactTimestamp(item.timestamp),
    }))
    : [];
  const supervisedClosedLoopLedger: EvolutionActiveRunClosedLoopLedger | null = supervisedWorktreeLedgerSummary
    ? {
      eyebrow: lang === "zh" ? "闭环记录库" : "Closed-loop ledger",
      title: supervisedWorktreeLedgerSummary.runId,
      statusLabel: supervisedWorktreeLedgerSummary.decision
        ? displayDecisionLabel(supervisedWorktreeLedgerSummary.decision)
        : statusLabel(supervisedWorktreeLedgerSummary.status),
      statusTone: ["failed", "cancelled"].includes(supervisedWorktreeLedgerSummary.status.toLowerCase())
        ? "primary"
        : "secondary",
      description: supervisedWorktreeLedgerSummary.description || "--",
      evidence: [
        {
          id: "review",
          label: lang === "zh" ? "审批状态" : "Approval",
          value: supervisedWorktreeLedgerApprovalLabel(supervisedWorktreeLedgerSummary, lang),
        },
        {
          id: "sessions",
          label: lang === "zh" ? "Agent 会话" : "Agent sessions",
          value: supervisedWorktreeLedgerSummary.roleSessionCount,
        },
        {
          id: "candidate-score",
          label: lang === "zh" ? "候选得分" : "Candidate score",
          value: supervisedWorktreeLedgerSummary.candidateScore ?? "--",
        },
        {
          id: "bundle",
          label: lang === "zh" ? "评测包" : "Evaluation bundle",
          value: supervisedWorktreeLedgerSummary.bundleName || "--",
        },
      ],
      action: {
        label: lang === "zh" ? "查看审批" : "Review approval",
        title: supervisedWorktreeLedgerSummary.description,
        onClick: () => {
          setSelectedSupervisedWorkflowStepId("approval");
          setSelectedSupervisedAgentRole(null);
          goToSupervisedView("live");
        },
      },
    }
    : supervisedClosedLoopRecord
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
  const supervisedActiveRunMonitorRun: EvolutionActiveRunMonitorRunView | null = supervisedRunMonitorSource
    ? {
      termination: {
        disabled: !canTerminateSupervisedRun,
        pending: terminateSupervisedPending,
        title: terminateSupervisedDisabledReason || t("terminateSupervisedRun"),
        ariaLabel: t("terminateSupervisedRun"),
        onClick: handleTerminateSupervisedRun,
      },
      openSessionAction: monitoredRun?.sessionId
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
        status: monitoredWorktreeSummary?.status || monitoredRun?.status || "",
        decision: monitoredWorktreeSummary?.decision || monitoredRun?.decision,
        tone: monitoredWorktreeSummary?.tone || monitoredControlSummary?.tone,
        headline: monitoredWorktreeSummary?.headline || monitoredControlSummary?.headline || monitoredRun?.latestMessage || "",
        reason: monitoredWorktreeSummary?.reason || monitoredControlSummary?.reason,
        nextActionLabel: t("nextRecommendedAction"),
        nextAction: monitoredWorktreeSummary?.nextAction || monitoredControlSummary?.nextAction,
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
      value: supervisedWorktreeLedgerSummary?.candidateScore ?? (overviewRecentRuns[0] ? clampScore(overviewRecentRuns[0].score) : latestRun ? clampScore(latestRun.candidateScore) : "--"),
    },
    {
      id: "selected-dataset",
      label: t("selectedDataset"),
      value: workbenchState?.datasetName || "--",
    },
  ];
  const selfRunLocked = Boolean(
    (
      selfWorktreeRun
      && ["queued", "running", "paused", "stopping"].includes(String(selfWorktreeRun.status || "").trim().toLowerCase())
    )
    || (
      selfAutonomousRun
      && ["queued", "running"].includes(String(selfAutonomousRun.status || "").trim().toLowerCase())
    ),
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
  const hiddenDatasetCount = Math.max(0, datasetCatalog.length - primaryDatasets.length);
  const availableBundles = workbenchControl?.bundles ?? [];
  const selectedBundleExists = availableBundles.some((item) => item.name === bundleNameInput);
  const datasetLimitError = supervisedDatasetLimitError(sourceKind, datasetLimitInput);
  const supervisedStartDisabledReason = datasetLimitError || (startLocked
    ? (activationLocked ? t("supervisedActivationLockHint") : t("runningLockHint"))
    : !workbenchControl
      ? (lang === "zh" ? "监督运行控制暂不可用。" : "Supervised run controls are unavailable.")
      : sourceKind === "dataset" && !datasetName
        ? (lang === "zh" ? "先选择数据集。" : "Choose a dataset first.")
        : sourceKind === "bundle" && !selectedBundleExists
          ? (lang === "zh" ? "先选择有效的评测包。" : "Choose a valid evaluation bundle first.")
          : undefined);
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
      fetchEvolutionProposalDetail<EvolutionProposalDetail>(selectedProposalRunId ?? ""),
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
    setFormInitialized(true);
  }, [formInitialized, primaryDatasets, workbenchControl]);

  useEffect(() => {
    if (!formInitialized || !monitoredWorktreeRun) {
      return;
    }
    const activeSourceKind = monitoredWorktreeRun.sourceKind === "bundle" ? "bundle" : "dataset";
    if (sourceKind !== activeSourceKind) {
      setSourceKind(activeSourceKind);
    }
    if (datasetName !== monitoredWorktreeRun.datasetName) {
      setDatasetName(monitoredWorktreeRun.datasetName || "");
    }
    if (bundleNameInput !== monitoredWorktreeRun.bundleName) {
      setBundleNameInput(monitoredWorktreeRun.bundleName || "");
    }
    const activeDatasetLimit = toLimitInput(monitoredWorktreeRun.datasetLimit);
    if (datasetLimitInput !== activeDatasetLimit) {
      setDatasetLimitInput(activeDatasetLimit);
    }
  }, [
    bundleNameInput,
    datasetLimitInput,
    datasetName,
    formInitialized,
    monitoredWorktreeRun,
    sourceKind,
  ]);

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
    if (forcedTrack) setWorkspaceTrack(forcedTrack);
  }, [forcedTrack]);

  useEffect(() => {
    if (!forcedView && rawEvolutionView === "overview") {
      setEvolutionView("live");
    }
  }, [forcedView, rawEvolutionView, setEvolutionView]);

  useEffect(() => {
    if (selfGoalInitialized || !selfWorkspaceSnapshot?.overview?.goal) {
      return;
    }
    setSelfGoalInput(selfWorkspaceSnapshot.overview.goal);
    setSelfGoalInitialized(true);
  }, [selfGoalInitialized, selfWorkspaceSnapshot?.overview?.goal]);

  useEffect(() => {
    if (!pageVisible || activeTrack !== "supervised") {
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
    activeTrack,
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
  const supervisedSnapshotError = supervisedTrackQueriesEnabled && workspaceSnapshotQuery.isError && !workspaceSnapshot;
  const supervisedSnapshotErrorText = supervisedSnapshotError
    ? workspaceSnapshotQuery.error instanceof Error
      ? workspaceSnapshotQuery.error.message
      : String(workspaceSnapshotQuery.error)
    : "";
  const runHeaderMessage = supervisedSnapshotError
    ? t("loadFailed")
    : !hasRuns
      ? t("noRunsRecordedHint")
      : filteredRunsEmpty
        ? t("runFilterEmptyHint")
        : t("runQueueHint");
  const libraryHeaderMessage = libraryPaneEmpty
    ? (libraryView === "items" ? t("emptyLibraryItems") : t("emptyPendingItems"))
    : libraryFilteredEmpty
      ? t("noProposalMatches")
      : t("chooseProposalDetail");
  // Collapse-only styles: widths/heights themselves come from the hook-owned
  // --pane-w-* / --pane-h-* variables on the registered split container.
  const runsWorkspaceStyle = useMemo(
    () =>
      ({
        ...(runsQueueCollapsed ? { [paneWidthCssVar("runs-queue")]: "0px" } : null),
      }) as CSSProperties,
    [runsQueueCollapsed],
  );
  const libraryWorkspaceStyle = useMemo(
    () =>
      ({
        ...(libraryListCollapsed ? { [paneWidthCssVar("library-list")]: "0px" } : null),
      }) as CSSProperties,
    [libraryListCollapsed],
  );
  const evolutionVariablesStyle = evolutionPaneVariablesStyle;
  const registerEvolutionVariablesContainer = registerEvolutionContainer;
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
    if (normalized === "baseline_rerun") {
      return lang === "zh" ? "独立复跑" : "Clean-room rerun";
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

  const supervisedWorkflowStepViews: EvolutionSupervisedWorkflowStepView[] = supervisedWorkflowCards.map((step) => {
    const selected = step.id === supervisedSelectedWorkflowStep.id;
    const current = step.id === supervisedRuntimeWorkflowStepId;
    const member = step.member;
    const sessionRoute = step.chatRoute || member?.chatRoute || "";
    const approvalIsAgent = String(supervisedMembersRun?.approvalMode ?? approvalMode).toLowerCase() === "agent";
    const meta = step.role
      ? runRoleLabel(step.role)
      : approvalIsAgent
        ? (lang === "zh" ? "Agent 审批" : "Agent approval")
        : (lang === "zh" ? "人工审批" : "Human approval");
    const metric = typeof step.metrics?.scoreDelta === "number"
      ? `Δ ${step.metrics.scoreDelta}`
      : typeof step.metrics?.score === "number"
        ? String(step.metrics.score)
        : statusLabel(step.status);
    return {
      id: step.id,
      label: supervisedWorkflowStepLabel(step, lang),
      selected,
      current,
      meta,
      metric,
      preview: step.livePreview || step.summary || (lang === "zh" ? "等待实时输出" : "Waiting for live output"),
      sessionRoute: sessionRoute || undefined,
      configRoute: member?.configRoute || undefined,
      memberName: member?.name,
    };
  });

  function supervisedAgentRoleDescription(role: SupervisedMemberRole) {
    if (role === "baseline") {
      return lang === "zh" ? "基线运行后在原会话中完成自改" : "Run the baseline and self-improve in the same session";
    }
    if (role === "baseline_rerun") {
      return lang === "zh" ? "新会话独立复跑，不继承本轮上下文" : "Independent rerun in a fresh session";
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


  const confirmationRun = supervisedConfirmation?.runId === supervisedWorktreeLiveRun?.runId
    ? supervisedWorktreeLiveRun : supervisedConfirmation?.runId === reviewCandidateWorktree?.runId ? reviewCandidateWorktree : null;
  const confirmationActionKey = supervisedConfirmation ? ({
    approve_review: "approveReview", run_agent_approval: "runAgentApproval",
    reject_review: "rejectReview", request_rerun: "requestRerun",
  } as Record<string, string>)[supervisedConfirmation.action] || supervisedConfirmation.action : "";
  const confirmationEnabled = Boolean(confirmationRun?.actionStates?.[confirmationActionKey]?.enabled);
  const confirmationLabel = supervisedConfirmation ? (lang === "zh" ? ({
    terminate: "停止运行", approve_review: "批准并受控合入", run_agent_approval: "运行 Agent 审批",
    reject_review: "拒绝改动", request_rerun: "重新评测", merge: "合入候选", rollback: "回滚改动",
  } as Record<string, string>)[supervisedConfirmation.action] || supervisedConfirmation.action : supervisedConfirmation.action) : "";
  const frozenSourceLabel = reviewCandidateWorktree?.datasetName || reviewCandidateWorktree?.bundleName
    || selectedSupervisedWorkspaceRun?.worktreeRun?.datasetName || selectedSupervisedWorkspaceRun?.worktreeRun?.bundleName
    || monitoredRun?.datasetName || monitoredRun?.bundleName || (lang === "zh" ? "尚未选择" : "Not selected");
  function openSupervisedSetup() {
    if (!supervisedSetupOpen) supervisedDraftRef.current = {
      sourceKind, datasetName, bundleName: bundleNameInput, limit: datasetLimitInput,
      approval: approvalMode, mental: supervisedMentalModelMode,
    };
    setSupervisedDialog(null);
    setSupervisedSetupOpen(true);
  }
  function cancelSupervisedSetup() {
    const draft = supervisedDraftRef.current;
    if (draft) {
      setSourceKind(draft.sourceKind); setDatasetName(draft.datasetName); setBundleNameInput(draft.bundleName);
      setDatasetLimitInput(draft.limit); setApprovalMode(draft.approval); setSupervisedMentalModelMode(draft.mental);
    }
    supervisedDraftRef.current = null;
    setSupervisedSetupOpen(false);
  }

  const workspaceRunGroups: EvolutionWorkspaceRunGroup[] = (["supervised", "self"] as const)
    .filter((track) => track === "supervised" ? supervisedTrackEnabled : selfTrackEnabled)
    .map((track) => ({
      id: track,
      label: track === "supervised" ? t("supervisedEvolutionMode") : (lang === "zh" ? "自进化 · 当前与最近" : "Self-evolution · current and latest"),
      onHistory: () => {
        changeWorkspaceTrack(track);
        if (track === "supervised") goToSupervisedView("runs");
        else setSelfDetailsOpen(true);
      },
      runs: unifiedRuns.filter((run) => run.track === track)
        .sort((left, right) => evolutionRunTimestamp(right) - evolutionRunTimestamp(left)).map((run) => ({
        id: run.key,
        title: run.title,
        history: isEvolutionRunHistory(run),
        status: `${statusLabel(run.status)} · ${run.runId.slice(-8)}`,
        selected: activeTrack === track && run.key === (track === "supervised" ? selectedSupervisedWorkspaceRun?.key : selectedSelfWorkspaceRun?.key),
        onSelect: () => {
          setActionFeedback("");
          setSelfActionFeedback("");
          setWorkspaceRunKeys((keys) => ({ ...keys, [track]: run.key }));
          setSupervisedSetupOpen(false);
          changeWorkspaceTrack(track);
        },
      })),
    }));
  const workspaceNavigation = {
    activeTrack,
    onTrackChange: changeWorkspaceTrack,
    trackAvailability: { supervised: supervisedTrackEnabled, self: selfTrackEnabled },
    runGroups: workspaceRunGroups,
  };
  const selectedSelfRunMissing = Boolean(workspaceRunKeys.self && !selectedSelfWorkspaceRun && !selfWorkspaceSnapshotQuery.isLoading);

  return (
    <VTrackWorkbenchPage
      ref={evolutionLayoutRef}
      fill
      className={activeTrack === "self" || evolutionView === "live" ? `${styles.page} ${styles.supervisedLivePage}` : styles.page}
      ariaLabel={routeTitle}
      domainRecipe="evolution-multi-rail"
      data-vui-recipe="evolution-workbench"
      data-vui-layout-id={EVOLUTION_LAYOUT_ID}
      data-evolution-track={activeTrack}
      header={
        showRouteToolbar
          ? {
              ariaLabel: routeTitle,
              hideIntro: hideSupervisedToolbarIntro,
              className: hideSupervisedToolbarIntro
                ? styles.toolbarSupervisedFocus
                : styles.toolbar,
              eyebrow: routeEyebrow,
              title: routeTitle,
              meta: routeSubtitle,
              actions: (
                <div
                  className={
                    hideSupervisedToolbarIntro
                      ? styles.toolbarControlsSupervisedFocus
                      : styles.toolbarControls
                  }
                >
                  {showTrackToggle ? (
                    <VTabs
                      density="compact"
                      className={styles.trackTabs}
                      listClassName={styles.trackTabsList}
                      triggerClassName={styles.trackTabsTrigger}
                      aria-label={lang === "zh" ? "进化轨道" : "Evolution track"}
                      value={activeTrack}
                      onValueChange={(value) => {
                        if (value === "supervised" || value === "self") {
                          changeWorkspaceTrack(value);
                        }
                      }}
                      items={[
                        { id: "supervised", label: t("supervisedEvolutionMode") },
                        { id: "self", label: t("selfEvolutionMode") },
                      ]}
                    />
                  ) : null}

                  {activeTrack === "supervised" ? (
                    <SupervisedWorkspaceControls
                      activeView={evolutionView}
                      activeWorkflowStepId={supervisedWorkspaceActiveStepId}
                      onWorkflowStepSelect={handleSupervisedWorkflowStepSelect}
                      overviewIntakeMode={overview?.intakeMode}
                      configIntakeMode={configQuery.data?.intakeMode}
                      tabSummaries={supervisedTabSummaries}
                    />
                  ) : null}
                </div>
              ),
            }
          : null
      }
    >
      <div
        ref={registerEvolutionVariablesContainer}
        style={evolutionVariablesStyle}
        className="contents"
      >
      {activeTrack === "self" ? (
        <Suspense fallback={<p role="status">{t("loading")}</p>}>
          <SelfEvolutionConversationWorkspace
            lang={lang}
            workspaceNavigation={workspaceNavigation}
            selectedRunKind={selectedSelfWorkspaceRun?.kind === "session" ? null : selectedSelfWorkspaceRun?.kind ?? null}
            overview={selfOverview}
            autonomousRun={selectedSelfWorkspaceRun?.autonomousRun ?? null}
            observationRun={selectedSelfWorkspaceRun?.observationRun ?? null}
            worktreeRun={selectedSelfDetail.run}
            phaseSelections={selfPhaseSelections}
            onPhaseSelect={(runKey, phaseId) => setSelfPhaseSelections((current) => ({ ...current, [runKey]: phaseId }))}
            goalInput={selfGoalInput}
            onGoalInputChange={setSelfGoalInput}
            onStartRun={() => startSelfAutonomousLoopMutation.mutate({ goal: selfGoalInput.trim(), maxIterations: 1 }, {
              onSuccess: (run) => {
                setWorkspaceRunKeys((keys) => ({ ...keys, self: `self:autonomous:${run.runId}` }));
                setSelfRunFeedback((current) => ({ ...current, [`self:autonomous:${run.runId}`]: lang === "zh" ? "自动闭环已启动。" : "The autonomous loop started." }));
              },
            })}
            onAutonomousAction={(runId, action, comment) => {
              setSelfRunFeedback((current) => ({ ...current, [`self:autonomous:${runId}`]: "" }));
              selfAutonomousLoopActionMutation.mutate({ runId, action, comment }, { onSuccess: (run) => setSelfRunFeedback((current) => ({ ...current, [`self:autonomous:${run.runId}`]: run.error?.message || (run.status === "completed" ? (lang === "zh" ? "候选已完成 Git 集成与清理。" : "Candidate integration and cleanup completed.") : "") })) });
            }}
            onStartObservation={(payload) => startSelfObservationMutation.mutate(payload, {
              onSuccess: (run) => setWorkspaceRunKeys((keys) => ({ ...keys, self: `self:observation:${run.runId}` })),
            })}
            onTerminateObservation={(runId) => selfObservationActionMutation.mutate({ runId, action: "terminate" })}
            onWorktreeAction={(runId, action) => approvalWorktreeActionMutation.mutate({ runId, action })}
            startPending={startSelfAutonomousLoopMutation.isPending}
            observationStartPending={startSelfObservationMutation.isPending}
            observationActionPending={selfObservationActionMutation.isPending}
            worktreeActionPending={approvalWorktreeActionMutation.isPending}
            autonomousActionPending={selfAutonomousLoopActionMutation.isPending}
            startWorktreeError={startSelfAutonomousLoopMutation.error?.message ?? ""}
            observationStartError={startSelfObservationMutation.error?.message ?? ""}
            observationActionError={selfObservationActionMutation.variables?.runId === selectedSelfWorkspaceRun?.runId ? selfObservationActionMutation.error?.message ?? "" : ""}
            worktreeActionError={approvalWorktreeActionMutation.variables?.runId === selectedSelfWorkspaceRun?.runId ? approvalWorktreeActionMutation.error?.message ?? "" : ""}
            autonomousActionError={selfAutonomousLoopActionMutation.variables?.runId === selectedSelfWorkspaceRun?.runId ? selfAutonomousLoopActionMutation.error?.message ?? "" : ""}
            actionFeedback={selectedSelfWorkspaceRun ? selfRunFeedback[selectedSelfWorkspaceRun.key] ?? "" : ""}
            runLocked={selfRunLocked}
            worktreeRunLocked={worktreeRunLocked}
            loading={selfTrackLoading || selectedSelfDetail.loading}
            loadError={selectedSelfRunMissing ? (lang === "zh" ? "所选运行已不在当前列表中，请在左栏重新选择。" : "The selected run is no longer in this list. Select another run.") : selectedSelfDetail.error?.message || selfWorkspaceSnapshotQuery.error?.message || ""}
            onRetry={() => { void selfWorkspaceSnapshotQuery.refetch(); void selectedSelfDetail.retry(); }}
            onHistory={() => setSelfDetailsOpen(true)}
            onSettings={() => setSelfDetailsOpen(true)}
            onLibrary={() => { changeWorkspaceTrack("supervised"); goToSupervisedView("library"); }}
          />
        </Suspense>
      ) : null}
      <VDialog open={activeTrack === "self" && selfDetailsOpen} onOpenChange={setSelfDetailsOpen}
        title={lang === "zh" ? "所选运行详情与事务历史" : "Selected run details and transaction history"} className={styles.selfDetailsDialog}>
        {selfDetailsOpen ? (
        <EvolutionSelfTrackBoundary
          lang={lang}
          overview={selfOverview}
          worktreeRun={selectedSelfDetail.run}
          observationRun={selectedSelfWorkspaceRun?.observationRun ?? null}
          autonomousRun={selectedSelfWorkspaceRun?.autonomousRun ?? null}
          goalInput={selfGoalInput}
          onGoalInputChange={setSelfGoalInput}
          onStartRun={() => startSelfAutonomousLoopMutation.mutate({
            goal: selfGoalInput.trim(),
            maxIterations: 1,
          }, { onSuccess: (run) => setWorkspaceRunKeys((keys) => ({ ...keys, self: `self:autonomous:${run.runId}` })) })}
          onAutonomousAction={(runId, action, comment) =>
            selfAutonomousLoopActionMutation.mutate({ runId, action, comment })}
          onStartObservation={(payload) => startSelfObservationMutation.mutate(payload)}
          onTerminateObservation={(runId) => selfObservationActionMutation.mutate({ runId, action: "terminate" })}
          onWorktreeAction={(runId, action) => approvalWorktreeActionMutation.mutate({ runId, action })}
          onDeleteHistoryGroups={(txnIds) => deleteSelfHistoryMutation.mutate(txnIds)}
          startPending={startSelfAutonomousLoopMutation.isPending}
          observationStartPending={startSelfObservationMutation.isPending}
          observationActionPending={selfObservationActionMutation.isPending}
          worktreeActionPending={approvalWorktreeActionMutation.isPending}
          autonomousActionPending={selfAutonomousLoopActionMutation.isPending}
          deleteHistoryPending={deleteSelfHistoryMutation.isPending}
          startWorktreeError={startSelfAutonomousLoopMutation.error?.message ?? ""}
          observationStartError={startSelfObservationMutation.error?.message ?? ""}
          observationActionError={selfObservationActionMutation.error?.message ?? ""}
          worktreeActionError={approvalWorktreeActionMutation.error?.message ?? ""}
          autonomousActionError={selfAutonomousLoopActionMutation.error?.message ?? ""}
          deleteHistoryError={deleteSelfHistoryMutation.error?.message ?? ""}
          actionFeedback={selfActionFeedback}
          runLocked={selfRunLocked}
          worktreeRunLocked={worktreeRunLocked}
          transactions={selfTransactions}
          loading={selfTrackLoading}
        />
        ) : null}
      </VDialog>

      {activeTrack === "supervised" && evolutionView === "live" ? (
        <>
          <SupervisedConversationWorkspace
            {...workspaceNavigation}
            lang={lang}
            title={selectedSupervisedWorkspaceRun?.title || (lang === "zh" ? "监督进化" : "Supervised evolution")}
            sourceLabel={frozenSourceLabel}
            sourceSummary={`${lang === "zh" ? "本轮样本" : "Run cases"} ${reviewCandidateWorktree?.costEstimate?.caseCount ?? monitoredRun?.caseTotal ?? "—"} · ${reviewCandidateWorktree?.approvalMode === "agent" ? "Agent" : (lang === "zh" ? "人工审批" : "Human approval")}`}
            phases={supervisedWorkflowCards.map((step) => ({
              id: step.id, label: step.label, statusLabel: statusLabel(step.status), current: step.current,
              disabled: !step.current && step.status === "pending" && !step.conversationSessionId,
            }))}
            hasRun={Boolean(selectedSupervisedWorkspaceRun)}
            setupOpen={supervisedSetupOpen || !selectedSupervisedWorkspaceRun}
            selectedStepId={selectedSupervisedAgentRole && !SUPERVISED_WORKFLOW_STEPS.some((step) => step.role === selectedSupervisedAgentRole)
              ? `agent:${selectedSupervisedAgentRole}` : supervisedSelectedWorkflowStepId || "baseline_eval"}
            steps={[...supervisedWorkflowCards.map((step) => ({
              id: step.id,
              label: `${step.label}${step.role ? ` · ${runRoleLabel(step.role)}` : ""}${step.current ? (lang === "zh" ? " · 当前" : " · Current") : ""}`,
              disabled: !step.current && step.status === "pending" && !step.conversationSessionId,
            })), ...supervisedRunMembers.filter((member) => !SUPERVISED_WORKFLOW_STEPS.some((step) => step.role === member.role)).map((member) => ({
              id: `agent:${member.role}`, label: runRoleLabel(member.role), disabled: !member.agentId && !member.conversationSession?.conversationSessionId,
            }))]}
            onSelectStep={(id) => id.startsWith("agent:") ? handleSupervisedAgentSelect(id.slice(6) as SupervisedMemberRole) : handleSupervisedWorkflowStepSelect(id as SupervisedWorkflowStepId)}
            showFollowLive={supervisedWorkflowManualSelection || Boolean(selectedSupervisedAgentRole && selectedSupervisedAgentRole !== supervisedActiveAgentRole)}
            onFollowLive={handleFollowSupervisedAgent}
            onNew={openSupervisedSetup}
            onSource={() => setSupervisedDialog("source")}
            onHistory={() => goToSupervisedView("runs")}
            onLibrary={() => goToSupervisedView("library")}
            onSettings={() => setSupervisedDialog("settings")}
            onOpenConversation={supervisedSelectedAgentMember?.chatRoute ? () => navigate(supervisedSelectedAgentMember.chatRoute!) : undefined}
            setup={
              <div className={styles.supervisedSetupFrame}>
                {workspaceRunKeys.supervised && !selectedSupervisedWorkspaceRun && !workspaceSnapshotQuery.isLoading ? <p role="alert" className={styles.errorTextCompact}>{lang === "zh" ? "所选运行已不在当前列表中，请在左栏重新选择。" : "The selected run is no longer in this list. Select another run."}</p> : null}
                {workbenchCatalogUnavailable ? <p role="alert" className={styles.errorTextCompact}>{lang === "zh" ? "评估集目录暂时不可用，请稍后重试。" : "Evaluation catalog is temporarily unavailable."}</p> : null}
                {supervisedSnapshotErrorText ? <p role="alert" className={styles.errorTextCompact}>{supervisedSnapshotErrorText}<VButton onPress={() => void workspaceSnapshotQuery.refetch()}>{lang === "zh" ? "重试" : "Retry"}</VButton></p> : null}
                <EvolutionSupervisedLiveSetupPanel
                  lang={lang}
                  onCancel={supervisedWorkflowRun ? cancelSupervisedSetup : undefined}
                  sourceKind={sourceKind}
                  selectedSourceValue={selectedSourceValue}
                  sourceOptions={supervisedSourceOptions.map((source) => ({
                    value: source.value,
                    kind: source.kind,
                    caseCount: source.caseCount,
                    detail: source.kind === "dataset" ? source.dataset?.description : "",
                    status: source.kind === "dataset" ? datasetUsabilityLabel(source.dataset, lang) : undefined,
                    label: source.name,
                  }))}
                  onSourceValueChange={(value) => {
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
                  datasetLimitInput={datasetLimitInput}
                  datasetLimitInputRef={datasetLimitInputRef}
                  onDatasetLimitChange={setDatasetLimitInput}
                  selectedSourceLabel={selectedSourceOption?.label}
                  selectedSourceStatusText={selectedSourceStatusText}
                  selectedSourceEvaluationText={selectedSourceEvaluationText}
                  selectedSourceKindLabel={selectedSourceKindLabel}
                  selectedSourceCaseText={selectedSourceCaseText}
                  selectedSourceOfficialWarning={selectedSourceOfficialWarning}
                  showMissingBundleError={Boolean(workbenchControl && sourceKind === "bundle" && !selectedBundleExists)}
                  approvalMode={approvalMode}
                  onApprovalModeChange={setApprovalMode}
                  supervisedMentalModelMode={supervisedMentalModelMode}
                  onMentalModelModeChange={setSupervisedMentalModelMode}
                  startDisabled={
                    Boolean(datasetLimitError) ||
                    startLocked
                    || !workbenchControl
                    || (sourceKind === "dataset" && !datasetName)
                    || (sourceKind === "bundle" && !selectedBundleExists)
                  }
                  startDisabledReason={supervisedStartDisabledReason}
                  startPendingVisual={supervisedStartSubmitting || supervisedPrimaryRunning}
                  startLabel={supervisedStartButtonLabel}
                  startTooltip={t("launchSupervisedRunHint")}
                  caseLimitLabel={t("caseLimit")}
                  caseLimitHint={t("caseLimitHint")}
                  mentalModeLabel={t("supervisedMentalMode")}
                  mentalModeHint={t("supervisedMentalModeHint")}
                  mentalModeFollowLabel={t("supervisedMentalModeFollow")}
                  mentalModeEnabledLabel={t("supervisedMentalModeEnabled")}
                  mentalModeDisabledLabel={t("supervisedMentalModeDisabled")}
                  runningLockHint={activationLocked ? t("supervisedActivationLockHint") : t("runningLockHint")}
                  showRunningLock={runLocked || worktreeRunLocked || activationLocked}
                  controlError={datasetLimitError || supervisedControlError}
                  onStart={() => startWorktreeRunMutation.mutate(undefined, { onSuccess: () => { setSupervisedSetupOpen(false); supervisedDraftRef.current = null; } })}
                />
              </div>
            }
            conversation={<div className={styles.supervisedConversationFrame}>
              {supervisedSnapshotErrorText ? <p role="alert" className={styles.errorTextCompact}>{supervisedSnapshotErrorText}<VButton onPress={() => void workspaceSnapshotQuery.refetch()}>{lang === "zh" ? "重试" : "Retry"}</VButton></p> : null}
              {selectedSupervisedDetail.loading ? <p role="status">{t("loading")}</p>
                : selectedSupervisedDetail.error ? <div role="alert">{selectedSupervisedDetail.error.message}<VButton onPress={() => void selectedSupervisedDetail.retry()}>{lang === "zh" ? "重试" : "Retry"}</VButton></div>
                : <SupervisedAgentConversationPanel
                      compact
                      members={supervisedRunMembers}
                      selectedRole={supervisedSelectedAgentRole}
                      activeRole={supervisedActiveAgentRole}
                      fallbackMessages={supervisedSelectedAgentFallbackMessages}
                      taskSummary={supervisedSelectedAgentTaskSummary}
                      isLive={supervisedRunIsLive}
                      lang={lang}
                      roleLabel={runRoleLabel}
                      roleDescription={supervisedAgentRoleDescription}
                      statusLabel={statusLabel}
                      onSelectRole={handleSupervisedAgentSelect}
                      onFollowLive={handleFollowSupervisedAgent}
                    />}
            </div>}
            footer={supervisedRunIsLive ? (
              <div className={styles.supervisedLiveFooter}>
                <span className={styles.supervisedSecondaryText}>{supervisedMembersRunStatusLabel} · {supervisedWorkflowCards.find((step) => step.current)?.label}</span>
                <VButton variant="ghost" isDisabled={!canTerminateSupervisedRun || terminateSupervisedPending} disabledReason={terminateSupervisedDisabledReason} onPress={() => supervisedWorktreeLiveRun && setSupervisedConfirmation({runId:supervisedWorktreeLiveRun.runId,action:"terminate"})}>{lang === "zh" ? "停止运行" : "Stop run"}</VButton>
                {supervisedControlError ? <p role="alert" className={styles.errorTextCompact}>{supervisedControlError}</p> : null}
              </div>
            ) : <SupervisedApprovalDecisionPanel compact
                      run={reviewCandidateWorktree}
                      lang={lang}
                      pending={approvalWorktreeActionMutation.isPending}
                      onPrepareRerun={(run) => {
                        openSupervisedSetup();
                        setSourceKind(run.sourceKind === "dataset" ? "dataset" : "bundle");
                        setDatasetName(run.datasetName || "");
                        setBundleNameInput(run.bundleName || "");
                        setDatasetLimitInput(run.datasetLimit == null ? "" : String(run.datasetLimit));
                        setApprovalMode(run.approvalMode === "agent" ? "agent" : "human");
                        setActionFeedback(lang === "zh" ? "已恢复本轮来源、样本数和审批方式；请检查当前配置后点击开始监督运行。" : "Source, sample limit and approval mode restored. Check current settings before starting.");
                        requestAnimationFrame(() => datasetLimitInputRef.current?.focus());
                      }}
                      error={supervisedControlError}
                      onAction={(runId, action) => setSupervisedConfirmation({ runId, action })}
                    />}
            evidenceTabs={[
              { id: "changes", label: lang === "zh" ? "改动" : "Changes", content: (
                <section className={styles.supervisedChanges} aria-label={lang === "zh" ? "本轮候选改动" : "Candidate changes"}>
                  {(reviewCandidateWorktree?.mergeAnalysis?.changedFiles ?? []).map((file) => (
                    <div key={file.path} className={styles.supervisedChangedFile}>
                      <code className={styles.supervisedChangedPath}>{file.path}</code>
                      <span className={styles.supervisedSecondaryText}>{file.changeType || file.status}{file.highRisk ? (lang === "zh" ? " · 需要复核" : " · Review required") : ""}</span>
                    </div>
                  ))}
                  {!reviewCandidateWorktree?.mergeAnalysis?.changedFiles?.length ? <p>{lang === "zh" ? "本轮尚未生成候选文件变更记录。" : "No candidate file changes are available yet."}</p> : null}
                  <VButton variant="secondary" onPress={() => navigate("/supervised-evolution/review")}>{lang === "zh" ? "完整审核与证据" : "Full review and evidence"}</VButton>
                </section>
              ) },
              { id: "scores", label: lang === "zh" ? "评分" : "Scores", content: <SupervisedApprovalDecisionPanel hideActions run={reviewCandidateWorktree} lang={lang} pending={approvalWorktreeActionMutation.isPending} onAction={(runId, action) => setSupervisedConfirmation({ runId, action })} /> },
              { id: "progress", label: lang === "zh" ? "进度" : "Progress", content: <>
          <Suspense fallback={<p className={styles.noticeText}>{t("loading")}</p>}>
            <EvolutionActiveRunMonitorPanel
              className={styles.supervisedEvidenceContent}
              header={{
                eyebrow: t("activeSupervisedRun"),
                title: monitoredRunIdentity || t("activeSupervisedRun"),
                titleTooltip: monitoredRunIdentity || undefined,
                statusLabel: supervisedRunMonitorSource ? monitoredStatusLabel : undefined,
                sourceKindLabel: supervisedRunMonitorSource
                  ? sourceKindLabel(monitoredWorktreeRun?.sourceKind || monitoredRun?.sourceKind || "")
                  : undefined,
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
                  onClick: () => recentSupervisedWorktreeRun
                    ? handleSupervisedWorkflowStepSelect("approval")
                    : openRun(overviewLatestRunId || null),
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
                <EvolutionSupervisedWorkflowMembersPanel lang={lang} membersSource={supervisedMembersSource} selectedStepLabel={supervisedWorkflowStepLabel(supervisedSelectedWorkflowStep, lang)} membersHint={supervisedMembersHint} showFollowLive={supervisedWorkflowManualSelection} onFollowLive={handleFollowSupervisedAgent} stepCount={supervisedWorkflowCards.length} steps={supervisedWorkflowStepViews} onSelectStep={handleSupervisedWorkflowStepSelect} />
                {supervisedLiveConversationSupplement}
                <EvolutionBaselinePromotionStrip lang={lang} t={t} promotion={workspaceSnapshot?.evolutionRuntime?.currentBaseline} />
              </> },
            ]}
          />
          <VDialog className={styles.supervisedDialog} open={supervisedDialog !== null} onOpenChange={(open) => !open && setSupervisedDialog(null)} title={supervisedDialog === "source" ? (lang === "zh" ? "本轮评估集" : "Run evaluation source") : (lang === "zh" ? "运行配置" : "Run settings")}>
            {supervisedDialog === "settings" && showTrackToggle ? <VTabs aria-label={lang === "zh" ? "进化轨道" : "Evolution track"} value={activeTrack} onValueChange={(value) => {
              if (value === "self" || value === "supervised") { changeWorkspaceTrack(value); setSupervisedDialog(null); }
            }} items={[{id:"supervised",label:t("supervisedEvolutionMode")},{id:"self",label:t("selfEvolutionMode")}]} /> : null}
            {supervisedDialog === "settings" ? <SupervisedWorkspaceControls activeView={evolutionView} overviewIntakeMode={overview?.intakeMode} configIntakeMode={configQuery.data?.intakeMode} /> : null}
            {supervisedDialog === "settings" ? <details className={styles.supervisedSourceCatalog}><summary>{lang === "zh" ? "评估来源目录" : "Evaluation source catalog"}</summary>
              <EvolutionDatasetCatalogPanel lang={lang} copy={{datasetCatalog:t("datasetCatalog"),datasetCatalogAll:t("datasetCatalogAll"),datasetCatalogRunnable:t("datasetCatalogRunnable"),datasetCatalogBlocked:t("datasetCatalogBlocked"),datasetCatalogRoadmap:t("datasetCatalogRoadmap"),datasetCatalogHiddenReason:t("datasetCatalogHiddenReason")}} items={datasetCatalog} groups={datasetCatalogGroups} selectedFilter={selectedDatasetCatalogFilter} onFilterChange={setSelectedDatasetCatalogFilter} />
            </details> : null}
            <dl className={styles.supervisedSourceFacts}>
              <div><dt>{lang === "zh" ? "评估来源" : "Evaluation source"}</dt><dd className={styles.supervisedSourceName}>{frozenSourceLabel}</dd></div>
              <div><dt>{lang === "zh" ? "本轮样本" : "Run cases"}</dt><dd>{reviewCandidateWorktree?.costEstimate?.caseCount ?? monitoredRun?.caseTotal ?? "—"}</dd></div>
              <div><dt>{lang === "zh" ? "审批方式" : "Approval mode"}</dt><dd>{reviewCandidateWorktree?.approvalMode === "agent" ? "Agent" : (lang === "zh" ? "人工" : "Human")}</dd></div>
            </dl>
            <p className={styles.supervisedSourceHint}>{lang === "zh" ? "本轮来源由运行记录固定；更换评估集需要新建一轮。" : "The run record fixes this source. Create a new run to change it."}</p>
            <VButton variant="secondary" onPress={openSupervisedSetup}>{lang === "zh" ? "选择评估集新建" : "Create with another source"}</VButton>
          </VDialog>
          <VDialog
            className={styles.supervisedDialog}
            open={Boolean(supervisedConfirmation)}
            onOpenChange={(open) => !open && !approvalWorktreeActionMutation.isPending && setSupervisedConfirmation(null)}
            title={confirmationLabel}
            description={supervisedConfirmation?.action === "approve_review"
              ? (lang === "zh" ? "批准后将由后端受控合入并请求激活；是否已生效，以运行版本核验结果为准。" : "Approval requests a controlled merge and activation. Runtime verification determines whether the change is applied.")
              : (lang === "zh" ? "确认对本轮运行执行此操作？结果以服务端返回的最新状态为准。" : "Perform this action on the current run? The server determines the resulting state.")}
            footer={<>
              <VButton variant="secondary" isDisabled={approvalWorktreeActionMutation.isPending} onPress={() => setSupervisedConfirmation(null)}>{lang === "zh" ? "返回" : "Back"}</VButton>
              <VButton variant={supervisedConfirmation?.action === "terminate" || supervisedConfirmation?.action === "reject_review" || supervisedConfirmation?.action === "rollback" ? "danger" : "primary"}
                isDisabled={!confirmationEnabled || approvalWorktreeActionMutation.isPending}
                onPress={() => {
                  if (supervisedConfirmation && confirmationEnabled) approvalWorktreeActionMutation.mutate(supervisedConfirmation, {onSuccess: () => setSupervisedConfirmation(null)});
                }}>{approvalWorktreeActionMutation.isPending ? (lang === "zh" ? "正在执行…" : "Working…") : (lang === "zh" ? "确认执行" : "Confirm")}</VButton>
            </>}
          >
            {!confirmationEnabled ? <p role="status">{confirmationRun?.actionStates?.[confirmationActionKey]?.reason || (lang === "zh" ? "运行状态已变化，此操作当前不可用。" : "The run state changed; this action is unavailable.")}</p> : null}
            {approvalWorktreeActionMutation.error ? <p role="alert">{approvalWorktreeActionMutation.error.message}</p> : null}
          </VDialog>
        </>
      ) : null}

      {activeTrack === "supervised" && evolutionView === "runs" ? (
        <EvolutionSupervisedRunsView
          lang={lang}
          labels={{ t, statusLabel, decisionLabel, riskLabel, proposalActionLabel }}
          runFilter={runFilter}
          onRunFilterChange={setRunFilter}
          filteredRunsCount={filteredRuns.length}
          totalRunsCount={runs.length}
          hasRuns={hasRuns}
          runSuccessCount={runSuccessCount}
          runFailedCount={runFailedCount}
          runPendingCount={runPendingCount}
          runDeletableCount={runDeletableCount}
          selectedRunCount={selectedRunIds.length}
          runsWorkspaceStyle={runsWorkspaceStyle}
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
      ) : null}

      {activeTrack === "supervised" && evolutionView === "library" ? (
        <EvolutionSupervisedLibraryView
          lang={lang}
          t={t}
          statusLabel={statusLabel}
          decisionLabel={decisionLabel}
          riskLabel={riskLabel}
          intakeModeLabel={intakeModeLabel}
          proposalActionLabel={proposalActionLabel}
          displayDecisionLabel={displayDecisionLabel}
          libraryView={libraryView}
          onLibraryViewChange={setLibraryView}
          libraryItems={libraryItems}
          pendingItems={pendingItems}
          filteredLibraryItems={filteredLibraryItems}
          filteredPendingItems={filteredPendingItems}
          visibleLibraryEntries={visibleLibraryEntries}
          currentLibraryEntries={currentLibraryEntries}
          selectedLibraryItem={selectedLibraryItem}
          selectedPendingItem={selectedPendingItem}
          selectedProposalSummary={selectedProposalSummary}
          selectedProposalIsSelfCandidate={selectedProposalIsSelfCandidate}
          selectedProposalDisplaySourceRun={selectedProposalDisplaySourceRun}
          selectedProposalCanOpenSourceRun={selectedProposalCanOpenSourceRun}
          selectedProposalRunIds={selectedProposalRunIds}
          libraryWorkspaceStyle={libraryWorkspaceStyle}
          libraryListCollapsed={libraryListCollapsed}
          libraryListWidth={libraryListWidth}
          libraryListMinWidth={EVOLUTION_LIBRARY_LIST_PANE.minWidth}
          libraryListMaxWidth={EVOLUTION_LIBRARY_LIST_PANE.maxWidth}
          libraryDragging={evolutionDraggingPaneId === "library-list"}
          resizeLibraryListLabel={resizeLibraryListLabel}
          onToggleLibraryListCollapsed={() => setLibraryListCollapsed((current) => !current)}
          onLibraryResizePointerDown={handleLibraryResizeStart}
          onLibraryResizeKeyDown={handleLibraryResizeKeyDown}
          librarySearchInput={librarySearchInput}
          onLibrarySearchInputChange={setLibrarySearchInput}
          libraryStatusFilter={libraryStatusFilter}
          onLibraryStatusFilterChange={setLibraryStatusFilter}
          libraryDeleteFilter={libraryDeleteFilter}
          onLibraryDeleteFilterChange={setLibraryDeleteFilter}
          hasLibraryFilters={hasLibraryFilters}
          onClearLibraryFilters={clearLibraryFilters}
          libraryHeaderMessage={libraryHeaderMessage}
          libraryDeletableCount={libraryDeletableCount}
          libraryBlockedCount={libraryBlockedCount}
          currentIntakeMode={currentIntakeMode}
          latestRunId={latestRun?.id}
          libraryFeedback={libraryFeedback}
          bulkDeleteError={bulkDeleteMutation.error?.message}
          bulkDeletePending={bulkDeleteMutation.isPending}
          onClearProposalSelection={() => setSelectedProposalRunIds([])}
          onBulkDelete={triggerBulkDelete}
          onSelectLibraryItem={setSelectedLibraryItemId}
          onSelectPendingItem={setSelectedPendingItemId}
          onToggleProposalSelection={toggleProposalSelection}
          proposalSelected={proposalSelected}
          proposalDetail={proposalDetailQuery.data}
          proposalDetailError={proposalDetailQuery.error instanceof Error ? proposalDetailQuery.error.message : proposalDetailQuery.error ? String(proposalDetailQuery.error) : undefined}
          proposalDetailLoading={proposalDetailQuery.isPending}
          proposalEditOpen={proposalEditOpen}
          proposalEditDraft={proposalEditDraft}
          proposalEditFeedback={proposalEditFeedback}
          updateProposalPending={updateProposalMutation.isPending}
          updateProposalError={updateProposalMutation.error?.message ?? ""}
          deleteProposalPending={deleteProposalMutation.isPending}
          deleteProposalError={deleteProposalMutation.error?.message ?? ""}
          actionFeedback={actionFeedback}
          actionError={actionMutation.error?.message ?? ""}
          actionPending={actionMutation.isPending}
          runLocked={runLocked}
          onBeginProposalEdit={beginProposalEdit}
          onCancelProposalEdit={cancelProposalEdit}
          onUpdateProposalEditDraft={updateProposalEditDraft}
          onTriggerProposalUpdate={triggerProposalUpdate}
          onRunAction={triggerRunAction}
          onDeleteProposal={triggerProposalDelete}
          onOpenRun={openRun}
          formatAvailableActions={formatAvailableActions}
        />
      ) : null}
      </div>
    </VTrackWorkbenchPage>
  );
}
