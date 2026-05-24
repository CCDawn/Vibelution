import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowUpRight,
  CheckCircle2,
  Clock3,
  Gauge,
  LibraryBig,
  LoaderCircle,
  Pause,
  Play,
  Sparkles,
  Square,
  Save,
  Pencil,
  Trash2,
  TriangleAlert,
  X,
} from "lucide-react";
import { type CSSProperties, type KeyboardEvent, type PointerEvent, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import {
  EvolutionActiveRun,
  EvolutionActiveRunStreamEvent,
  EvolutionActionState,
  ConfigSummary,
  EvolutionOverview,
  EvolutionRunActionResponse,
  EvolutionRunDeleteResponse,
  EvolutionWorkbench,
  EvolutionProposalBulkDeleteResponse,
  EvolutionProposalDeleteResponse,
  EvolutionProposalDetail,
  EvolutionProposalUpdateResponse,
  EvolutionLibraryEntry,
  EvolutionLibraryPayload,
  SupervisedWorktreeRun,
  SelfEvolutionActiveRun,
  SelfEvolutionHistoryDeleteResponse,
  SelfEvolutionHandoffResponse,
  SelfEvolutionRunStreamEvent,
  EvolutionRun,
  SelfEvolutionOverview,
  SelfEvolutionTransaction,
} from "../api/types";
import { resolvePollingInterval, usePageVisibility } from "../app/pollingPolicy";
import { useAppI18n } from "../i18n/useAppI18n";
import { useShellStore } from "../store/shellStore";
import { SelfEvolutionTrack } from "./SelfEvolutionTrack";
import { SupervisedWorkspaceControls } from "./SupervisedWorkspaceControls";
import {
  isLiveSupervisedRunStatus,
  parseRunStreamSnapshot,
  requireEvolutionRunSnapshot,
  selectRunSnapshotWithRunId,
  selectSupervisedRunStreamTarget,
  shouldIgnoreActiveRunSnapshot,
} from "./evolutionLiveRun";
import {
  clampPaneSize,
  clampPaneWidth,
  keyboardPaneHeight,
  keyboardPaneWidth,
  storedPaneSize,
  storedPaneWidth,
} from "./resizablePane";
import { savePendingSelfEvolutionHandoff } from "./selfEvolutionHandoff";
import styles from "./EvolutionRoute.module.css";

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
const EVOLUTION_RUNS_QUEUE_WIDTH_KEY = "vibelution.evolution.runs-queue-width";
const EVOLUTION_RUNS_QUEUE_BOUNDS = { min: 300, max: 520 };
const EVOLUTION_RUNS_QUEUE_DEFAULT_WIDTH = 380;
const EVOLUTION_LIBRARY_LIST_WIDTH_KEY = "vibelution.evolution.library-list-width";
const EVOLUTION_LIBRARY_LIST_BOUNDS = { min: 280, max: 520 };
const EVOLUTION_LIBRARY_LIST_DEFAULT_WIDTH = 360;
const EVOLUTION_LIVE_LAUNCH_WIDTH_KEY = "vibelution.evolution.live-launch-width";
const EVOLUTION_LIVE_LAUNCH_BOUNDS = { min: 320, max: 520 };
const EVOLUTION_LIVE_LAUNCH_DEFAULT_WIDTH = 360;
const EVOLUTION_LIVE_RUN_WIDTH_KEY = "vibelution.evolution.live-run-width";
const EVOLUTION_LIVE_RUN_BOUNDS = { min: 320, max: 560 };
const EVOLUTION_LIVE_RUN_DEFAULT_WIDTH = 380;
const EVOLUTION_LIVE_IO_HEIGHT_KEY = "vibelution.evolution.live-io-height";
const EVOLUTION_LIVE_IO_HEIGHT_BOUNDS = { min: 260, max: 780 };
const EVOLUTION_LIVE_IO_DEFAULT_HEIGHT = 440;

type ProposalEditDraft = {
  improvementType: string;
  expectedEffect: string;
  summary: string;
  candidatePrompt: string;
  baselinePrompt: string;
  editNote: string;
};

function clampScore(value: number) {
  return Math.max(0, Math.min(100, Math.round(value)));
}

function isSelfRunExecutingStatus(status: string) {
  return ["queued", "running", "stopping"].includes(String(status || "").trim().toLowerCase());
}

function isSelfRunLockedStatus(status: string) {
  return ["queued", "running", "stopping", "paused"].includes(String(status || "").trim().toLowerCase());
}

function statusIcon(status: string) {
  const normalized = String(status).trim().toLowerCase();
  if (normalized === "success") {
    return <CheckCircle2 size={16} />;
  }
  if (normalized === "failed" || normalized === "caution") {
    return <TriangleAlert size={16} />;
  }
  if (normalized === "running" || normalized === "waiting" || normalized === "queued" || normalized === "paused" || normalized === "stopping") {
    return <Clock3 size={16} />;
  }
  if (normalized === "done" || normalized === "cancelled") {
    return <CheckCircle2 size={16} />;
  }
  return <Gauge size={16} />;
}

function toLimitInput(value: number | null | undefined) {
  if (typeof value !== "number" || Number.isNaN(value) || value <= 0) {
    return "";
  }
  return String(value);
}

function compactTimestamp(value: string) {
  const text = String(value || "").trim();
  if (!text) {
    return "--";
  }
  const normalized = text.replace("T", " ");
  if (normalized.length > 19) {
    return normalized.slice(0, 19);
  }
  return normalized;
}

function formatTurnRange(startTurn: number, endTurn: number) {
  if (startTurn > 0 && endTurn > 0) {
    return `T${startTurn}-${endTurn}`;
  }
  if (startTurn > 0) {
    return `T${startTurn}`;
  }
  return "--";
}

function datasetUsabilityLabel(
  dataset: { effective?: boolean; usabilityStatus?: string; adapterStatus?: string; caseCount?: number | null },
  lang: string,
) {
  const status = String(dataset.usabilityStatus || "").trim();
  const caseCount = typeof dataset.caseCount === "number" ? dataset.caseCount : null;
  if (dataset.effective) {
    return lang === "zh" ? `可用 ${caseCount ?? 0} 例` : `usable ${caseCount ?? 0} cases`;
  }
  if (status === "empty") {
    return lang === "zh" ? "空数据" : "empty";
  }
  if (status === "missing_source") {
    return lang === "zh" ? "缺源文件" : "missing source";
  }
  if (status === "requires_external_harness") {
    return lang === "zh" ? "需外部 harness" : "needs harness";
  }
  if (status === "invalid") {
    return lang === "zh" ? "格式异常" : "invalid";
  }
  if (status === "blocked") {
    return String(dataset.adapterStatus || status || "blocked");
  }
  return String(dataset.adapterStatus || status || (lang === "zh" ? "不可用" : "unavailable"));
}

function proposalEditDraftFromDetail(detail: EvolutionProposalDetail): ProposalEditDraft {
  return {
    improvementType: detail.proposal.improvementType || "",
    expectedEffect: detail.proposal.expectedEffect || "",
    summary: detail.proposal.summary || detail.review.changeSummary || "",
    candidatePrompt: detail.proposal.candidatePrompt || "",
    baselinePrompt: detail.proposal.baselinePrompt || "",
    editNote: detail.proposal.editNote || "",
  };
}

function isSelfEvolutionCandidateItem(item: EvolutionLibraryEntry | null | undefined) {
  return item?.ingestMode === "self_evolution_candidate";
}

function proposalDisplaySourceRun(item: EvolutionLibraryEntry | null | undefined) {
  if (!item) {
    return "";
  }
  if (isSelfEvolutionCandidateItem(item)) {
    return item.sourceSelfRunId || item.sourceRun;
  }
  return item.sourceRun;
}

function canOpenProposalSourceRun(item: EvolutionLibraryEntry | null | undefined) {
  return Boolean(item?.sourceRun) && !isSelfEvolutionCandidateItem(item);
}

function compactCaseObject(value: Record<string, unknown> | undefined) {
  if (!value || Object.keys(value).length === 0) {
    return "";
  }
  const text = JSON.stringify(value);
  return text.length > 160 ? `${text.slice(0, 159)}...` : text;
}

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
  } = useAppI18n();
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const evolutionTrack = useShellStore((state) => state.evolutionTrack);
  const setEvolutionTrack = useShellStore((state) => state.setEvolutionTrack);
  const rawEvolutionView = useShellStore((state) => state.evolutionView);
  const setEvolutionView = useShellStore((state) => state.setEvolutionView);
  const evolutionView = forcedView ?? (rawEvolutionView === "overview" ? "live" : rawEvolutionView);
  const selfTrackQueriesEnabled = forcedTrack === "self" || forcedTrack === undefined;
  const supervisedTrackQueriesEnabled = forcedTrack !== "self";
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
  const [datasetLimitInput, setDatasetLimitInput] = useState("");
  const [bundleNameInput, setBundleNameInput] = useState("");
  const [keepWorktree, setKeepWorktree] = useState(false);
  const [liveActiveRun, setLiveActiveRun] = useState<EvolutionActiveRun | null>(null);
  const [worktreeRunFeedback, setWorktreeRunFeedback] = useState("");
  const [selfGoalInput, setSelfGoalInput] = useState("");
  const [selfGoalInitialized, setSelfGoalInitialized] = useState(false);
  const [liveSelfRun, setLiveSelfRun] = useState<SelfEvolutionActiveRun | null>(null);
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
  const [runsQueueWidth, setRunsQueueWidth] = useState(() =>
    storedPaneWidth(
      EVOLUTION_RUNS_QUEUE_WIDTH_KEY,
      EVOLUTION_RUNS_QUEUE_DEFAULT_WIDTH,
      EVOLUTION_RUNS_QUEUE_BOUNDS,
    ),
  );
  const [libraryListWidth, setLibraryListWidth] = useState(() =>
    storedPaneWidth(
      EVOLUTION_LIBRARY_LIST_WIDTH_KEY,
      EVOLUTION_LIBRARY_LIST_DEFAULT_WIDTH,
      EVOLUTION_LIBRARY_LIST_BOUNDS,
    ),
  );
  const [liveLaunchWidth, setLiveLaunchWidth] = useState(() =>
    storedPaneWidth(
      EVOLUTION_LIVE_LAUNCH_WIDTH_KEY,
      EVOLUTION_LIVE_LAUNCH_DEFAULT_WIDTH,
      EVOLUTION_LIVE_LAUNCH_BOUNDS,
    ),
  );
  const [liveRunWidth, setLiveRunWidth] = useState(() =>
    storedPaneWidth(
      EVOLUTION_LIVE_RUN_WIDTH_KEY,
      EVOLUTION_LIVE_RUN_DEFAULT_WIDTH,
      EVOLUTION_LIVE_RUN_BOUNDS,
    ),
  );
  const [liveIoHeight, setLiveIoHeight] = useState(() =>
    storedPaneSize(
      EVOLUTION_LIVE_IO_HEIGHT_KEY,
      EVOLUTION_LIVE_IO_DEFAULT_HEIGHT,
      EVOLUTION_LIVE_IO_HEIGHT_BOUNDS,
    ),
  );
  const configQuery = useQuery({
    queryKey: queryKeys.configPublic(),
    queryFn: () => fetchJson<ConfigSummary>("/api/config/public"),
    refetchInterval: resolvePollingInterval(pageVisible, 8_000),
    refetchIntervalInBackground: false,
  });

  const runsQuery = useQuery({
    queryKey: queryKeys.evolutionRuns(),
    queryFn: () => fetchJson<EvolutionRun[]>("/api/evolution/runs"),
    refetchInterval: resolvePollingInterval(pageVisible, 8_000),
    refetchIntervalInBackground: false,
    enabled: supervisedTrackQueriesEnabled,
  });
  const libraryQuery = useQuery({
    queryKey: queryKeys.evolutionLibrary(),
    queryFn: () => fetchJson<EvolutionLibraryPayload>("/api/evolution/library"),
    refetchInterval: resolvePollingInterval(pageVisible, 8_000),
    refetchIntervalInBackground: false,
    enabled: supervisedTrackQueriesEnabled,
  });
  const workbenchQuery = useQuery({
    queryKey: queryKeys.evolutionWorkbench(),
    queryFn: () => fetchJson<EvolutionWorkbench>("/api/evolution/workbench"),
    refetchInterval: resolvePollingInterval(pageVisible, 8_000),
    refetchIntervalInBackground: false,
    enabled: supervisedTrackQueriesEnabled,
  });
  const overviewQuery = useQuery({
    queryKey: queryKeys.evolutionOverview(),
    queryFn: () => fetchJson<EvolutionOverview>("/api/evolution/overview"),
    refetchInterval: resolvePollingInterval(pageVisible, 8_000),
    refetchIntervalInBackground: false,
    enabled: supervisedTrackQueriesEnabled,
  });
  const activeRunQuery = useQuery({
    queryKey: queryKeys.evolutionActiveRun(),
    queryFn: () => fetchJson<EvolutionActiveRun | null>("/api/evolution/active-run"),
    refetchInterval: resolvePollingInterval(pageVisible, 4_000),
    refetchIntervalInBackground: false,
    enabled: supervisedTrackQueriesEnabled,
  });
  const worktreeActiveRunQuery = useQuery({
    queryKey: queryKeys.evolutionWorktreeActiveRun(),
    queryFn: () => fetchJson<SupervisedWorktreeRun | null>("/api/evolution/worktree-runs/active"),
    refetchInterval: resolvePollingInterval(pageVisible, 4_000),
    refetchIntervalInBackground: false,
    enabled: supervisedTrackQueriesEnabled,
  });
  const selfOverviewQuery = useQuery({
    queryKey: queryKeys.evolutionSelfOverview(),
    queryFn: () => fetchJson<SelfEvolutionOverview>("/api/evolution/self/overview"),
    refetchInterval: resolvePollingInterval(pageVisible, 8_000),
    refetchIntervalInBackground: false,
    enabled: selfTrackQueriesEnabled && (configQuery.data ? configQuery.data.modeAvailability.self_evolution : true),
  });
  const selfLatestRunQuery = useQuery({
    queryKey: queryKeys.evolutionSelfLatestRun(),
    queryFn: () => fetchJson<SelfEvolutionActiveRun | null>("/api/evolution/self/latest-run"),
    refetchInterval: resolvePollingInterval(pageVisible, 4_000),
    refetchIntervalInBackground: false,
    enabled: selfTrackQueriesEnabled && (configQuery.data ? configQuery.data.modeAvailability.self_evolution : true),
  });
  const selfTransactionsQuery = useQuery({
    queryKey: queryKeys.evolutionSelfTransactions(),
    queryFn: () => fetchJson<SelfEvolutionTransaction[]>("/api/evolution/self/transactions"),
    refetchInterval: resolvePollingInterval(pageVisible, 8_000),
    refetchIntervalInBackground: false,
    enabled: selfTrackQueriesEnabled && (configQuery.data ? configQuery.data.modeAvailability.self_evolution : true),
  });
  const startRunMutation = useMutation({
    mutationFn: () =>
      fetchJson<EvolutionActiveRun>("/api/evolution/runs", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          sourceKind,
          datasetName: sourceKind === "dataset" ? datasetName : "",
          datasetLimit:
            sourceKind === "dataset" && datasetLimitInput.trim()
              ? Number(datasetLimitInput.trim())
              : null,
          bundleName: sourceKind === "bundle" ? bundleNameInput : "",
          keepWorktree,
        }),
      }).then((snapshot) => requireEvolutionRunSnapshot(snapshot, "supervised evolution start")),
    onSuccess: async (snapshot) => {
      setActionFeedback("");
      setLiveActiveRun(snapshot);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionWorkbench() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionActiveRun() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionOverview() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionRuns() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionLibrary() }),
      ]);
    },
  });
  const startWorktreeRunMutation = useMutation({
    onMutate: () => {
      setWorktreeRunFeedback("");
    },
    mutationFn: () =>
      fetchJson<SupervisedWorktreeRun>("/api/evolution/worktree-runs", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          sourceKind,
          datasetName: sourceKind === "dataset" ? datasetName : "",
          datasetLimit:
            sourceKind === "dataset" && datasetLimitInput.trim()
              ? Number(datasetLimitInput.trim())
              : null,
          bundleName: sourceKind === "bundle" ? bundleNameInput : "",
          keepWorktree: true,
          mode: currentIntakeMode === "auto" ? "auto" : "manual",
          executionMode: "simulation",
          confirmRealLlmCost: false,
          uiRoute: `${location.pathname}${location.search}`,
          clientAction: "start_supervised_worktree_run",
        }),
      }),
    onSuccess: async (snapshot) => {
      setWorktreeRunFeedback(snapshot.latestMessage || t("startClosedLoopQueued"));
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionWorktreeActiveRun() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionWorktreeRuns() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.runtimeSummary() }),
      ]);
    },
  });
  const invalidateSupervisedEvolution = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.evolutionWorkbench() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.evolutionActiveRun() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.evolutionOverview() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.evolutionRuns() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.evolutionLibrary() }),
    ]);
  };
  const pauseRunMutation = useMutation({
    onMutate: () => {
      setActionFeedback("");
    },
    mutationFn: (runId: string) =>
      fetchJson<EvolutionActiveRun>(`/api/evolution/runs/${runId}/pause`, {
        method: "POST",
      }).then((snapshot) => requireEvolutionRunSnapshot(snapshot, "supervised pause")),
    onSuccess: async (snapshot) => {
      setActionFeedback(snapshot.latestMessage || "");
      setLiveActiveRun(snapshot);
      await invalidateSupervisedEvolution();
    },
  });
  const resumeRunMutation = useMutation({
    onMutate: () => {
      setActionFeedback("");
    },
    mutationFn: (runId: string) =>
      fetchJson<EvolutionActiveRun>(`/api/evolution/runs/${runId}/resume`, {
        method: "POST",
      }).then((snapshot) => requireEvolutionRunSnapshot(snapshot, "supervised resume")),
    onSuccess: async (snapshot) => {
      setActionFeedback(snapshot.latestMessage || "");
      setLiveActiveRun(snapshot);
      await invalidateSupervisedEvolution();
    },
  });
  const terminateRunMutation = useMutation({
    onMutate: () => {
      setActionFeedback("");
    },
    mutationFn: (runId: string) =>
      fetchJson<EvolutionActiveRun>(`/api/evolution/runs/${runId}/terminate`, {
        method: "POST",
      }).then((snapshot) => requireEvolutionRunSnapshot(snapshot, "supervised terminate")),
    onSuccess: async (snapshot) => {
      setActionFeedback(snapshot.latestMessage || snapshot.reason || "");
      setLiveActiveRun(snapshot);
      await invalidateSupervisedEvolution();
    },
  });
  const deleteRunMutation = useMutation({
    onMutate: () => {
      setActionFeedback("");
    },
    mutationFn: (runId: string) =>
      fetchJson<EvolutionRunDeleteResponse>(`/api/evolution/runs/${runId}`, {
        method: "DELETE",
      }),
    onSuccess: async (payload) => {
      setActionFeedback(payload.summary || "");
      setLiveActiveRun(null);
      await invalidateSupervisedEvolution();
    },
  });
  const invalidateSelfEvolution = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.evolutionSelfOverview() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.evolutionSelfActiveRun() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.evolutionSelfLatestRun() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.evolutionSelfTransactions() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.evolutionSelfAudit() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.runtimeSummary() }),
    ]);
  };
  const startSelfRunMutation = useMutation({
    onMutate: () => {
      setSelfActionFeedback("");
    },
    mutationFn: () =>
      fetchJson<SelfEvolutionActiveRun>("/api/evolution/self/runs", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          goal: selfGoalInput.trim(),
        }),
      }).then((snapshot) => requireEvolutionRunSnapshot(snapshot, "self-evolution start")),
    onSuccess: async (snapshot) => {
      setSelfActionFeedback("");
      setLiveSelfRun(snapshot);
      await invalidateSelfEvolution();
    },
  });
  const stopSelfRunMutation = useMutation({
    onMutate: () => {
      setSelfActionFeedback("");
    },
    mutationFn: (runId: string) =>
      fetchJson<SelfEvolutionActiveRun>(`/api/evolution/self/runs/${runId}/terminate`, {
        method: "POST",
      }).then((snapshot) => requireEvolutionRunSnapshot(snapshot, "self-evolution terminate")),
    onSuccess: async (snapshot) => {
      setSelfActionFeedback(snapshot.latestMessage || snapshot.stopReason || "");
      setLiveSelfRun(snapshot);
      await invalidateSelfEvolution();
    },
  });
  const pauseSelfRunMutation = useMutation({
    onMutate: () => {
      setSelfActionFeedback("");
    },
    mutationFn: (runId: string) =>
      fetchJson<SelfEvolutionActiveRun>(`/api/evolution/self/runs/${runId}/pause`, {
        method: "POST",
      }).then((snapshot) => requireEvolutionRunSnapshot(snapshot, "self-evolution pause")),
    onSuccess: async (snapshot) => {
      setSelfActionFeedback(snapshot.latestMessage || snapshot.stopReason || "");
      setLiveSelfRun(snapshot);
      await invalidateSelfEvolution();
    },
  });
  const resumeSelfRunMutation = useMutation({
    onMutate: () => {
      setSelfActionFeedback("");
    },
    mutationFn: (runId: string) =>
      fetchJson<SelfEvolutionActiveRun>(`/api/evolution/self/runs/${runId}/resume`, {
        method: "POST",
      }).then((snapshot) => requireEvolutionRunSnapshot(snapshot, "self-evolution resume")),
    onSuccess: async (snapshot) => {
      setSelfActionFeedback(snapshot.latestMessage || "");
      setLiveSelfRun(snapshot);
      await invalidateSelfEvolution();
    },
  });
  const rollbackSelfRunMutation = useMutation({
    onMutate: () => {
      setSelfActionFeedback("");
    },
    mutationFn: (runId: string) =>
      fetchJson<SelfEvolutionActiveRun>(`/api/evolution/self/runs/${runId}/rollback`, {
        method: "POST",
      }).then((snapshot) => requireEvolutionRunSnapshot(snapshot, "self-evolution rollback")),
    onSuccess: async (snapshot) => {
      setSelfActionFeedback(snapshot.rollback?.reason || snapshot.latestMessage || "");
      setLiveSelfRun(snapshot);
      await invalidateSelfEvolution();
    },
  });
  const handoffSelfRunMutation = useMutation({
    onMutate: () => {
      setSelfActionFeedback("");
    },
    mutationFn: (runId: string) =>
      fetchJson<SelfEvolutionHandoffResponse>(`/api/evolution/self/runs/${runId}/handoff`, {
        method: "POST",
      }),
    onSuccess: async (payload) => {
      setSelfActionFeedback(payload.message || "");
      if (payload.run) {
        setLiveSelfRun(requireEvolutionRunSnapshot(payload.run, "self-evolution handoff"));
      }
      await Promise.all([
        invalidateSelfEvolution(),
        queryClient.invalidateQueries({ queryKey: queryKeys.sessions() }),
      ]);
      if (payload.status === "ready" && payload.content) {
        savePendingSelfEvolutionHandoff({
          sessionId: payload.sessionId || "",
          content: payload.content,
        });
        void navigate("/chat");
      }
    },
  });
  const deleteSelfHistoryMutation = useMutation({
    onMutate: () => {
      setSelfActionFeedback("");
    },
    mutationFn: (txnIds: string[]) =>
      fetchJson<SelfEvolutionHistoryDeleteResponse>("/api/evolution/self/history/delete", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ txnIds }),
      }),
    onSuccess: async (payload) => {
      setSelfActionFeedback(payload.summary || "");
      await invalidateSelfEvolution();
    },
  });
  const actionMutation = useMutation({
    mutationFn: (variables: { sessionId: string; action: string }) =>
      fetchJson<EvolutionRunActionResponse>(`/api/evolution/runs/${variables.sessionId}/actions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ action: variables.action }),
      }),
    onSuccess: async (payload) => {
      setActionFeedback(payload.summary);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionOverview() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionRuns() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionLibrary() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionWorkbench() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionActiveRun() }),
      ]);
    },
  });
  const runs = runsQuery.data ?? EMPTY_RUNS;
  const libraryItems = libraryQuery.data?.items ?? EMPTY_LIBRARY_ENTRIES;
  const pendingItems = libraryQuery.data?.pending ?? EMPTY_LIBRARY_ENTRIES;
  const overview = overviewQuery.data;
  const workbenchControl = workbenchQuery.data;
  const workbenchState = overview?.workbench ?? workbenchControl?.savedState;
  const activeRunSnapshot = selectRunSnapshotWithRunId(activeRunQuery.data);
  const activeWorktreeRun = worktreeActiveRunQuery.data ?? null;
  const latestSelfRunSnapshot = selectRunSnapshotWithRunId(selfLatestRunQuery.data);
  const latestRun = runs[0] ?? null;
  const selfTrackEnabled = configQuery.data?.modeAvailability.self_evolution ?? false;
  const supervisedTrackEnabled = configQuery.data?.modeAvailability.supervised_evolution ?? true;
  const activeTrack = forcedTrack ?? (
    evolutionTrack === "self" && selfTrackEnabled
      ? "self"
      : supervisedTrackEnabled
        ? "supervised"
        : selfTrackEnabled
          ? "self"
          : "supervised"
  );
  const showTrackToggle = !forcedTrack && selfTrackEnabled && supervisedTrackEnabled;
  const routeEyebrow = activeTrack === "self" ? t("navSelfEvolution") : t("navSupervisedEvolution");
  const routeTitle =
    activeTrack === "self" ? t("selfEvolutionMode") : t("supervisedEvolutionMode");
  const routeSubtitle =
    activeTrack === "self" ? t("selfEvolutionSubtitle") : t("supervisedEvolutionSubtitle");
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
  const monitoredRun = effectiveActiveRunSnapshot
    ?? (liveActiveRun && ["done", "failed", "cancelled"].includes(String(liveActiveRun.status || "").toLowerCase())
      ? liveActiveRun
      : null);
  const runningRun = effectiveActiveRunSnapshot ?? (liveActiveRun && isLiveSupervisedRunStatus(liveActiveRun.status)
    ? liveActiveRun
    : null);
  const runLocked = Boolean(runningRun && isLiveSupervisedRunStatus(runningRun.status));
  const worktreeRunLocked = Boolean(
    activeWorktreeRun
    && ["queued", "running", "paused", "stopping"].includes(String(activeWorktreeRun.status || "").toLowerCase()),
  );
  const monitoredRunStatus = String(monitoredRun?.status || "").toLowerCase();
  const monitoredCaseTranscript = monitoredRun?.currentCaseIo?.transcript ?? [];
  const monitoredCaseHasOutput = Boolean(
    monitoredRun?.currentCaseIo?.latestOutput || monitoredCaseTranscript.length > 0,
  );
  const monitoredCaseHasVisibleIo = Boolean(
    monitoredRun?.currentCasePrompt || monitoredRun?.currentCaseIo?.latestInput || monitoredCaseHasOutput,
  );
  const runPauseRequested = Boolean(monitoredRun?.pauseRequested) && monitoredRunStatus !== "paused";
  const runPaused = monitoredRunStatus === "paused";
  const runStopping = monitoredRunStatus === "stopping" || Boolean(monitoredRun?.stopRequested);
  const monitoredRunIdentity = monitoredRun?.sessionId || monitoredRun?.runId || "";
  const monitoredCaseLabel = monitoredRun?.currentCaseId
    ? `${monitoredRun.currentCaseIndex ?? "--"}/${monitoredRun.caseTotal ?? "--"} ${monitoredRun.currentCaseId}`
    : "--";
  const monitoredTaskLabel = monitoredRun?.currentTask || monitoredRun?.latestMessage || "--";
  const pauseSupervisedAction = monitoredRun?.actionStates?.pause;
  const resumeSupervisedAction = monitoredRun?.actionStates?.resume;
  const terminateSupervisedAction = monitoredRun?.actionStates?.terminate;
  const deleteSupervisedAction = monitoredRun?.actionStates?.delete;
  const canPauseSupervisedRun = Boolean(monitoredRun && pauseSupervisedAction?.enabled);
  const canResumeSupervisedRun = Boolean(monitoredRun && resumeSupervisedAction?.enabled);
  const canTerminateSupervisedRun = Boolean(monitoredRun && terminateSupervisedAction?.enabled);
  const canDeleteSupervisedRun = Boolean(monitoredRun && deleteSupervisedAction?.enabled);
  const supervisedControlError =
    pauseRunMutation.error?.message
    ?? resumeRunMutation.error?.message
    ?? terminateRunMutation.error?.message
    ?? deleteRunMutation.error?.message
    ?? startRunMutation.error?.message
    ?? startWorktreeRunMutation.error?.message
    ?? "";
  const monitoredSelfRun = latestSelfRunSnapshot ?? liveSelfRun;
  const lockedSelfRun =
    monitoredSelfRun
    && isSelfRunLockedStatus(monitoredSelfRun.status || "")
      ? monitoredSelfRun
      : null;
  const selfRunLocked = Boolean(lockedSelfRun);
  const selectedDataset = workbenchControl?.datasets.find((item) => item.name === datasetName) ?? null;
  const availableBundles = workbenchControl?.bundles ?? [];
  const selectedBundleExists = availableBundles.some((item) => item.name === bundleNameInput);
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
    refetchInterval: resolvePollingInterval(pageVisible, 8_000),
    refetchIntervalInBackground: false,
  });
  const updateProposalMutation = useMutation({
    mutationFn: ({ sessionId, draft }: { sessionId: string; draft: ProposalEditDraft }) =>
      fetchJson<EvolutionProposalUpdateResponse>(`/api/evolution/proposals/${sessionId}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(draft),
      }),
    onSuccess: async (payload) => {
      setProposalEditFeedback(payload.summary);
      setProposalEditDraft(proposalEditDraftFromDetail(payload.proposal));
      if (payload.updated) {
        setProposalEditOpen(false);
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionOverview() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionRuns() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionLibrary() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionProposal(payload.sessionId) }),
      ]);
    },
  });
  const deleteProposalMutation = useMutation({
    mutationFn: (sessionId: string) =>
      fetchJson<EvolutionProposalDeleteResponse>(`/api/evolution/proposals/${sessionId}`, {
        method: "DELETE",
      }),
    onSuccess: async (payload) => {
      setLibraryFeedback(payload.summary);
      setSelectedProposalRunIds((current) => current.filter((item) => item !== payload.sessionId));
      if (selectedRunId === payload.sessionId) {
        setSelectedRunId(null);
      }
      if (selectedLibraryItemId === payload.sessionId) {
        setSelectedLibraryItemId(null);
      }
      if (selectedPendingItemId === payload.sessionId) {
        setSelectedPendingItemId(null);
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionOverview() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionRuns() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionLibrary() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionProposal(payload.sessionId) }),
      ]);
    },
  });
  const bulkDeleteMutation = useMutation({
    mutationFn: (sessionIds: string[]) =>
      fetchJson<EvolutionProposalBulkDeleteResponse>("/api/evolution/proposals/delete", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ sessionIds }),
      }),
    onSuccess: async (payload) => {
      setLibraryFeedback(payload.summary);
      setSelectedProposalRunIds([]);
      if (
        selectedProposalRunId
        && payload.results.some(
          (item) => item.sessionId === selectedProposalRunId && item.status === "deleted",
        )
      ) {
        if (libraryView === "items") {
          setSelectedLibraryItemId(null);
        } else {
          setSelectedPendingItemId(null);
        }
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionOverview() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionRuns() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionLibrary() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionProposal(selectedProposalRunId ?? "__none__") }),
      ]);
    },
  });
  const deleteRunRecordMutation = useMutation({
    mutationFn: (sessionId: string) =>
      fetchJson<EvolutionProposalDeleteResponse>(`/api/evolution/proposals/${sessionId}`, {
        method: "DELETE",
      }),
    onSuccess: async (payload) => {
      setRunRecordsFeedback(payload.summary);
      setSelectedRunIds((current) => current.filter((item) => item !== payload.sessionId));
      setSelectedProposalRunIds((current) => current.filter((item) => item !== payload.sessionId));
      if (selectedRunId === payload.sessionId) {
        setSelectedRunId(null);
      }
      if (selectedLibraryItemId === payload.sessionId) {
        setSelectedLibraryItemId(null);
      }
      if (selectedPendingItemId === payload.sessionId) {
        setSelectedPendingItemId(null);
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionOverview() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionRuns() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionLibrary() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionProposal(payload.sessionId) }),
      ]);
    },
  });
  const bulkDeleteRunRecordsMutation = useMutation({
    mutationFn: (sessionIds: string[]) =>
      fetchJson<EvolutionProposalBulkDeleteResponse>("/api/evolution/proposals/delete", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ sessionIds }),
      }),
    onSuccess: async (payload) => {
      const deletedIds = new Set(
        payload.results
          .filter((item) => item.status === "deleted")
          .map((item) => item.sessionId),
      );
      setRunRecordsFeedback(payload.summary);
      setSelectedRunIds([]);
      setSelectedProposalRunIds((current) => current.filter((item) => !deletedIds.has(item)));
      if (selectedRunId && deletedIds.has(selectedRunId)) {
        setSelectedRunId(null);
      }
      if (selectedLibraryItemId && deletedIds.has(selectedLibraryItemId)) {
        setSelectedLibraryItemId(null);
      }
      if (selectedPendingItemId && deletedIds.has(selectedPendingItemId)) {
        setSelectedPendingItemId(null);
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionOverview() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionRuns() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionLibrary() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionProposal(selectedRunId ?? "__none__") }),
      ]);
    },
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
    setDatasetName(savedState.datasetName || workbenchControl.datasets[0]?.name || "");
    setDatasetLimitInput(toLimitInput(savedState.datasetLimit));
    setBundleNameInput(savedBundle);
    setKeepWorktree(Boolean(savedState.keepWorktree));
    setFormInitialized(true);
  }, [formInitialized, workbenchControl]);

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
    if (selfGoalInitialized || !selfOverviewQuery.data?.goal) {
      return;
    }
    setSelfGoalInput(selfOverviewQuery.data.goal);
    setSelfGoalInitialized(true);
  }, [selfGoalInitialized, selfOverviewQuery.data?.goal]);

  useEffect(() => {
    if (latestSelfRunSnapshot) {
      setLiveSelfRun(latestSelfRunSnapshot);
      return;
    }
    setLiveSelfRun((current) => {
      if (current && !isSelfRunLockedStatus(current.status || "")) {
        return current;
      }
      return null;
    });
  }, [latestSelfRunSnapshot]);

  useEffect(() => {
    if (!pageVisible) {
      return;
    }
    const target = monitoredSelfRun;
    if (!target || !isSelfRunExecutingStatus(target.status || "")) {
      return;
    }
    if (typeof EventSource === "undefined") {
      return;
    }

    const source = new EventSource(`/api/evolution/self/runs/${target.runId}/events`);
    const handleSnapshot = (message: MessageEvent) => {
      const snapshot = parseRunStreamSnapshot<SelfEvolutionActiveRun>(message.data, "self-evolution stream");
      if (!snapshot) {
        return;
      }
      const payload = JSON.parse(message.data) as SelfEvolutionRunStreamEvent;
      setLiveSelfRun(snapshot);
      if (payload.terminal) {
        void Promise.all([
          queryClient.invalidateQueries({ queryKey: queryKeys.evolutionSelfOverview() }),
          queryClient.invalidateQueries({ queryKey: queryKeys.evolutionSelfActiveRun() }),
          queryClient.invalidateQueries({ queryKey: queryKeys.evolutionSelfLatestRun() }),
          queryClient.invalidateQueries({ queryKey: queryKeys.evolutionSelfTransactions() }),
          queryClient.invalidateQueries({ queryKey: queryKeys.evolutionSelfAudit() }),
          queryClient.invalidateQueries({ queryKey: queryKeys.runtimeSummary() }),
        ]);
        source.close();
      }
    };

    source.addEventListener("self_evolution_run", handleSnapshot as EventListener);
    source.onerror = () => {
      source.close();
      void queryClient.invalidateQueries({ queryKey: queryKeys.evolutionSelfLatestRun() });
    };

    return () => {
      source.removeEventListener("self_evolution_run", handleSnapshot as EventListener);
      source.close();
    };
  }, [monitoredSelfRun?.runId, monitoredSelfRun?.status, pageVisible, queryClient]);

  useEffect(() => {
    if (!pageVisible) {
      return;
    }
    const target = selectSupervisedRunStreamTarget(activeRunSnapshot, liveActiveRun);
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
        void Promise.all([
          queryClient.invalidateQueries({ queryKey: queryKeys.evolutionActiveRun() }),
          queryClient.invalidateQueries({ queryKey: queryKeys.evolutionOverview() }),
          queryClient.invalidateQueries({ queryKey: queryKeys.evolutionRuns() }),
          queryClient.invalidateQueries({ queryKey: queryKeys.evolutionLibrary() }),
          queryClient.invalidateQueries({ queryKey: queryKeys.evolutionWorkbench() }),
        ]);
        source.close();
      }
    };

    source.addEventListener("supervised_run", handleSnapshot as EventListener);
    source.onerror = () => {
      source.close();
      void queryClient.invalidateQueries({ queryKey: queryKeys.evolutionActiveRun() });
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
    queryClient,
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

  useEffect(() => {
    window.localStorage.setItem(EVOLUTION_RUNS_QUEUE_WIDTH_KEY, String(runsQueueWidth));
  }, [runsQueueWidth]);

  useEffect(() => {
    window.localStorage.setItem(EVOLUTION_LIBRARY_LIST_WIDTH_KEY, String(libraryListWidth));
  }, [libraryListWidth]);

  useEffect(() => {
    window.localStorage.setItem(EVOLUTION_LIVE_LAUNCH_WIDTH_KEY, String(liveLaunchWidth));
  }, [liveLaunchWidth]);

  useEffect(() => {
    window.localStorage.setItem(EVOLUTION_LIVE_RUN_WIDTH_KEY, String(liveRunWidth));
  }, [liveRunWidth]);

  useEffect(() => {
    window.localStorage.setItem(EVOLUTION_LIVE_IO_HEIGHT_KEY, String(liveIoHeight));
  }, [liveIoHeight]);

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
        "--evolution-runs-queue-width": `${runsQueueWidth}px`,
      }) as CSSProperties,
    [runsQueueWidth],
  );
  const libraryWorkspaceStyle = useMemo(
    () =>
      ({
        "--evolution-library-list-width": `${libraryListWidth}px`,
      }) as CSSProperties,
    [libraryListWidth],
  );
  const liveWorkspaceStyle = useMemo(
    () =>
      ({
        "--evolution-live-launch-width": `${liveLaunchWidth}px`,
        "--evolution-live-run-width": `${liveRunWidth}px`,
        "--evolution-live-io-height": `${liveIoHeight}px`,
      }) as CSSProperties,
    [liveIoHeight, liveLaunchWidth, liveRunWidth],
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
    return normalized || "--";
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
      const decisionText = event.decision ? decisionLabel(event.decision) : "--";
      return lang === "zh"
        ? `监督结论为 ${decisionText}${reasonText ? `，原因：${reasonText}` : ""}。`
        : `The supervised decision is ${decisionText}${reasonText ? `, reason: ${reasonText}` : ""}.`;
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

  function beginPaneResize(
    startX: number,
    startWidth: number,
    bounds: typeof EVOLUTION_RUNS_QUEUE_BOUNDS,
    setWidth: (value: number) => void,
    inverted = false,
  ) {
    const handleMove = (moveEvent: globalThis.PointerEvent) => {
      const delta = moveEvent.clientX - startX;
      setWidth(clampPaneWidth(startWidth + (inverted ? -delta : delta), bounds));
    };
    const handleEnd = () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleEnd);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleEnd);
  }

  function beginPaneHeightResize(
    startY: number,
    startHeight: number,
    bounds: typeof EVOLUTION_LIVE_IO_HEIGHT_BOUNDS,
    setHeight: (value: number) => void,
  ) {
    const handleMove = (moveEvent: globalThis.PointerEvent) => {
      setHeight(clampPaneSize(startHeight + moveEvent.clientY - startY, bounds));
    };
    const handleEnd = () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleEnd);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    document.body.style.cursor = "row-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleEnd);
  }

  function handleRunsResizeStart(event: PointerEvent<HTMLButtonElement>) {
    if (event.button !== 0) {
      return;
    }
    event.preventDefault();
    beginPaneResize(event.clientX, runsQueueWidth, EVOLUTION_RUNS_QUEUE_BOUNDS, setRunsQueueWidth);
  }

  function handleRunsResizeKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    const nextWidth = keyboardPaneWidth(runsQueueWidth, event.key, EVOLUTION_RUNS_QUEUE_BOUNDS);
    if (nextWidth === null) {
      return;
    }
    event.preventDefault();
    setRunsQueueWidth(nextWidth);
  }

  function handleLiveLaunchResizeStart(event: PointerEvent<HTMLButtonElement>) {
    if (event.button !== 0) {
      return;
    }
    event.preventDefault();
    beginPaneResize(event.clientX, liveLaunchWidth, EVOLUTION_LIVE_LAUNCH_BOUNDS, setLiveLaunchWidth);
  }

  function handleLiveLaunchResizeKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    const nextWidth = keyboardPaneWidth(liveLaunchWidth, event.key, EVOLUTION_LIVE_LAUNCH_BOUNDS);
    if (nextWidth === null) {
      return;
    }
    event.preventDefault();
    setLiveLaunchWidth(nextWidth);
  }

  function handleLiveRunResizeStart(event: PointerEvent<HTMLButtonElement>) {
    if (event.button !== 0) {
      return;
    }
    event.preventDefault();
    beginPaneResize(event.clientX, liveRunWidth, EVOLUTION_LIVE_RUN_BOUNDS, setLiveRunWidth, true);
  }

  function handleLiveRunResizeKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    const nextWidth = keyboardPaneWidth(liveRunWidth, event.key, EVOLUTION_LIVE_RUN_BOUNDS, true);
    if (nextWidth === null) {
      return;
    }
    event.preventDefault();
    setLiveRunWidth(nextWidth);
  }

  function handleLiveIoResizeStart(event: PointerEvent<HTMLButtonElement>) {
    if (event.button !== 0) {
      return;
    }
    event.preventDefault();
    beginPaneHeightResize(event.clientY, liveIoHeight, EVOLUTION_LIVE_IO_HEIGHT_BOUNDS, setLiveIoHeight);
  }

  function handleLiveIoResizeKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    const nextHeight = keyboardPaneHeight(liveIoHeight, event.key, EVOLUTION_LIVE_IO_HEIGHT_BOUNDS);
    if (nextHeight === null) {
      return;
    }
    event.preventDefault();
    setLiveIoHeight(nextHeight);
  }

  function handleLibraryResizeStart(event: PointerEvent<HTMLButtonElement>) {
    if (event.button !== 0) {
      return;
    }
    event.preventDefault();
    beginPaneResize(event.clientX, libraryListWidth, EVOLUTION_LIBRARY_LIST_BOUNDS, setLibraryListWidth);
  }

  function handleLibraryResizeKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    const nextWidth = keyboardPaneWidth(libraryListWidth, event.key, EVOLUTION_LIBRARY_LIST_BOUNDS);
    if (nextWidth === null) {
      return;
    }
    event.preventDefault();
    setLibraryListWidth(nextWidth);
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
          <p>{item.reason || item.outcomeSemantics.runtimeExplanation}</p>
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
          <p className={styles.noticeText}>{item.outcomeSemantics.runtimeExplanation}</p>
        </div>

        <div className={styles.detailSection}>
          <h3>{t("currentStateTitle")}</h3>
          <div className={styles.relatedList}>
            <article className={styles.relatedRow}>
              <strong>review_state</strong>
              <span>{item.reviewState || "--"}</span>
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
    <div className={styles.page}>
      <section className={styles.toolbar}>
        <div className={styles.toolbarIntro}>
          <p className={styles.eyebrow}>{routeEyebrow}</p>
          <h1 className={styles.title}>{routeTitle}</h1>
          <p className={styles.subtitle}>{routeSubtitle}</p>
        </div>

        <div className={styles.toolbarControls}>
          {showTrackToggle ? (
            <div className={styles.segmented}>
              {([
                { key: "supervised", label: t("supervisedEvolutionMode") },
                { key: "self", label: t("selfEvolutionMode") },
              ] as const).map((track) => (
                <button
                  key={track.key}
                  type="button"
                  className={
                    activeTrack === track.key
                      ? `${styles.segmentButton} ${styles.segmentButtonActive}`
                      : styles.segmentButton
                  }
                  onClick={() => setEvolutionTrack(track.key)}
                >
                  {track.label}
                </button>
              ))}
            </div>
          ) : null}

          {activeTrack === "supervised" ? (
            <SupervisedWorkspaceControls
              activeView={evolutionView}
              overviewIntakeMode={overview?.intakeMode}
              configIntakeMode={configQuery.data?.intakeMode}
            />
          ) : null}
        </div>
      </section>

      {activeTrack === "self" ? (
        <SelfEvolutionTrack
          overview={selfOverviewQuery.data}
          latestRun={monitoredSelfRun}
          goalInput={selfGoalInput}
          onGoalInputChange={setSelfGoalInput}
          onStartRun={() => startSelfRunMutation.mutate()}
          onPauseRun={() => monitoredSelfRun && pauseSelfRunMutation.mutate(monitoredSelfRun.runId)}
          onResumeRun={() => monitoredSelfRun && resumeSelfRunMutation.mutate(monitoredSelfRun.runId)}
          onTerminateRun={() => monitoredSelfRun && stopSelfRunMutation.mutate(monitoredSelfRun.runId)}
          onRollbackRun={() => monitoredSelfRun && rollbackSelfRunMutation.mutate(monitoredSelfRun.runId)}
          onHandoffRun={() => monitoredSelfRun && handoffSelfRunMutation.mutate(monitoredSelfRun.runId)}
          onDeleteHistoryGroups={(txnIds) => deleteSelfHistoryMutation.mutate(txnIds)}
          startPending={startSelfRunMutation.isPending}
          pausePending={pauseSelfRunMutation.isPending}
          resumePending={resumeSelfRunMutation.isPending}
          terminatePending={stopSelfRunMutation.isPending}
          rollbackPending={rollbackSelfRunMutation.isPending}
          handoffPending={handoffSelfRunMutation.isPending}
          deleteHistoryPending={deleteSelfHistoryMutation.isPending}
          startError={startSelfRunMutation.error?.message ?? ""}
          pauseError={pauseSelfRunMutation.error?.message ?? ""}
          resumeError={resumeSelfRunMutation.error?.message ?? ""}
          terminateError={stopSelfRunMutation.error?.message ?? ""}
          rollbackError={rollbackSelfRunMutation.error?.message ?? ""}
          handoffError={handoffSelfRunMutation.error?.message ?? ""}
          deleteHistoryError={deleteSelfHistoryMutation.error?.message ?? ""}
          actionFeedback={selfActionFeedback}
          runLocked={selfRunLocked}
          transactions={selfTransactionsQuery.data ?? []}
          loading={selfOverviewQuery.isLoading || selfLatestRunQuery.isLoading || selfTransactionsQuery.isLoading}
        />
      ) : null}

      {activeTrack === "supervised" && evolutionView === "live" ? (
        <div className={styles.overviewGrid} style={liveWorkspaceStyle}>
          <section className={`${styles.surface} ${styles.launchSurface} ${styles.dashboardLaunch}`}>
            <div className={styles.surfaceHeaderCompact}>
              <div>
                <p className={styles.eyebrow}>{t("supervisedControl")}</p>
                <h2 className={styles.sectionTitle}>{t("launchSupervisedRun")}</h2>
              </div>
              <span className={styles.secondaryPill}>
                {sourceKindLabel(sourceKind)}
              </span>
            </div>
            <p className={styles.noticeText}>{t("launchSupervisedRunHint")}</p>

            <div className={styles.metricStrip}>
              <article className={styles.stripItem}>
                <span>{t("availableDatasets")}</span>
                <strong>{workbenchState?.availableDatasets ?? 0}</strong>
              </article>
              <article className={styles.stripItem}>
                <span>{t("runnableDatasets")}</span>
                <strong>{workbenchState?.runnableDatasets ?? 0}</strong>
              </article>
              <article className={styles.stripItem}>
                <span>{t("blockedDatasets")}</span>
                <strong>{workbenchState?.blockedDatasets ?? 0}</strong>
              </article>
            </div>

              <div className={styles.segmented}>
                {(["dataset", "bundle"] as const).map((value) => (
                  <button
                    key={value}
                    type="button"
                    className={
                      sourceKind === value
                        ? `${styles.segmentButton} ${styles.segmentButtonActive}`
                        : styles.segmentButton
                    }
                    onClick={() => setSourceKind(value)}
                  >
                    {sourceKindLabel(value)}
                  </button>
                ))}
              </div>

              <div className={styles.formGrid}>
                {sourceKind === "dataset" ? (
                  <>
                    <div className={styles.compactFieldGrid}>
                      <div className={styles.formField}>
                        <label htmlFor="supervised-dataset">{t("selectedDataset")}</label>
                        <select
                          id="supervised-dataset"
                          className={styles.selectInput}
                          value={datasetName}
                          onChange={(event) => setDatasetName(event.target.value)}
                        >
                          {workbenchControl?.datasets.map((item) => (
                            <option key={item.name} value={item.name}>
                              {item.name} [{datasetUsabilityLabel(item, lang)}]
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className={styles.formField}>
                        <label htmlFor="supervised-limit">{t("caseLimit")}</label>
                        <input
                          id="supervised-limit"
                          className={styles.textInput}
                          type="number"
                          min={1}
                          placeholder="all"
                          value={datasetLimitInput}
                          onChange={(event) => setDatasetLimitInput(event.target.value)}
                        />
                      </div>
                    </div>
                    {selectedDataset ? (
                      <div className={styles.datasetMetaCompact}>
                        <div className={styles.listRowTop}>
                          <strong>{selectedDataset.bundleName}</strong>
                          <span className={styles.secondaryPill}>
                            {datasetUsabilityLabel(selectedDataset, lang)}
                          </span>
                        </div>
                        <p>{selectedDataset.description}</p>
                        <div className={styles.metaRow}>
                          <span>{lang === "zh" ? "样本数" : "Cases"}</span>
                          <span>{selectedDataset.caseCount ?? "--"}</span>
                        </div>
                        {selectedDataset.usabilityReason ? (
                          <div className={styles.metaRow}>
                            <span>{lang === "zh" ? "状态" : "Status"}</span>
                            <span>{selectedDataset.usabilityReason}</span>
                          </div>
                        ) : null}
                        <div className={styles.metaRow}>
                          <span>{lang === "zh" ? "来源" : "Source"}</span>
                          <span>{selectedDataset.sourceTrack || "--"}</span>
                        </div>
                        <div className={styles.signalRow}>
                          {selectedDataset.reviewRequired ? (
                            <span className={styles.secondaryPill}>
                              {lang === "zh" ? "需审核" : "review required"}
                            </span>
                          ) : null}
                          {!selectedDataset.holdoutAllowed ? (
                            <span className={styles.secondaryPill}>
                              {lang === "zh" ? "不进 holdout" : "no holdout"}
                            </span>
                          ) : null}
                          {!selectedDataset.rawChatDirectTrainingAllowed ? (
                            <span className={styles.secondaryPill}>
                              {lang === "zh" ? "raw chat 不直训" : "no raw-chat training"}
                            </span>
                          ) : null}
                        </div>
                        {selectedDataset.allowedDownstreamUses.length > 0 ? (
                          <div className={styles.metaRow}>
                            <span>{lang === "zh" ? "下游用途" : "Downstream"}</span>
                            <span>{selectedDataset.allowedDownstreamUses.join(", ")}</span>
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                  </>
                ) : (
                  <div className={styles.formField}>
                    <label htmlFor="supervised-bundle">{t("selectedBundle")}</label>
                    <select
                      id="supervised-bundle"
                      className={styles.selectInput}
                      value={bundleNameInput}
                      onChange={(event) => setBundleNameInput(event.target.value)}
                    >
                      {availableBundles.map((item) => (
                        <option key={item.name} value={item.name}>
                          {item.name} [{item.caseCount} cases]
                        </option>
                      ))}
                    </select>
                    {!selectedBundleExists ? (
                      <p className={styles.errorTextCompact}>
                        {lang === "zh" ? "请选择一个存在的监督 bundle。" : "Choose an existing supervised bundle."}
                      </p>
                    ) : null}
                  </div>
                )}

                <label className={styles.checkboxRow}>
                  <input
                    type="checkbox"
                    checked={keepWorktree}
                    onChange={(event) => setKeepWorktree(event.target.checked)}
                  />
                  <span className={styles.checkboxLabel}>{t("keepWorktreeLabel")}</span>
                </label>
              </div>

              <div className={styles.controlFooter}>
                <div className={styles.controlActions}>
                  <button
                    type="button"
                    className={styles.inlineAction}
                    disabled={
                      runLocked
                      || worktreeRunLocked
                      || startRunMutation.isPending
                      || (sourceKind === "bundle" && !selectedBundleExists)
                    }
                    onClick={() => startRunMutation.mutate()}
                  >
                    {startRunMutation.isPending ? <LoaderCircle size={15} /> : <Play size={15} />}
                    {t("startSupervisedRun")}
                  </button>
                  <button
                    type="button"
                    className={styles.inlineAction}
                    disabled={
                      runLocked
                      || worktreeRunLocked
                      || startWorktreeRunMutation.isPending
                      || (sourceKind === "bundle" && !selectedBundleExists)
                    }
                    onClick={() => startWorktreeRunMutation.mutate()}
                    title={t("startClosedLoopHint")}
                  >
                    {startWorktreeRunMutation.isPending ? <LoaderCircle size={15} /> : <Sparkles size={15} />}
                    {t("startClosedLoopRun")}
                  </button>
                </div>
                {activeWorktreeRun ? (
                  <div className={styles.closedLoopStatus}>
                    <span className={styles.secondaryPill}>{t("closedLoopActive")}</span>
                    <strong>{activeWorktreeRun.status || "--"}</strong>
                    <span>{activeWorktreeRun.latestMessage || activeWorktreeRun.phase || "--"}</span>
                  </div>
                ) : null}
                {worktreeRunFeedback ? <p className={styles.noticeText}>{worktreeRunFeedback}</p> : null}
                {runLocked || worktreeRunLocked ? <p className={styles.noticeText}>{t("runningLockHint")}</p> : null}
                {supervisedControlError ? (
                  <p className={styles.errorText}>{supervisedControlError}</p>
                ) : null}
              </div>
          </section>

          <button
            type="button"
            className={`${styles.resizeHandle} ${styles.liveResizeHandle} ${styles.liveResizeHandleLaunch}`}
            aria-label={resizeLiveLaunchLabel}
            title={resizeLiveLaunchLabel}
            onPointerDown={handleLiveLaunchResizeStart}
            onKeyDown={handleLiveLaunchResizeKeyDown}
          />

          <section className={`${styles.surface} ${styles.liveSurface} ${styles.dashboardRun}`}>
              <div className={styles.surfaceHeaderCompact}>
                <div>
                  <p className={styles.eyebrow}>{t("activeSupervisedRun")}</p>
                  <h2 className={`${styles.sectionTitle} ${styles.truncateText}`} title={monitoredRunIdentity || undefined}>
                    {monitoredRunIdentity || t("activeSupervisedRun")}
                  </h2>
                </div>
                {monitoredRun ? (
                  <div className={styles.liveStatusRow}>
                    <span className={styles.statusPill}>{statusLabel(monitoredRun.status)}</span>
                    <span className={styles.secondaryPill}>{sourceKindLabel(monitoredRun.sourceKind)}</span>
                  </div>
                ) : (
                  <span className={styles.secondaryPill}>
                    {workbenchSourceLabel(workbenchState?.source ?? "unknown")}
                  </span>
                )}
              </div>

              {monitoredRun ? (
                <div className={styles.runMonitorDense}>
                  <div className={styles.liveRunToolbar}>
                    <div className={styles.compactActionGroup}>
                      <button
                        type="button"
                        className={styles.compactIconAction}
                        disabled={!canPauseSupervisedRun || pauseRunMutation.isPending}
                        title={disabledReason(pauseSupervisedAction) || t("pauseSupervisedRun")}
                        onClick={() => monitoredRun && pauseRunMutation.mutate(monitoredRun.runId)}
                        aria-label={t("pauseSupervisedRun")}
                      >
                        {pauseRunMutation.isPending ? <LoaderCircle size={15} /> : <Pause size={15} />}
                      </button>
                      <button
                        type="button"
                        className={styles.compactIconAction}
                        disabled={!canResumeSupervisedRun || resumeRunMutation.isPending}
                        title={disabledReason(resumeSupervisedAction) || t("resumeSupervisedRun")}
                        onClick={() => monitoredRun && resumeRunMutation.mutate(monitoredRun.runId)}
                        aria-label={t("resumeSupervisedRun")}
                      >
                        {resumeRunMutation.isPending ? <LoaderCircle size={15} /> : <Play size={15} />}
                      </button>
                      <button
                        type="button"
                        className={styles.compactIconAction}
                        disabled={!canTerminateSupervisedRun || terminateRunMutation.isPending}
                        title={disabledReason(terminateSupervisedAction) || t("terminateSupervisedRun")}
                        onClick={() => monitoredRun && terminateRunMutation.mutate(monitoredRun.runId)}
                        aria-label={t("terminateSupervisedRun")}
                      >
                        {terminateRunMutation.isPending ? <LoaderCircle size={15} /> : <Square size={15} />}
                      </button>
                    </div>
                    <div className={styles.compactActionGroup}>
                      {monitoredRun.sessionId ? (
                        <button
                          type="button"
                          className={styles.compactTextAction}
                          onClick={() => openRun(monitoredRun.sessionId)}
                        >
                          <Activity size={15} />
                          {t("openLatestRuns")}
                        </button>
                      ) : null}
                      <button
                        type="button"
                        className={`${styles.compactIconAction} ${styles.dangerIconAction}`}
                        disabled={!canDeleteSupervisedRun || deleteRunMutation.isPending}
                        title={disabledReason(deleteSupervisedAction) || t("deleteSupervisedRun")}
                        onClick={() => monitoredRun && deleteRunMutation.mutate(monitoredRun.runId)}
                        aria-label={t("deleteSupervisedRun")}
                      >
                        {deleteRunMutation.isPending ? <LoaderCircle size={15} /> : <Trash2 size={15} />}
                      </button>
                    </div>
                  </div>

                  {actionFeedback ? <p className={styles.feedbackTextCompact}>{actionFeedback}</p> : null}
                  {supervisedControlError ? <p className={styles.errorTextCompact}>{supervisedControlError}</p> : null}
                  {!canPauseSupervisedRun && disabledReason(pauseSupervisedAction) ? (
                    <p className={styles.noticeTextCompact}>{disabledReason(pauseSupervisedAction)}</p>
                  ) : null}
                  {!canResumeSupervisedRun && disabledReason(resumeSupervisedAction) && (runPaused || runPauseRequested) ? (
                    <p className={styles.noticeTextCompact}>{disabledReason(resumeSupervisedAction)}</p>
                  ) : null}
                  {!canTerminateSupervisedRun && disabledReason(terminateSupervisedAction) && runStopping ? (
                    <p className={styles.noticeTextCompact}>{disabledReason(terminateSupervisedAction)}</p>
                  ) : null}
                  {!canDeleteSupervisedRun && disabledReason(deleteSupervisedAction) ? (
                    <p className={styles.noticeTextCompact}>{disabledReason(deleteSupervisedAction)}</p>
                  ) : null}

                  <div className={styles.monitorSummary}>
                    <div className={styles.liveSummaryRow}>
                      <span className={styles.statusIcon}>{statusIcon(monitoredRun.status)}</span>
                      <p className={styles.heroSummary} title={monitoredRun.latestMessage}>
                        {monitoredRun.latestMessage}
                      </p>
                    </div>
                  </div>

                  <div className={styles.monitorMetricsDense}>
                    <article className={styles.metricTile}>
                      <span>{t("activeRunSession")}</span>
                      <strong title={monitoredRunIdentity}>{monitoredRunIdentity}</strong>
                    </article>
                    <article className={styles.metricTile}>
                      <span>{t("activeRunPhase")}</span>
                      <strong>{statusLabel(monitoredRun.currentPhase || monitoredRun.status)}</strong>
                    </article>
                    <article className={styles.metricTile}>
                      <span>{t("activeRunCurrentCase")}</span>
                      <strong title={monitoredCaseLabel}>{monitoredCaseLabel}</strong>
                    </article>
                    <article className={styles.metricTile}>
                      <span>{t("activeRunCurrentRole")}</span>
                      <strong>{monitoredRun.currentRole || "--"}</strong>
                    </article>
                    <article className={styles.metricTile}>
                      <span>{t("activeRunCurrentTask")}</span>
                      <strong title={monitoredTaskLabel}>{monitoredTaskLabel}</strong>
                    </article>
                    <article className={styles.metricTile}>
                      <span>{t("latestLiveMessage")}</span>
                      <strong>{compactTimestamp(monitoredRun.updatedAt)}</strong>
                    </article>
                  </div>

                  <div className={`${styles.detailSection} ${styles.detailSectionCompact}`}>
                    <h3>{t("activeRunTimeline")}</h3>
                    <div className={`${styles.eventList} ${styles.eventListScrollable}`}>
                      {monitoredRun.eventTail.map((item) => (
                        <article key={`${item.timestamp}-${item.event}-${item.summary}`} className={styles.eventRow}>
                          <div className={styles.eventHeader}>
                            <strong>{formatRunEventTitle(item)}</strong>
                            <span className={styles.secondaryPill}>{statusLabel(item.status)}</span>
                          </div>
                          <p className={styles.eventSummary}>{formatRunEventSummary(item)}</p>
                          <span className={styles.formHint}>{compactTimestamp(item.timestamp)}</span>
                        </article>
                      ))}
                    </div>
                  </div>

                </div>
              ) : (
                <div className={styles.idleMonitor}>
                  <p className={styles.noticeText}>{t("noActiveSupervisedRun")}</p>
                  <div className={styles.metricStrip}>
                    <article className={styles.stripItem}>
                      <span>{t("latestRun")}</span>
                      <strong>{overviewLatestRunId || "--"}</strong>
                    </article>
                    <article className={styles.stripItem}>
                      <span>{t("pendingCandidates")}</span>
                      <strong>{pendingItems.length}</strong>
                    </article>
                    <article className={styles.stripItem}>
                      <span>{t("selectedBundle")}</span>
                      <strong>{workbenchState?.bundleName || "--"}</strong>
                    </article>
                  </div>
                  <div className={styles.relatedList}>
                    <article className={styles.relatedRow}>
                      <strong>{t("latestScore")}</strong>
                      <span>{overviewRecentRuns[0] ? clampScore(overviewRecentRuns[0].score) : latestRun ? clampScore(latestRun.candidateScore) : "--"}</span>
                    </article>
                    <article className={styles.relatedRow}>
                      <strong>{t("selectedDataset")}</strong>
                      <span>{workbenchState?.datasetName || "--"}</span>
                    </article>
                  </div>
                  <div className={styles.actionRow}>
                    <button
                      type="button"
                      className={styles.inlineAction}
                      disabled={!overviewLatestRunId}
                      onClick={() => openRun(overviewLatestRunId || null)}
                    >
                      <Activity size={15} />
                      {t("openLatestRuns")}
                    </button>
                    <button
                      type="button"
                      className={styles.inlineAction}
                      onClick={() => {
                        setLibraryView("items");
                        goToSupervisedView("library");
                      }}
                    >
                      <LibraryBig size={15} />
                      {t("openLibraryQueue")}
                    </button>
                  </div>
                </div>
              )}
          </section>

          <button
            type="button"
            className={`${styles.resizeHandle} ${styles.liveResizeHandle} ${styles.liveResizeHandleRun}`}
            aria-label={resizeLiveRunLabel}
            title={resizeLiveRunLabel}
            onPointerDown={handleLiveRunResizeStart}
            onKeyDown={handleLiveRunResizeKeyDown}
          />

          <section className={`${styles.surface} ${styles.ioSurface} ${styles.dashboardIo}`}>
              <div className={styles.surfaceHeaderCompact}>
                <div>
                  <p className={styles.eyebrow}>{t("currentCaseTranscript")}</p>
                  <h2 className={`${styles.sectionTitle} ${styles.truncateText}`} title={monitoredRun?.currentCaseId || undefined}>
                    {monitoredRun?.currentCaseId || t("currentCaseOutput")}
                  </h2>
                </div>
                <div className={styles.liveStatusRow}>
                  {monitoredRun?.currentRole ? (
                    <span className={styles.secondaryPill}>{runRoleLabel(monitoredRun.currentRole)}</span>
                  ) : null}
                  {monitoredRun?.currentCaseScenario ? (
                    <span className={styles.secondaryPill}>{monitoredRun.currentCaseScenario}</span>
                  ) : null}
                  {monitoredRun?.currentCaseMode ? (
                    <span className={styles.secondaryPill}>{monitoredRun.currentCaseMode}</span>
                  ) : null}
                </div>
              </div>

              <div className={styles.liveIoPane}>
                {monitoredCaseHasVisibleIo ? (
                  <div className={styles.ioStack}>
                    {monitoredRun?.currentCasePrompt ? (
                      <details className={`${styles.rawBlock} ${styles.collapsibleEvidence}`}>
                        <summary>{t("currentCasePrompt")}</summary>
                        <pre className={styles.ioContent}>{monitoredRun.currentCasePrompt}</pre>
                      </details>
                    ) : null}

                    <div className={`${styles.detailSection} ${styles.detailSectionCompact}`}>
                      <h3>{currentCaseOutputLabel(monitoredRun)}</h3>
                      {monitoredRun?.currentCaseIo?.latestOutput ? (
                        <div className={`${styles.rawBlock} ${styles.primaryEvidenceBlock}`}>
                          <pre className={styles.ioContent}>{monitoredRun.currentCaseIo.latestOutput}</pre>
                        </div>
                      ) : (
                        <p className={styles.noticeText}>{t("caseIoWaiting")}</p>
                      )}
                    </div>

                    <div className={`${styles.detailSection} ${styles.detailSectionCompact}`}>
                      <h3>{t("currentCaseTranscript")}</h3>
                      {monitoredCaseTranscript.length > 0 ? (
                        <div className={styles.ioTranscript}>
                          {monitoredCaseTranscript.map((entry, index) => (
                            <article
                              key={`${entry.timestamp}-${entry.kind}-${entry.label}-${index}`}
                              className={styles.ioEntry}
                            >
                              <div className={styles.ioMetaRow}>
                                <strong>{caseIoEntryLabel(entry.kind, entry.label, entry.status)}</strong>
                                <span className={styles.formHint}>{compactTimestamp(entry.timestamp)}</span>
                              </div>
                              <pre className={styles.ioContent} title={entry.content}>{entry.content}</pre>
                            </article>
                          ))}
                        </div>
                      ) : (
                        <p className={styles.noticeText}>{t("caseIoWaiting")}</p>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className={styles.ioWaitingState}>
                    <p className={styles.noticeText}>{t("noCurrentCaseIo")}</p>
                  </div>
                )}
              </div>

              <button
                type="button"
                className={styles.liveIoResizeHandle}
                aria-label={resizeLiveIoLabel}
                title={resizeLiveIoLabel}
                onPointerDown={handleLiveIoResizeStart}
                onKeyDown={handleLiveIoResizeKeyDown}
              />
          </section>

        </div>
      ) : null}

      {activeTrack === "supervised" && evolutionView === "runs" ? (
        <div className={styles.viewStack}>
          <section className={`${styles.surface} ${styles.runsCommandStrip}`}>
            <div className={styles.runsCommandHeader}>
              <div>
                <p className={styles.eyebrow}>{t("recentRunPerformance")}</p>
                <h2 className={styles.sectionTitle}>{t("runList")}</h2>
              </div>
              <div className={styles.filterSegmented}>
                {(["all", "success", "failed"] as const).map((filter) => (
                  <button
                    key={filter}
                    type="button"
                    className={
                      runFilter === filter
                        ? `${styles.filterButton} ${styles.filterButtonActive}`
                        : styles.filterButton
                    }
                    onClick={() => setRunFilter(filter)}
                  >
                    {filter === "all" ? t("allRuns") : statusLabel(filter)}
                  </button>
                ))}
              </div>
            </div>

            <div className={styles.runsCommandMetrics}>
              <article className={styles.compactFact}>
                <span>{t("runs")}</span>
                <strong>{hasRuns ? `${filteredRuns.length} / ${runs.length}` : "0 / 0"}</strong>
              </article>
              <article className={styles.compactFact}>
                <span>{statusLabel("success")}</span>
                <strong>{runSuccessCount}</strong>
              </article>
              <article className={styles.compactFact}>
                <span>{statusLabel("failed")}</span>
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
          </section>

          <div className={styles.runsWorkspace} style={runsWorkspaceStyle}>
            <section className={`${styles.surface} ${styles.runQueuePanel}`}>
              <div className={styles.panelHeader}>
                <div>
                  <p className={styles.eyebrow}>{t("runQueue")}</p>
                  <h2 className={styles.sectionTitle}>{t("runs")}</h2>
                </div>
                <span className={styles.secondaryPill}>{filteredRuns.length}</span>
              </div>
              {hasFilteredRuns ? (
                <div className={styles.bulkToolbar}>
                  <div className={styles.bulkToolbarText}>
                    <strong>{t("selectedCount")}</strong>
                    <span>{selectedRunIds.length}</span>
                  </div>
                  <div className={styles.actionRow}>
                    <button
                      type="button"
                      className={styles.inlineAction}
                      disabled={visibleDeletableRunIds.length === 0 || allVisibleDeletableRunsSelected}
                      onClick={selectVisibleRunRecords}
                    >
                      <CheckCircle2 size={15} />
                      {t("selectVisibleRuns")}
                    </button>
                    <button
                      type="button"
                      className={styles.inlineAction}
                      disabled={selectedRunIds.length === 0}
                      onClick={() => setSelectedRunIds([])}
                    >
                      {t("clearSelection")}
                    </button>
                    <button
                      type="button"
                      className={styles.inlineAction}
                      disabled={selectedRunIds.length === 0 || bulkDeleteRunRecordsMutation.isPending}
                      onClick={triggerBulkRunRecordDelete}
                    >
                      {bulkDeleteRunRecordsMutation.isPending ? <LoaderCircle size={15} /> : <Trash2 size={15} />}
                      {t("deleteSelectedRuns")}
                    </button>
                  </div>
                  <p className={styles.bulkToolbarHint}>{t("runBatchDeleteHint")}</p>
                </div>
              ) : (
                <p className={styles.noticeText}>{runHeaderMessage}</p>
              )}
              {runRecordsFeedback ? <p className={styles.feedbackText}>{runRecordsFeedback}</p> : null}
              {deleteRunRecordMutation.error ? <p className={styles.errorText}>{deleteRunRecordMutation.error.message}</p> : null}
              {bulkDeleteRunRecordsMutation.error ? <p className={styles.errorText}>{bulkDeleteRunRecordsMutation.error.message}</p> : null}
              {!hasRuns ? (
                <div className={styles.structuredEmptyState}>
                  <h3>{t("noSupervisedRunsYet")}</h3>
                  <p>{t("noRunsRecordedHint")}</p>
                  <div className={styles.actionRow}>
                    <button
                      type="button"
                      className={styles.inlineAction}
                      onClick={() => goToSupervisedView("live")}
                    >
                      <ArrowUpRight size={15} />
                      {t("returnToOverview")}
                    </button>
                  </div>
                </div>
              ) : filteredRunsEmpty ? (
                <div className={styles.structuredEmptyState}>
                  <h3>{t("noRunMatches")}</h3>
                  <p>{t("runFilterEmptyHint")}</p>
                  <div className={styles.actionRow}>
                    <button
                      type="button"
                      className={styles.inlineAction}
                      onClick={() => setRunFilter("all")}
                    >
                      {t("allRuns")}
                    </button>
                  </div>
                </div>
              ) : (
                <div className={styles.runListScrollable}>
                  {filteredRuns.map((run) => (
                    <article
                      key={run.id}
                      className={
                        selectedRun?.id === run.id
                          ? `${styles.runItem} ${styles.runItemActive} ${styles.runRecordCard}`
                          : `${styles.runItem} ${styles.runRecordCard}`
                      }
                    >
                      <div className={styles.selectionBar}>
                        <label className={styles.batchToggle}>
                          <input
                            type="checkbox"
                            checked={selectedRunIdSet.has(run.id)}
                            disabled={!run.canDelete}
                            onChange={() => toggleRunSelection(run)}
                          />
                          <span>{t("selectRunForDelete")}</span>
                        </label>
                        <span className={run.canDelete ? styles.secondaryPill : styles.statusPill}>
                          {run.canDelete ? t("deletionAllowed") : t("deletionBlocked")}
                        </span>
                      </div>
                      <button
                        type="button"
                        className={styles.runCardButton}
                        onClick={() => setSelectedRunId(run.id)}
                      >
                        <div className={styles.listRowTop}>
                          <strong>{run.id}</strong>
                          <span className={styles.secondaryPill}>{decisionLabel(run.decision)}</span>
                        </div>
                        <div className={styles.metaRow}>
                          <span>{statusLabel(run.status)}</span>
                          <span>{run.outcomeSemantics.proposalStatusLabel}</span>
                        </div>
                        <div className={styles.scoreRow}>
                          <span>{run.bundleName || "--"}</span>
                          <strong>{run.candidateScore}</strong>
                        </div>
                        <p>{run.summary}</p>
                        <div className={styles.cardFooter}>
                          <span>{riskLabel(run.riskLevel)}</span>
                          <span>{run.nextAction || "--"}</span>
                        </div>
                      </button>
                      {!run.canDelete && run.deleteBlockReason ? (
                        <p className={styles.noticeText}>{run.deleteBlockReason}</p>
                      ) : null}
                    </article>
                  ))}
                </div>
              )}
            </section>

            <button
              type="button"
              className={styles.resizeHandle}
              aria-label={resizeRunsQueueLabel}
              title={resizeRunsQueueLabel}
              onPointerDown={handleRunsResizeStart}
              onKeyDown={handleRunsResizeKeyDown}
            />

            <section className={`${styles.surface} ${styles.runDetailPanel}`}>
              {selectedRun ? (
                <>
                  <div className={styles.detailHeader}>
                    <div>
                      <p className={styles.eyebrow}>{t("runDetail")}</p>
                      <h2 className={styles.detailTitle}>{selectedRun.id}</h2>
                    </div>
                    <div className={styles.detailHeaderActions}>
                      <span className={styles.statusPill}>{decisionLabel(selectedRun.decision)}</span>
                      <span className={styles.secondaryPill}>{selectedRun.outcomeSemantics.proposalStatusLabel}</span>
                    </div>
                  </div>

                  <div className={styles.runDetailOverview}>
                    <div className={styles.runScorePanel}>
                      <span>{t("candidateScore")}</span>
                      <p className={styles.detailLead}>{selectedRun.candidateScore}</p>
                      <p>{selectedRun.summary}</p>
                      <div className={styles.runScoreDiagnosis}>
                        <span>{t("diagnosis")}</span>
                        <p>{selectedRun.diagnosis}</p>
                      </div>
                      <div className={styles.runScoreFacts}>
                        <span>
                          {t("baselineScore")}
                          <strong>{selectedRun.baselineScore}</strong>
                        </span>
                        <span>
                          {t("scoreDelta")}
                          <strong>{selectedRun.deltaScore}</strong>
                        </span>
                        <span>
                          {t("linkedItems")}
                          <strong>{relatedProposalCount}</strong>
                        </span>
                      </div>
                    </div>
                    <div className={styles.runSignalStack}>
                      <h3>{t("resultLayersTitle")}</h3>
                      <div className={styles.runSignalGrid}>
                        <article className={styles.compactFact}>
                          <span>{t("runLayer")}</span>
                          <strong>{selectedRun.runSemantics.runStatusLabel}</strong>
                        </article>
                        <article className={styles.compactFact}>
                          <span>{t("decision")}</span>
                          <strong>{selectedRun.outcomeSemantics.decisionLabel}</strong>
                        </article>
                        <article className={styles.compactFact}>
                          <span>{t("proposalLayer")}</span>
                          <strong>{selectedRun.outcomeSemantics.proposalStatusLabel}</strong>
                        </article>
                        <article className={styles.compactFact}>
                          <span>{t("runtimeLayer")}</span>
                          <strong>{selectedRun.outcomeSemantics.runtimeEffectLabel}</strong>
                        </article>
                        <article className={styles.compactFact}>
                          <span>{t("nextRecommendedAction")}</span>
                          <strong>{selectedRun.runSemantics.nextAction || "--"}</strong>
                        </article>
                        <article className={styles.compactFact}>
                          <span>{t("riskLevel")}</span>
                          <strong>{riskLabel(selectedRun.riskLevel)}</strong>
                        </article>
                      </div>
                    </div>
                  </div>

                  <div className={`${styles.detailSection} ${styles.detailSectionCompact}`}>
                    <div className={styles.runRuntimeNote}>
                      <p>{selectedRun.outcomeSemantics.runtimeExplanation}</p>
                      {selectedRun.riskReasons.length > 0 ? (
                        <p>{selectedRun.riskReasons.join(" / ")}</p>
                      ) : null}
                    </div>
                    {selectedRun.availableActions.length > 0 ? (
                      <div className={styles.actionRow}>
                        {selectedRun.availableActions.map((action) => (
                          <button
                            key={action}
                            type="button"
                            className={styles.inlineAction}
                            disabled={runLocked || actionMutation.isPending}
                            onClick={() => triggerRunAction(selectedRun.id, action)}
                          >
                            <Sparkles size={15} />
                            {proposalActionLabel(action)}
                          </button>
                        ))}
                      </div>
                    ) : null}
                    {actionFeedback ? <p className={styles.feedbackText}>{actionFeedback}</p> : null}
                    {actionMutation.error ? <p className={styles.errorText}>{actionMutation.error.message}</p> : null}
                  </div>

                  <div className={styles.detailSection}>
                    <h3>{t("caseDiagnostics")}</h3>
                    {selectedRun.caseDiagnostics.length > 0 ? (
                      <div className={styles.relatedList}>
                        {selectedRun.caseDiagnostics.slice(0, 3).map((item) => (
                          <article key={item.caseId || item.summary} className={styles.relatedRow}>
                            <div className={styles.listRowTop}>
                              <strong>{item.caseId || "--"}</strong>
                              <span>{item.caseType && item.caseType !== "static" ? item.caseType : item.decisionSignal || "--"}</span>
                            </div>
                            <p>{item.summary}</p>
                            {compactCaseObject(item.expectedFinalState) ? (
                              <p>expected final: {compactCaseObject(item.expectedFinalState)}</p>
                            ) : null}
                            {compactCaseObject(item.expectedInfeasibleOutcome) ? (
                              <p>expected infeasible: {compactCaseObject(item.expectedInfeasibleOutcome)}</p>
                            ) : null}
                          </article>
                        ))}
                      </div>
                    ) : (
                      <p>{t("noCaseDiagnostics")}</p>
                    )}
                  </div>

                  <div className={styles.detailSection}>
                    <h3>{t("outputsWorthPromoting")}</h3>
                    {relatedLibraryItems.length === 0 && relatedPendingItems.length === 0 ? (
                      <p>{t("noPromotionCandidates")}</p>
                    ) : (
                      <div className={styles.relatedList}>
                        {relatedLibraryItems.map((item) => (
                          <article key={item.id} className={styles.relatedRow}>
                            <div className={styles.listRowTop}>
                              <strong>{item.title}</strong>
                              <span>{statusLabel(item.proposalStatus)}</span>
                            </div>
                            <p>{item.changeSummary || item.headline}</p>
                            <div className={styles.actionRow}>
                              <button
                                type="button"
                                className={styles.inlineAction}
                                onClick={() => openProposalFromRun(item, "items")}
                              >
                                <ArrowUpRight size={15} />
                                {t("openProposal")}
                              </button>
                              <button
                                type="button"
                                className={styles.inlineAction}
                                disabled={!item.canDelete || deleteProposalMutation.isPending}
                                onClick={() => triggerProposalDelete(item.sourceRun)}
                              >
                                <Trash2 size={15} />
                                {t("deleteProposal")}
                              </button>
                            </div>
                            {!item.canDelete && item.deleteBlockReason ? (
                              <p>{item.deleteBlockReason}</p>
                            ) : null}
                          </article>
                        ))}
                        {relatedPendingItems.map((item) => (
                          <article key={item.id} className={styles.relatedRow}>
                            <div className={styles.listRowTop}>
                              <strong>{item.title}</strong>
                              <span>{statusLabel(item.proposalStatus)}</span>
                            </div>
                            <p>{item.changeSummary || item.headline}</p>
                            <div className={styles.actionRow}>
                              <button
                                type="button"
                                className={styles.inlineAction}
                                onClick={() => openProposalFromRun(item, "pending")}
                              >
                                <ArrowUpRight size={15} />
                                {t("openProposal")}
                              </button>
                              <button
                                type="button"
                                className={styles.inlineAction}
                                disabled={!item.canDelete || deleteProposalMutation.isPending}
                                onClick={() => triggerProposalDelete(item.sourceRun)}
                              >
                                <Trash2 size={15} />
                                {t("deleteProposal")}
                              </button>
                            </div>
                            {!item.canDelete && item.deleteBlockReason ? (
                              <p>{item.deleteBlockReason}</p>
                            ) : null}
                          </article>
                        ))}
                      </div>
                    )}
                    {libraryFeedback ? <p className={styles.feedbackText}>{libraryFeedback}</p> : null}
                    {deleteProposalMutation.error ? <p className={styles.errorText}>{deleteProposalMutation.error.message}</p> : null}
                  </div>

                  <div className={`${styles.detailSection} ${styles.dangerDetailSection}`}>
                    <h3>{t("deleteAndCleanup")}</h3>
                    <div className={styles.relatedList}>
                      <article className={styles.relatedRow}>
                        <strong>{selectedRun.canDelete ? t("deletionAllowed") : t("deletionBlocked")}</strong>
                        <span>
                          {selectedRun.canDelete
                            ? t("deleteRunRecord")
                            : selectedRun.deleteBlockReason || "--"}
                        </span>
                      </article>
                    </div>
                    <p>{t("runDeleteImpact")}</p>
                    <div className={styles.actionRow}>
                      <button
                        type="button"
                        className={styles.inlineAction}
                        disabled={!selectedRun.canDelete || deleteRunRecordMutation.isPending}
                        onClick={() => triggerRunRecordDelete(selectedRun.id)}
                      >
                        {deleteRunRecordMutation.isPending ? <LoaderCircle size={15} /> : <Trash2 size={15} />}
                        {t("deleteRunRecord")}
                      </button>
                    </div>
                  </div>
                </>
              ) : (
                <div className={styles.structuredEmptyState}>
                  <p className={styles.eyebrow}>{t("runDetail")}</p>
                  <h3>{hasRuns ? t("noRunMatches") : t("noSupervisedRunsYet")}</h3>
                  <p>{hasRuns ? t("runDetailFilterHint") : t("runDetailPlaceholder")}</p>
                  <div className={styles.detailFactGrid}>
                    <article className={styles.relatedRow}>
                      <strong>{t("score")}</strong>
                      <span>--</span>
                    </article>
                    <article className={styles.relatedRow}>
                      <strong>{t("proposalStatus")}</strong>
                      <span>--</span>
                    </article>
                  </div>
                  <div className={styles.actionRow}>
                    {!hasRuns ? (
                      <button
                        type="button"
                        className={styles.inlineAction}
                        onClick={() => goToSupervisedView("live")}
                      >
                        <ArrowUpRight size={15} />
                        {t("returnToOverview")}
                      </button>
                    ) : (
                      <button
                        type="button"
                        className={styles.inlineAction}
                        onClick={() => setRunFilter("all")}
                      >
                        {t("allRuns")}
                      </button>
                    )}
                  </div>
                </div>
              )}
            </section>
          </div>
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
                    <button
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
                    </button>
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
                  <button
                    type="button"
                    className={styles.inlineAction}
                    onClick={clearLibraryFilters}
                  >
                    {t("clearFilters")}
                  </button>
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
                  <button
                    type="button"
                    className={styles.inlineAction}
                    onClick={() => openRun(selectedProposalSummary.sourceRun)}
                  >
                    <ArrowUpRight size={15} />
                    {t("openSourceRun")}
                  </button>
                </div>
              ) : null}
            </section>
          </div>

          <div className={styles.masterDetail} style={libraryWorkspaceStyle}>
            <section className={`${styles.surface} ${styles.listPanel}`}>
              <>
                <div className={styles.bulkToolbar}>
                  <div className={styles.bulkToolbarText}>
                    <strong>{t("selectedCount")}</strong>
                    <span>{selectedProposalRunIds.length}</span>
                  </div>
                  <div className={styles.actionRow}>
                    <button
                      type="button"
                      className={styles.inlineAction}
                      disabled={selectedProposalRunIds.length === 0}
                      onClick={() => setSelectedProposalRunIds([])}
                    >
                      {t("clearSelection")}
                    </button>
                    <button
                      type="button"
                      className={styles.inlineAction}
                      disabled={selectedProposalRunIds.length === 0 || bulkDeleteMutation.isPending}
                      onClick={triggerBulkDelete}
                    >
                      <Trash2 size={15} />
                      {t("deleteSelected")}
                    </button>
                  </div>
                </div>
                <div className={styles.libraryFilters}>
                  <div className={styles.filterRow}>
                    <label className={styles.filterField}>
                      <span>{t("proposalTarget")}</span>
                      <input
                        type="text"
                        className={styles.textInput}
                        value={librarySearchInput}
                        placeholder={t("proposalSearchPlaceholder")}
                        onChange={(event) => setLibrarySearchInput(event.target.value)}
                      />
                    </label>
                    <label className={styles.filterField}>
                      <span>{t("filterByStatus")}</span>
                      <select
                        className={styles.selectInput}
                        value={libraryStatusFilter}
                        onChange={(event) => setLibraryStatusFilter(event.target.value as LibraryStatusFilter)}
                      >
                        {LIBRARY_STATUS_FILTERS.map((status) => (
                          <option key={status} value={status}>
                            {status === "all" ? t("filterAll") : statusLabel(status)}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className={styles.filterField}>
                      <span>{t("filterByDeleteState")}</span>
                      <select
                        className={styles.selectInput}
                        value={libraryDeleteFilter}
                        onChange={(event) => setLibraryDeleteFilter(event.target.value as LibraryDeleteFilter)}
                      >
                        <option value="all">{t("filterAll")}</option>
                        <option value="deletable">{t("filterDeletableOnly")}</option>
                        <option value="blocked">{t("filterBlockedOnly")}</option>
                      </select>
                    </label>
                  </div>
                  <div className={styles.filterMeta}>
                    <div className={styles.selectionSummary}>
                      <span>{t("filterResults")}</span>
                      <strong>{visibleLibraryEntries.length} / {currentLibraryEntries.length}</strong>
                    </div>
                    {hasLibraryFilters ? (
                      <button
                        type="button"
                        className={styles.inlineAction}
                        onClick={clearLibraryFilters}
                      >
                        {t("clearFilters")}
                      </button>
                    ) : null}
                  </div>
                </div>
                {libraryFeedback ? <p className={styles.feedbackText}>{libraryFeedback}</p> : null}
                {bulkDeleteMutation.error ? <p className={styles.errorText}>{bulkDeleteMutation.error.message}</p> : null}
                {libraryView === "items"
                ? libraryItems.length === 0
                  ? <div className={styles.emptyState}>{t("emptyLibraryItems")}</div>
                  : filteredLibraryItems.length === 0
                    ? <div className={styles.emptyState}>{t("noProposalMatches")}</div>
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
                          <label className={styles.batchToggle}>
                            <input
                              type="checkbox"
                              disabled={!item.canDelete}
                              checked={proposalSelected(item.sourceRun)}
                              onChange={() => toggleProposalSelection(item)}
                            />
                            <span>{t("selectForBatchDelete")}</span>
                          </label>
                          <span className={item.canDelete ? styles.secondaryPill : styles.statusPill}>
                            {item.canDelete ? t("deletionAllowed") : t("deletionBlocked")}
                          </span>
                        </div>
                        <button
                          type="button"
                          className={styles.proposalCardButton}
                          onClick={() => setSelectedLibraryItemId(item.id)}
                        >
                          <div className={styles.listRowTop}>
                            <strong>{item.title}</strong>
                            <span className={styles.secondaryPill}>{item.outcomeSemantics.proposalStatusLabel}</span>
                          </div>
                          <div className={styles.metaRow}>
                            <span>{decisionLabel(item.decision)}</span>
                            <span>{proposalDisplaySourceRun(item)}</span>
                          </div>
                          <p className={styles.cardHeadline}>{item.changeSummary || item.headline}</p>
                          <p>{item.summary}</p>
                          <div className={styles.cardFooter}>
                            <span>{item.targetLabel || item.targetKey || "--"}</span>
                            <span>{compactTimestamp(item.updatedAt)}</span>
                          </div>
                        </button>
                      </article>
                    ))
                : pendingItems.length === 0
                  ? <div className={styles.emptyState}>{t("emptyPendingItems")}</div>
                  : filteredPendingItems.length === 0
                    ? <div className={styles.emptyState}>{t("noProposalMatches")}</div>
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
                          <label className={styles.batchToggle}>
                            <input
                              type="checkbox"
                              disabled={!item.canDelete}
                              checked={proposalSelected(item.sourceRun)}
                              onChange={() => toggleProposalSelection(item)}
                            />
                            <span>{t("selectForBatchDelete")}</span>
                          </label>
                          <span className={item.canDelete ? styles.secondaryPill : styles.statusPill}>
                            {item.canDelete ? t("deletionAllowed") : t("deletionBlocked")}
                          </span>
                        </div>
                        <button
                          type="button"
                          className={styles.proposalCardButton}
                          onClick={() => setSelectedPendingItemId(item.id)}
                        >
                          <div className={styles.listRowTop}>
                            <strong>{item.title}</strong>
                            <span className={styles.secondaryPill}>{item.outcomeSemantics.proposalStatusLabel}</span>
                          </div>
                          <div className={styles.metaRow}>
                            <span>{decisionLabel(item.decision)}</span>
                            <span>{proposalDisplaySourceRun(item)}</span>
                          </div>
                          <p className={styles.cardHeadline}>{item.changeSummary || item.headline}</p>
                          <p>{item.reason || item.summary}</p>
                          <div className={styles.cardFooter}>
                            <span>{item.targetLabel || item.targetKey || "--"}</span>
                            <span>{compactTimestamp(item.updatedAt)}</span>
                          </div>
                        </button>
                      </article>
                    ))}
              </>
            </section>

            <button
              type="button"
              className={styles.resizeHandle}
              aria-label={resizeLibraryListLabel}
              title={resizeLibraryListLabel}
              onPointerDown={handleLibraryResizeStart}
              onKeyDown={handleLibraryResizeKeyDown}
            />

            <section className={`${styles.surface} ${styles.detailPanel}`}>
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
                            <button
                              type="button"
                              className={styles.inlineAction}
                              disabled={updateProposalMutation.isPending}
                              onClick={() => cancelProposalEdit(proposalDetailQuery.data)}
                            >
                              <X size={15} />
                              {t("cancelEdit")}
                            </button>
                            <button
                              type="button"
                              className={styles.inlineAction}
                              disabled={!proposalDetailQuery.data.canEdit || updateProposalMutation.isPending}
                              onClick={() => triggerProposalUpdate(proposalDetailQuery.data.sourceRun)}
                            >
                              <Save size={15} />
                              {updateProposalMutation.isPending ? t("saving") : t("saveProposalEdit")}
                            </button>
                          </div>
                        ) : (
                          <button
                            type="button"
                            className={styles.inlineAction}
                            disabled={!proposalDetailQuery.data.canEdit}
                            onClick={() => beginProposalEdit(proposalDetailQuery.data)}
                          >
                            <Pencil size={15} />
                            {t("editProposal")}
                          </button>
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
                            <input
                              className={styles.textInput}
                              value={proposalEditDraft.improvementType}
                              onChange={(event) => updateProposalEditDraft("improvementType", event.target.value)}
                            />
                          </label>
                          <label className={styles.formField}>
                            <span>{t("proposalExpectedEffect")}</span>
                            <textarea
                              className={styles.textArea}
                              rows={3}
                              value={proposalEditDraft.expectedEffect}
                              onChange={(event) => updateProposalEditDraft("expectedEffect", event.target.value)}
                            />
                          </label>
                          <label className={styles.formField}>
                            <span>{t("proposalDraftSummary")}</span>
                            <textarea
                              className={styles.textArea}
                              rows={3}
                              value={proposalEditDraft.summary}
                              onChange={(event) => updateProposalEditDraft("summary", event.target.value)}
                            />
                          </label>
                          <label className={styles.formField}>
                            <span>{t("proposalCandidatePrompt")}</span>
                            <textarea
                              className={styles.textArea}
                              rows={6}
                              value={proposalEditDraft.candidatePrompt}
                              onChange={(event) => updateProposalEditDraft("candidatePrompt", event.target.value)}
                            />
                          </label>
                          <label className={styles.formField}>
                            <span>{t("proposalBaselinePrompt")}</span>
                            <textarea
                              className={styles.textArea}
                              rows={5}
                              value={proposalEditDraft.baselinePrompt}
                              onChange={(event) => updateProposalEditDraft("baselinePrompt", event.target.value)}
                            />
                          </label>
                          <label className={styles.formField}>
                            <span>{t("proposalEditNote")}</span>
                            <input
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
                          <span>{proposalDetailQuery.data.outcomeSemantics.decisionLabel}</span>
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
                      <p className={styles.noticeText}>{proposalDetailQuery.data.outcomeSemantics.runtimeExplanation}</p>
                      <p>{proposalDetailQuery.data.supervised.decisionReason}</p>
                      {proposalDetailQuery.data.supervised.riskReasons.length > 0 ? (
                        <p>{proposalDetailQuery.data.supervised.riskReasons.join(" / ")}</p>
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

                    <div className={styles.detailSection}>
                      <h3>{t("availableActions")}</h3>
                      <p>{formatAvailableActions(proposalDetailQuery.data.availableActions)}</p>
                      {proposalDetailQuery.data.availableActions.length > 0 ? (
                        <div className={styles.actionRow}>
                          {proposalDetailQuery.data.availableActions.map((action) => (
                            <button
                              key={action}
                              type="button"
                              className={styles.inlineAction}
                              disabled={runLocked || actionMutation.isPending}
                              onClick={() => triggerRunAction(proposalDetailQuery.data.sourceRun, action)}
                            >
                              <Sparkles size={15} />
                              {proposalActionLabel(action)}
                            </button>
                          ))}
                        </div>
                      ) : null}
                      {actionFeedback ? <p className={styles.feedbackText}>{actionFeedback}</p> : null}
                      {actionMutation.error ? <p className={styles.errorText}>{actionMutation.error.message}</p> : null}
                    </div>

                    <div className={styles.detailSection}>
                      <h3>{t("deleteAndCleanup")}</h3>
                      <div className={styles.relatedList}>
                        <article className={styles.relatedRow}>
                          <strong>{proposalDetailQuery.data.canDelete ? t("deletionAllowed") : t("deletionBlocked")}</strong>
                          <span>
                            {proposalDetailQuery.data.canDelete
                              ? t("deleteProposal")
                              : proposalDetailQuery.data.deleteBlockReason || "--"}
                          </span>
                        </article>
                      </div>
                      <p>{proposalDetailQuery.data.review.deleteImpact}</p>
                      {proposalDetailQuery.data.review.evidenceNotes.length > 0
                        ? renderReviewList(proposalDetailQuery.data.review.evidenceNotes)
                        : null}
                      <div className={styles.actionRow}>
                        <button
                          type="button"
                          className={styles.inlineAction}
                          disabled={!proposalDetailQuery.data.canDelete || deleteProposalMutation.isPending}
                          onClick={() => triggerProposalDelete(proposalDetailQuery.data.sourceRun)}
                        >
                          <Trash2 size={15} />
                          {t("deleteProposal")}
                        </button>
                      </div>
                      {deleteProposalMutation.error ? <p className={styles.errorText}>{deleteProposalMutation.error.message}</p> : null}
                    </div>

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
                      <button
                        type="button"
                        className={styles.inlineAction}
                        onClick={() => openRun(proposalDetailQuery.data.sourceRun)}
                      >
                        <ArrowUpRight size={15} />
                        {t("openSourceRun")}
                      </button>
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
                  <div className={styles.emptyState}>{proposalDetailQuery.error.message}</div>
                ) : (
                  <div className={styles.emptyState}>{t("loadingRunDetails")}</div>
                )
              ) : (
                <div className={styles.emptyState}>{t("chooseProposalDetail")}</div>
              )}
            </section>
          </div>
        </div>
      ) : null}
    </div>
  );
}
