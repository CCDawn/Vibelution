import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  ArrowUpRight,
  CheckSquare,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  LoaderCircle,
  ScrollText,
  ShieldCheck,
  TriangleAlert,
  X,
} from "lucide-react";
import { type PointerEvent as ReactPointerEvent, useEffect, useMemo, useState } from "react";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import {
  ConversationMessage,
  EvolutionWorkflowStep,
  PetSummary,
  RuntimeSummary,
  SelfEvolutionOverview,
  SelfEvolutionTransaction,
  SupervisedWorktreeRun,
} from "../api/types";
import { resolvePollingInterval, usePageVisibility } from "../app/pollingPolicy";
import { LazyConversationView } from "../components/conversation/LazyConversationView";
import { PaneCollapseHandle } from "../components/layout/PaneCollapseHandle";
import { VButton, VNativeInput } from "../components/vui";
import { TranslationKey } from "../i18n/dictionary";
import { petAvatarPresetLabel } from "../i18n/petLabels";
import { useAppI18n } from "../i18n/useAppI18n";
import { getPetAvatarSymbol } from "./chatCompactPanel";
import { selfEvolutionTrackStyles as styles } from "./SelfEvolutionTrack.styles";

type SelfEvolutionTrackProps = {
  overview?: SelfEvolutionOverview;
  worktreeRun?: SupervisedWorktreeRun | null;
  goalInput: string;
  onGoalInputChange: (value: string) => void;
  onStartRun: () => void;
  onWorktreeAction: (runId: string, action: string) => void;
  onDeleteHistoryGroups: (txnIds: string[]) => void;
  startPending: boolean;
  worktreeActionPending: boolean;
  deleteHistoryPending: boolean;
  startWorktreeError: string;
  worktreeActionError: string;
  deleteHistoryError: string;
  actionFeedback: string;
  runLocked: boolean;
  worktreeRunLocked: boolean;
  transactions: SelfEvolutionTransaction[];
  loading: boolean;
};

type ConversationTaskSummary = {
  title: string;
  goal: string;
  status: string;
  latestSummary: string;
  nextAction: string;
  verificationStatus: string;
  verificationSummary: string;
  readFiles: string[];
  changedFiles: string[];
  toolNames: string[];
  turnCount: number;
  resumeCount: number;
  updatedAt: string;
};

type SelfEvolutionPetCompanionTone = "idle" | "active" | "paused" | "caution" | "error";
export type SelfEvolutionTransactionFilter = "all" | "needs_review" | "open" | "changed";
export type SelfEvolutionTransactionDateFilter = "all" | string;
export type SelfEvolutionTransactionDateGroup = {
  key: string;
  label: string;
  count: number;
  needsReviewCount: number;
  items: SelfEvolutionTransaction[];
};

export type SelfEvolutionTransactionHistoryView = {
  filteredTransactions: SelfEvolutionTransaction[];
  transactionDateOptions: SelfEvolutionTransactionDateGroup[];
  dateFilteredTransactions: SelfEvolutionTransaction[];
  visibleTransactions: SelfEvolutionTransaction[];
  visibleTransactionGroups: SelfEvolutionTransactionDateGroup[];
  hiddenTransactionCount: number;
};

export type SelfEvolutionPetCompanionState = {
  tone: SelfEvolutionPetCompanionTone;
  stateKey: TranslationKey;
  detailKey: TranslationKey;
};

type SelfEvolutionWorkflowStepId = "self_evolution" | "approval";
type SelfEvolutionWorkflowDefinition = {
  id: SelfEvolutionWorkflowStepId;
  zh: string;
  en: string;
};

export const SELF_EVOLUTION_WORKFLOW_STEPS: SelfEvolutionWorkflowDefinition[] = [
  { id: "self_evolution", zh: "自进化", en: "Self-evolution" },
  { id: "approval", zh: "审批", en: "Approval" },
];

const WORKTREE_PAGE_SIZE = 10;
export const SELF_TRANSACTION_COLLAPSED_LIMIT = 8;
const SELF_SIDEBAR_WIDTH_STORAGE_KEY = "vibelution.self.sidebar.width";

export function matchesTransactionFilter(item: SelfEvolutionTransaction, filter: SelfEvolutionTransactionFilter) {
  if (filter === "needs_review") {
    return item.validationFailed > 0
      || item.mutationsBlocked > 0
      || ["failed", "error", "blocked"].includes(String(item.status || "").trim().toLowerCase());
  }
  if (filter === "open") {
    return item.isOpen || ["queued", "running", "stopping", "paused"].includes(String(item.status || "").trim().toLowerCase());
  }
  if (filter === "changed") {
    return item.mutationsRecorded > 0;
  }
  return true;
}

export function countTransactionsByFilter(items: SelfEvolutionTransaction[], filter: SelfEvolutionTransactionFilter) {
  return items.filter((item) => matchesTransactionFilter(item, filter)).length;
}

export function filterSelfEvolutionTransactions(items: SelfEvolutionTransaction[], filter: SelfEvolutionTransactionFilter) {
  if (filter === "all") {
    return items;
  }
  return items.filter((item) => matchesTransactionFilter(item, filter));
}

export function filterTransactionsByDate(items: SelfEvolutionTransaction[], dateFilter: SelfEvolutionTransactionDateFilter) {
  if (!dateFilter || dateFilter === "all") {
    return items;
  }
  return items.filter((item) => transactionDateKey(item) === dateFilter);
}

export function deriveSelfEvolutionPetCompanionState({
  petLoadFailed = false,
  worktreeIsolationStartError = false,
  terminateRequested = false,
  pauseRequested = false,
  runStatus = "",
}: {
  petLoadFailed?: boolean;
  worktreeIsolationStartError?: boolean;
  terminateRequested?: boolean;
  pauseRequested?: boolean;
  runStatus?: string | null;
}): SelfEvolutionPetCompanionState {
  if (petLoadFailed) {
    return { tone: "error", stateKey: "petSelfCompanionError", detailKey: "petSelfCompanionErrorDetail" };
  }
  if (worktreeIsolationStartError) {
    return { tone: "caution", stateKey: "petSelfCompanionWorktree", detailKey: "petSelfCompanionWorktreeDetail" };
  }
  if (terminateRequested) {
    return { tone: "caution", stateKey: "petSelfCompanionStopping", detailKey: "petSelfCompanionStoppingDetail" };
  }
  if (pauseRequested || isPausedRunStatus(runStatus || "")) {
    return { tone: "paused", stateKey: "petSelfCompanionPaused", detailKey: "petSelfCompanionPausedDetail" };
  }

  const normalizedStatus = String(runStatus || "").trim().toLowerCase();
  if (normalizedStatus === "queued") {
    return { tone: "active", stateKey: "petSelfCompanionQueued", detailKey: "petSelfCompanionQueuedDetail" };
  }
  if (normalizedStatus === "running") {
    return { tone: "active", stateKey: "petSelfCompanionRunning", detailKey: "petSelfCompanionRunningDetail" };
  }
  if (["failed", "error", "blocked"].includes(normalizedStatus)) {
    return { tone: "error", stateKey: "petSelfCompanionRunFailed", detailKey: "petSelfCompanionRunFailedDetail" };
  }
  if (["done", "completed", "success"].includes(normalizedStatus)) {
    return { tone: "idle", stateKey: "petSelfCompanionDone", detailKey: "petSelfCompanionDoneDetail" };
  }

  return { tone: "idle", stateKey: "petSelfCompanionIdle", detailKey: "petSelfCompanionIdleDetail" };
}

export function pruneSelectedHistoryTxnIds(selectedTxnIds: string[], visibleTxnIds: string[]) {
  if (selectedTxnIds.length === 0) {
    return selectedTxnIds;
  }
  const visibleSet = new Set(visibleTxnIds);
  const next = selectedTxnIds.filter((txnId) => visibleSet.has(txnId));
  if (next.length === selectedTxnIds.length) {
    return selectedTxnIds;
  }
  return next;
}

function formatRate(value: number | null | undefined) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "--";
  }
  return `${Math.round(value * 100)}%`;
}

function clampPercent(value: number | null | undefined) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return 0;
  }
  return Math.max(0, Math.min(100, Math.round(value)));
}

function compactTimestamp(value: string) {
  const text = String(value || "").trim();
  if (!text) {
    return "--";
  }
  const normalized = text.replace("T", " ");
  return normalized.length > 19 ? normalized.slice(0, 19) : normalized;
}

function compactRevision(value: string) {
  const text = String(value || "").trim();
  if (!text) {
    return "--";
  }
  return text.length > 12 ? text.slice(0, 12) : text;
}

function compactDuration(seconds: number | null | undefined, lang: string) {
  if (typeof seconds !== "number" || Number.isNaN(seconds) || seconds < 0) {
    return "--";
  }
  if (seconds < 60) {
    return lang === "zh" ? `${Math.round(seconds)}秒` : `${Math.round(seconds)}s`;
  }
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  if (minutes < 60) {
    return lang === "zh" ? `${minutes}分${rest ? `${rest}秒` : ""}` : `${minutes}m${rest ? ` ${rest}s` : ""}`;
  }
  const hours = Math.floor(minutes / 60);
  const minuteRest = minutes % 60;
  return lang === "zh" ? `${hours}小时${minuteRest ? `${minuteRest}分` : ""}` : `${hours}h${minuteRest ? ` ${minuteRest}m` : ""}`;
}

function looksLikeStructuredPayload(value: string) {
  const text = String(value || "").trim();
  return text.startsWith("{") || text.startsWith("[");
}

function isExecutingRunStatus(status: string) {
  return ["queued", "running", "stopping"].includes(String(status || "").trim().toLowerCase());
}

function isPausedRunStatus(status: string) {
  return String(status || "").trim().toLowerCase() === "paused";
}

function isWorktreeIsolationStartError(message: string) {
  const text = String(message || "").toLowerCase();
  return Boolean(text) && (
    text.includes("worktree")
    || text.includes("risky write")
    || text.includes("监督工作树")
    || text.includes("隔离工作树")
  );
}

function readinessIcon(state: string) {
  const normalized = String(state).trim().toLowerCase();
  if (normalized === "ready" || normalized === "done" || normalized === "success") {
    return <ShieldCheck size={16} />;
  }
  if (normalized === "caution" || normalized === "failed" || normalized === "blocked") {
    return <TriangleAlert size={16} />;
  }
  return <Activity size={16} />;
}

function worktreeFileFlags(
  t: ReturnType<typeof useAppI18n>["t"],
  file: SelfEvolutionOverview["worktree"]["files"][number],
) {
  const flags: string[] = [];
  if (file.staged) {
    flags.push(t("worktreeFlagStaged"));
  }
  if (file.unstaged) {
    flags.push(t("worktreeFlagUnstaged"));
  }
  if (file.untracked) {
    flags.push(t("worktreeFlagUntracked"));
  }
  if (file.deleted) {
    flags.push(t("worktreeFlagDeleted"));
  }
  return flags.length > 0 ? flags.join(" / ") : "";
}

function buildPageWindow(currentPage: number, totalPages: number) {
  const start = Math.max(1, currentPage - 2);
  const end = Math.min(totalPages, start + 4);
  const adjustedStart = Math.max(1, end - 4);
  return Array.from({ length: end - adjustedStart + 1 }, (_, index) => adjustedStart + index);
}

function collectUniqueLines(values: Array<string | null | undefined>) {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const raw of values) {
    const value = String(raw || "").trim();
    if (!value || seen.has(value)) {
      continue;
    }
    seen.add(value);
    result.push(value);
  }
  return result;
}

function joinReadableLines(values: Array<string | null | undefined>) {
  return values.map((value) => String(value || "").trim()).filter(Boolean).join("\n");
}

export function buildTransactionDisplayTitle(
  item: SelfEvolutionTransaction,
  options: { closedLabel: string; openLabel: string },
) {
  const summary = String(item.summary || "").trim();
  if (summary) {
    return summary.length > 72 ? `${summary.slice(0, 72)}...` : summary;
  }
  const timestamp = compactTimestamp(item.closedAt || item.openedAt);
  const stateLabel = item.isOpen ? options.openLabel : options.closedLabel;
  return timestamp && timestamp !== "--" ? `${stateLabel} · ${timestamp}` : stateLabel;
}

export function buildTransactionOutcomeLabel(item: SelfEvolutionTransaction, lang: string) {
  if (matchesTransactionFilter(item, "needs_review")) {
    return lang === "zh" ? "需复盘" : "Needs review";
  }
  if (!item.isOpen && item.validationPassed > 0) {
    return lang === "zh" ? "验证通过" : "Validated";
  }
  return item.isOpen ? (lang === "zh" ? "进行中" : "Open") : (lang === "zh" ? "已记录" : "Recorded");
}

function transactionTimestamp(item: SelfEvolutionTransaction) {
  return String(item.closedAt || item.openedAt || "").trim();
}

export function transactionDateKey(item: SelfEvolutionTransaction) {
  const timestamp = transactionTimestamp(item);
  return timestamp.length >= 10 ? timestamp.slice(0, 10) : "unknown";
}

export function transactionDateLabel(key: string, lang: string) {
  if (!key || key === "unknown") {
    return lang === "zh" ? "未记录日期" : "Undated";
  }
  if (lang === "zh" && /^\d{4}-\d{2}-\d{2}$/.test(key)) {
    const [year, month, day] = key.split("-");
    return `${year}年${month}月${day}日`;
  }
  return key;
}

export function buildTransactionBatchLabel(item: SelfEvolutionTransaction, lang: string) {
  const timestamp = transactionTimestamp(item);
  const batchTime = timestamp.length >= 16 ? timestamp.slice(11, 16) : "";
  const prefix = lang === "zh" ? "批次" : "Batch";
  if (batchTime) {
    return `${prefix} ${batchTime}`;
  }
  const revision = compactRevision(item.baseRevShort || item.baseRev);
  return revision && revision !== "--" ? `${prefix} ${revision}` : `${prefix} ${item.txnId}`;
}

export function groupTransactionsByDate(items: SelfEvolutionTransaction[], lang: string): SelfEvolutionTransactionDateGroup[] {
  const groups: SelfEvolutionTransactionDateGroup[] = [];
  const groupByKey = new Map<string, SelfEvolutionTransactionDateGroup>();
  for (const item of items) {
    const key = transactionDateKey(item);
    let group = groupByKey.get(key);
    if (!group) {
      group = {
        key,
        label: transactionDateLabel(key, lang),
        count: 0,
        needsReviewCount: 0,
        items: [],
      };
      groupByKey.set(key, group);
      groups.push(group);
    }
    group.count += 1;
    if (matchesTransactionFilter(item, "needs_review")) {
      group.needsReviewCount += 1;
    }
    group.items.push(item);
  }
  return groups;
}

export function buildSelfEvolutionTransactionHistoryView({
  items,
  filter,
  dateFilter,
  lang,
  expanded,
  collapsedLimit = SELF_TRANSACTION_COLLAPSED_LIMIT,
}: {
  items: SelfEvolutionTransaction[];
  filter: SelfEvolutionTransactionFilter;
  dateFilter: SelfEvolutionTransactionDateFilter;
  lang: string;
  expanded: boolean;
  collapsedLimit?: number;
}): SelfEvolutionTransactionHistoryView {
  const filteredTransactions = filterSelfEvolutionTransactions(items, filter);
  const transactionDateOptions = groupTransactionsByDate(filteredTransactions, lang);
  const dateFilteredTransactions = filterTransactionsByDate(filteredTransactions, dateFilter);
  const limit = expanded ? dateFilteredTransactions.length : Math.max(0, collapsedLimit);
  const visibleTransactions = dateFilteredTransactions.slice(0, limit);
  return {
    filteredTransactions,
    transactionDateOptions,
    dateFilteredTransactions,
    visibleTransactions,
    visibleTransactionGroups: groupTransactionsByDate(visibleTransactions, lang),
    hiddenTransactionCount: Math.max(0, dateFilteredTransactions.length - visibleTransactions.length),
  };
}

function buildSelfWorkflowSteps(run: SupervisedWorktreeRun | null | undefined, lang: "zh" | "en"): EvolutionWorkflowStep[] {
  const steps = run?.workflowSteps ?? [];
  const normalized = SELF_EVOLUTION_WORKFLOW_STEPS.map((definition) => {
    const existing = steps.find((step) => step.id === definition.id);
    if (existing) {
      return existing;
    }
    const isApproval = definition.id === "approval";
    const terminal = ["done", "failed", "cancelled"].includes(String(run?.status || "").trim().toLowerCase());
    return {
      id: definition.id,
      label: lang === "zh" ? definition.zh : definition.en,
      ownerKind: isApproval ? "human" : "agent",
      role: isApproval ? null : "candidate",
      status: isApproval ? (terminal ? "pending" : "pending") : (run ? String(run.status || "pending") : "pending"),
      current: isApproval ? terminal : !terminal,
      summary: isApproval
        ? (lang === "zh" ? "等待自进化候选证据完成后进行人工审批。" : "Waiting for candidate evidence before human approval.")
        : (run?.latestMessage || (lang === "zh" ? "等待自进化 Agent 会话。" : "Waiting for the self-evolution agent session.")),
      livePreview: run?.latestMessage || "",
      metrics: {},
      conversationSessionId: "",
      conversationTurnId: "",
      chatRoute: "",
      conversationMessages: [],
    } satisfies EvolutionWorkflowStep;
  });
  if (!normalized.some((step) => step.current)) {
    normalized[0] = { ...normalized[0], current: true };
  }
  return normalized;
}

export function SelfEvolutionTrack({
  overview,
  worktreeRun,
  goalInput,
  onGoalInputChange,
  onStartRun,
  onWorktreeAction,
  onDeleteHistoryGroups,
  startPending,
  worktreeActionPending,
  deleteHistoryPending,
  startWorktreeError,
  worktreeActionError,
  deleteHistoryError,
  actionFeedback,
  runLocked,
  worktreeRunLocked,
  transactions,
  loading,
}: SelfEvolutionTrackProps) {
  const { lang, t, statusLabel } = useAppI18n();
  const [worktreePage, setWorktreePage] = useState(1);
  const [activePage, setActivePage] = useState<"workspace" | "status">("workspace");
  const [selectedHistoryTxnIds, setSelectedHistoryTxnIds] = useState<string[]>([]);
  const [expandedHistoryTxnIds, setExpandedHistoryTxnIds] = useState<string[]>([]);
  const [transactionFilter, setTransactionFilter] = useState<SelfEvolutionTransactionFilter>("all");
  const [transactionDateFilter, setTransactionDateFilter] = useState<SelfEvolutionTransactionDateFilter>("all");
  const [transactionHistoryExpanded, setTransactionHistoryExpanded] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    if (typeof window === "undefined") {
      return 304;
    }
    const saved = Number(window.localStorage.getItem(SELF_SIDEBAR_WIDTH_STORAGE_KEY) || "");
    return Number.isFinite(saved) ? Math.max(260, Math.min(400, saved)) : 304;
  });
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const pageVisible = usePageVisibility();
  const petQuery = useQuery({
    queryKey: queryKeys.petSummary(),
    queryFn: () => fetchJson<PetSummary>("/api/pet/summary"),
    refetchInterval: resolvePollingInterval(pageVisible, 10_000),
    refetchIntervalInBackground: false,
  });
  const runtimeQuery = useQuery({
    queryKey: queryKeys.runtimeSummary(),
    queryFn: () => fetchJson<RuntimeSummary>("/api/runtime/summary"),
    refetchInterval: resolvePollingInterval(pageVisible, 5_000),
    refetchIntervalInBackground: false,
  });
  const pet = petQuery.data;
  const runtime = runtimeQuery.data;

  useEffect(() => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(SELF_SIDEBAR_WIDTH_STORAGE_KEY, String(sidebarWidth));
    }
  }, [sidebarWidth]);

  const worktreeFiles = useMemo(() => {
    const files = overview?.worktree.files ?? [];
    return [...files].sort((left, right) => {
      const leftStatus = String(left.status || "");
      const rightStatus = String(right.status || "");
      if (leftStatus !== rightStatus) {
        return leftStatus.localeCompare(rightStatus);
      }
      return left.path.localeCompare(right.path);
    });
  }, [overview?.worktree.files]);

  const totalWorktreePages = Math.max(1, Math.ceil(worktreeFiles.length / WORKTREE_PAGE_SIZE));
  const clampedWorktreePage = Math.min(worktreePage, totalWorktreePages);
  const pageNumbers = buildPageWindow(clampedWorktreePage, totalWorktreePages);
  const worktreePageStart = worktreeFiles.length === 0 ? 0 : (clampedWorktreePage - 1) * WORKTREE_PAGE_SIZE + 1;
  const worktreePageEnd = worktreeFiles.length === 0
    ? 0
    : Math.min(worktreeFiles.length, clampedWorktreePage * WORKTREE_PAGE_SIZE);
  const currentWorktreeFiles = worktreeFiles.slice(
    (clampedWorktreePage - 1) * WORKTREE_PAGE_SIZE,
    clampedWorktreePage * WORKTREE_PAGE_SIZE,
  );

  useEffect(() => {
    if (worktreePage !== clampedWorktreePage) {
      setWorktreePage(clampedWorktreePage);
    }
  }, [clampedWorktreePage, worktreePage]);

  const gitStatusSummary = String(overview?.gitStatus.summary || "").trim();
  const gitStatusLines = (overview?.gitStatus.lines ?? [])
    .map((line) => String(line || "").trim())
    .filter(Boolean)
    .filter((line) => !looksLikeStructuredPayload(line))
    .slice(0, 4);
  const currentStateNotes = overview
    ? overview.readiness.reasons.length > 0
      ? overview.readiness.reasons
      : gitStatusLines.length > 0
        ? gitStatusLines
        : [gitStatusSummary || t("loading")]
    : [];
  const worktreeFlags = [
    overview?.worktree.hasStaged ? t("worktreeFlagStaged") : "",
    overview?.worktree.hasUnstaged ? t("worktreeFlagUnstaged") : "",
    overview?.worktree.hasUntracked ? t("worktreeFlagUntracked") : "",
  ].filter(Boolean);
  const compactWorktreeSummary = !overview
    ? t("loading")
    : gitStatusSummary && !looksLikeStructuredPayload(gitStatusSummary)
      ? gitStatusSummary
      : overview.worktree.error
        ? overview.worktree.error
        : overview.worktree.isDirty
          ? [worktreeFlags.join(" / "), `${t("filesChanged")} ${overview.worktree.dirtyFileCount}`]
            .filter(Boolean)
            .join(" · ")
          : t("worktreeClean");
  const transactionItems = transactions.length > 0 ? transactions : overview?.recentTransactions ?? [];
  const workflowSteps = useMemo<EvolutionWorkflowStep[]>(() => buildSelfWorkflowSteps(worktreeRun, lang), [lang, worktreeRun]);
  const currentWorkflowStep = workflowSteps.find((step) => step.current) ?? workflowSteps[0];
  const [selectedWorkflowStepId, setSelectedWorkflowStepId] = useState<SelfEvolutionWorkflowStepId | null>(null);
  const selectedWorkflowStep =
    workflowSteps.find((step) => step.id === selectedWorkflowStepId)
    ?? currentWorkflowStep
    ?? workflowSteps[0];
  const selfEvolutionStep = workflowSteps.find((step) => step.id === "self_evolution") ?? workflowSteps[0];
  const approvalStep = workflowSteps.find((step) => step.id === "approval") ?? workflowSteps[1] ?? workflowSteps[0];
  const runIsActive = worktreeRun ? isExecutingRunStatus(worktreeRun.status) : false;
  const changedFiles = worktreeRun?.mergeAnalysis?.changedFiles ?? [];
  const approveReviewAction = worktreeRun?.actionStates?.approveReview;
  const mergeAction = worktreeRun?.actionStates?.merge;
  const discardAction = worktreeRun?.actionStates?.discard;
  const terminateAction = worktreeRun?.actionStates?.terminate;
  const reviewGate = worktreeRun?.reviewGate ?? worktreeRun?.mergeAnalysis?.reviewGate;
  const sceneSemantics = overview?.sceneSemantics;
  const runSemantics = overview?.runSemantics;
  const startSelfAction = overview?.actionStates?.start;
  const terminateRequested = String(worktreeRun?.status || "").toLowerCase() === "stopping";
  const worktreeIsolationStartError = false;
  const petCompanionState = deriveSelfEvolutionPetCompanionState({
    petLoadFailed: petQuery.isError,
    worktreeIsolationStartError,
    terminateRequested,
    pauseRequested: false,
    runStatus: worktreeRun?.status || worktreeRun?.runtimeStatus || overview?.readiness.state || "",
  });
  const errorMessage = collectUniqueLines([
    startWorktreeError,
    worktreeActionError,
    deleteHistoryError,
  ]).join("\n");
  const transactionFilterOptions = useMemo(() => ([
    { id: "all" as const, label: t("filterAll"), count: countTransactionsByFilter(transactionItems, "all") },
    { id: "needs_review" as const, label: t("selfTransactionFilterNeedsReview"), count: countTransactionsByFilter(transactionItems, "needs_review") },
    { id: "open" as const, label: t("selfTransactionFilterOpen"), count: countTransactionsByFilter(transactionItems, "open") },
    { id: "changed" as const, label: t("selfTransactionFilterChanged"), count: countTransactionsByFilter(transactionItems, "changed") },
  ]), [t, transactionItems]);
  const transactionHistoryView = useMemo(
    () => buildSelfEvolutionTransactionHistoryView({
      items: transactionItems,
      filter: transactionFilter,
      dateFilter: transactionDateFilter,
      lang,
      expanded: transactionHistoryExpanded,
    }),
    [lang, transactionDateFilter, transactionFilter, transactionHistoryExpanded, transactionItems],
  );
  const {
    filteredTransactions,
    transactionDateOptions,
    dateFilteredTransactions,
    visibleTransactions,
    visibleTransactionGroups,
    hiddenTransactionCount,
  } = transactionHistoryView;
  const visibleAuditTrail = useMemo(() => (overview?.auditTail ?? []).slice(-8).reverse(), [overview?.auditTail]);
  const visibleTransactionIds = useMemo(
    () => visibleTransactions.map((item) => item.txnId).filter(Boolean),
    [visibleTransactions],
  );
  const auditCountByTxnId = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of overview?.auditTail ?? []) {
      const txnId = String(item.txnId || "").trim();
      if (!txnId) {
        continue;
      }
      counts.set(txnId, (counts.get(txnId) || 0) + 1);
    }
    return counts;
  }, [overview?.auditTail]);
  const petVitals = useMemo(
    () => [
      { key: "mood", label: t("mood"), value: clampPercent(pet?.mood ?? 0) },
      { key: "hunger", label: t("hunger"), value: clampPercent(pet?.hunger ?? 0) },
      { key: "energy", label: t("energy"), value: clampPercent(pet?.energy ?? 0) },
      { key: "health", label: t("health"), value: clampPercent(pet?.health ?? 0) },
      { key: "love", label: t("love"), value: clampPercent(pet?.love ?? 0) },
    ],
    [pet?.energy, pet?.health, pet?.hunger, pet?.love, pet?.mood, t],
  );
  const petCompanionLine = petQuery.isError
    ? t("loadFailed")
    : pet?.inDream
      ? t("petCompanionDreaming")
      : (pet?.health ?? 0) < 35
        ? t("petCompanionLowHealth")
        : (pet?.hunger ?? 0) < 30
          ? t("petCompanionLowFuel")
          : (pet?.energy ?? 0) < 35
            ? t("petCompanionLowEnergy")
            : t("petCompanionStable");
  const petPresetLabel = petAvatarPresetLabel(t, pet?.avatarPreset);
  const petAvatarFallback = getPetAvatarSymbol(pet?.avatarPreset, pet?.name);

  function disabledReason(state: { enabled: boolean; reason: string } | undefined) {
    if (!state || state.enabled) {
      return "";
    }
    return state.reason || "";
  }
  const conversationTask = useMemo<ConversationTaskSummary>(() => {
    const readFiles = overview ? collectUniqueLines(overview.auditTail.flatMap((item) => item.targetPaths)) : [];
    const localChangedFiles = overview
      ? collectUniqueLines([
          ...overview.recentChanges.map((item) => item.path),
          ...overview.worktree.files
            .filter((item) => item.staged || item.unstaged || item.untracked || item.deleted)
            .map((item) => item.path),
          ...changedFiles.map((item) => item.path),
        ])
      : changedFiles.map((item) => item.path);
    const toolNames = overview ? collectUniqueLines(overview.auditTail.map((item) => item.toolName)) : [];
    const goal = worktreeRun?.selfEvolutionOrigin?.goal || overview?.goal || goalInput || t("selfGoalPlaceholder");
    const status = selectedWorkflowStep?.status || worktreeRun?.status || overview?.readiness.state || "pending";
    const latestSummary =
      selectedWorkflowStep?.livePreview
      || selectedWorkflowStep?.summary
      || worktreeRun?.latestMessage
      || overview?.readiness.summary
      || t("loading");
    return {
      title: selectedWorkflowStep?.label || t("launchSelfRun"),
      goal,
      status,
      latestSummary,
      nextAction: terminateRequested
        ? t("selfStopRequested")
        : sceneSemantics?.nextAction || overview?.readiness.nextAction || selectedWorkflowStep?.summary || latestSummary,
      verificationStatus: worktreeRun?.mergeAnalysis?.status || worktreeRun?.runtimeStatus || status,
      verificationSummary:
        worktreeRun?.mergeAnalysis?.reason
        || worktreeRun?.decision?.reason
        || overview?.readiness.summary
        || latestSummary,
      readFiles,
      changedFiles: localChangedFiles,
      toolNames,
      turnCount: selectedWorkflowStep?.conversationMessages?.length ?? transactionItems.length,
      resumeCount: 0,
      updatedAt: worktreeRun?.updatedAt || overview?.worktree.createdAt || "",
    };
  }, [
    changedFiles,
    goalInput,
    overview,
    sceneSemantics?.nextAction,
    selectedWorkflowStep,
    t,
    terminateRequested,
    transactionItems.length,
    worktreeRun,
  ]);
  const conversationMessages = useMemo<ConversationMessage[]>(() => {
    const selectedMessages = selectedWorkflowStep?.conversationMessages ?? [];
    if (selectedMessages.length) {
      return selectedMessages;
    }
    if (!overview) {
      return [];
    }
    return [
      {
        id: "self-readiness",
        role: "assistant",
        content: joinReadableLines([selectedWorkflowStep?.summary, overview.readiness.summary, overview.readiness.nextAction]),
        timestamp: "",
      },
    ];
  }, [overview, selectedWorkflowStep]);

  useEffect(() => {
    setSelectedHistoryTxnIds((current) => pruneSelectedHistoryTxnIds(current, visibleTransactionIds));
    setExpandedHistoryTxnIds((current) => pruneSelectedHistoryTxnIds(current, visibleTransactionIds));
  }, [visibleTransactionIds]);

  useEffect(() => {
    if (transactionDateFilter === "all") {
      return;
    }
    if (!transactionDateOptions.some((option) => option.key === transactionDateFilter)) {
      setTransactionDateFilter("all");
    }
  }, [transactionDateFilter, transactionDateOptions]);

  useEffect(() => {
    setTransactionHistoryExpanded(false);
  }, [transactionDateFilter, transactionFilter]);

  function beginSidebarResize(event: ReactPointerEvent<HTMLButtonElement>) {
    if (sidebarCollapsed) {
      return;
    }
    const startX = event.clientX;
    const startWidth = sidebarWidth;

    const handleMove = (moveEvent: PointerEvent) => {
      const nextWidth = startWidth + (moveEvent.clientX - startX);
      setSidebarWidth(Math.max(260, Math.min(400, nextWidth)));
    };

    const handleUp = () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
    };

    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp);
  }

  function toggleHistorySelection(txnId: string) {
    if (!txnId) {
      return;
    }
    setSelectedHistoryTxnIds((current) => (
      current.includes(txnId)
        ? current.filter((item) => item !== txnId)
        : [...current, txnId]
    ));
  }

  function toggleAllVisibleHistoryGroups() {
    if (visibleTransactionIds.length === 0) {
      return;
    }
    const allSelected = visibleTransactionIds.every((txnId) => selectedHistoryTxnIds.includes(txnId));
    setSelectedHistoryTxnIds(allSelected ? [] : visibleTransactionIds);
  }

  function toggleTransactionDetails(txnId: string) {
    if (!txnId) {
      return;
    }
    setExpandedHistoryTxnIds((current) => (
      current.includes(txnId)
        ? current.filter((item) => item !== txnId)
        : [...current, txnId]
    ));
  }

  function renderLoadingShell(message: string) {
    return (
      <section className={`${styles.surface} ${styles.loadingShell}`} aria-busy="true">
        <div className={styles.loadingRail}>
          <div>
            <p className={styles.eyebrow}>{lang === "zh" ? "自进化状态" : "Self-evolution status"}</p>
            <h2 className={styles.sectionTitle}>{message}</h2>
          </div>
          <div className={styles.loadingStatGrid}>
            <span>{lang === "zh" ? "工作区" : "Workspace"}<strong>--</strong></span>
            <span>{lang === "zh" ? "事务" : "Transactions"}<strong>--</strong></span>
            <span>{lang === "zh" ? "运行" : "Run"}<strong>--</strong></span>
          </div>
        </div>
        <div className={styles.loadingBody}>
          <div className={styles.loadingPanel}>
            <strong>{lang === "zh" ? "现场证据" : "Live evidence"}</strong>
            <span className={styles.skeletonLineWide} />
            <span className={styles.skeletonLine} />
            <span className={styles.skeletonLineShort} />
          </div>
          <div className={styles.loadingPanel}>
            <strong>{lang === "zh" ? "事务历史" : "Transaction history"}</strong>
            <span className={styles.skeletonLine} />
            <span className={styles.skeletonLineWide} />
            <span className={styles.skeletonLineShort} />
          </div>
          <div className={styles.loadingPanel}>
            <strong>{lang === "zh" ? "工作区状态" : "Workspace state"}</strong>
            <span className={styles.skeletonLineShort} />
            <span className={styles.skeletonLineWide} />
            <span className={styles.skeletonLine} />
          </div>
        </div>
      </section>
    );
  }

  function renderLoadFailedShell() {
    return (
      <section className={styles.surface} aria-busy="false">
        <div className={styles.emptyState}>{t("loadFailed")}</div>
      </section>
    );
  }

  if (loading && !overview) {
    return renderLoadingShell(t("loading"));
  }

  if (!overview) {
    return renderLoadFailedShell();
  }

  const allVisibleHistorySelected = visibleTransactionIds.length > 0
    && visibleTransactionIds.every((txnId) => selectedHistoryTxnIds.includes(txnId));
  const selectedHistorySet = new Set(selectedHistoryTxnIds);
  const expandedHistorySet = new Set(expandedHistoryTxnIds);
  const approvalEvidenceItems = [
    {
      label: lang === "zh" ? "最终结果" : "Final result",
      value: worktreeRun?.outcome || worktreeRun?.status || "--",
    },
    {
      label: lang === "zh" ? "分数变化" : "Score delta",
      value: String(worktreeRun?.decision?.scoreDelta ?? approvalStep.metrics?.scoreDelta ?? "--"),
    },
    {
      label: lang === "zh" ? "审批状态" : "Review gate",
      value: reviewGate?.status || "--",
    },
    {
      label: lang === "zh" ? "候选变更" : "Changed files",
      value: String(changedFiles.length || approvalStep.metrics?.changedFileCount || 0),
    },
    {
      label: lang === "zh" ? "风险摘要" : "Risk",
      value: worktreeRun?.mergeAnalysis?.reason || worktreeRun?.decision?.reason || approvalStep.summary || "--",
    },
  ];

  return (
    <div className={styles.pageStack}>
      <div className={styles.pageTabsRow}>
        <div className={styles.segmentedTabs}>
          <VButton
            type="button"
            className={activePage === "workspace" ? `${styles.tabButton} ${styles.tabButtonActive}` : styles.tabButton}
            onClick={() => setActivePage("workspace")}
          >
            {t("selfWorkspacePage")}
          </VButton>
          <VButton
            type="button"
            className={activePage === "status" ? `${styles.tabButton} ${styles.tabButtonActive}` : styles.tabButton}
            onClick={() => setActivePage("status")}
          >
            {t("selfStatusPage")}
          </VButton>
        </div>
      </div>

      {activePage === "workspace" ? (
        <div
          className={styles.workspaceLayout}
          style={{ ["--self-sidebar-width" as string]: sidebarCollapsed ? "0px" : `${sidebarWidth}px` }}
        >
          <aside
            className={
              sidebarCollapsed
                ? `${styles.sideColumn} ${styles.sideColumnScrollable} ${styles.paneCollapsed}`
                : `${styles.sideColumn} ${styles.sideColumnScrollable}`
            }
            aria-hidden={sidebarCollapsed}
          >
            <section className={styles.surface}>
              <div className={styles.sectionHeader}>
                <div>
                  <p className={styles.eyebrow}>{t("selfEvolutionMode")}</p>
                  <h3 className={styles.sectionTitle}>{t("selfWorkspacePage")}</h3>
                </div>
                <span className={styles.statusPill}>{statusLabel(conversationTask.status)}</span>
              </div>

              <p className={styles.sectionSummary}>{conversationTask.goal}</p>

                <div className={styles.detailStack}>
                  <div className={styles.detailRow}>
                    <span>{t("sceneStateTitle")}</span>
                    <strong>{sceneSemantics?.sceneTitle || statusLabel(overview.readiness.state)}</strong>
                  </div>
                  <div className={styles.detailRow}>
                    <span>{t("currentRunTitle")}</span>
                    <strong>{runSemantics?.phaseLabel || statusLabel(worktreeRun?.runtimeStatus || worktreeRun?.status || overview.readiness.state)}</strong>
                  </div>
                  <div className={styles.detailRow}>
                    <span>{t("rollbackStateTitle")}</span>
                    <strong>{runSemantics?.rollbackStateLabel || statusLabel(conversationTask.verificationStatus)}</strong>
                  </div>
                  <div className={styles.detailRow}>
                    <span>{t("lastUpdated")}</span>
                    <strong>{compactTimestamp(conversationTask.updatedAt)}</strong>
                  </div>
                </div>

              <div className={styles.noticeStack}>
                <p className={styles.noticeText}>{sceneSemantics?.sceneSummary || conversationTask.latestSummary}</p>
                <p className={styles.noticeText}>
                  {runSemantics?.rollbackSummary || conversationTask.nextAction}
                </p>
                {sceneSemantics?.nextAction ? <p className={styles.noticeText}>{sceneSemantics.nextAction}</p> : null}
                {!startSelfAction?.enabled && disabledReason(startSelfAction) ? (
                  <p className={styles.noticeText}>{disabledReason(startSelfAction)}</p>
                ) : null}
                {runLocked ? <p className={styles.noticeText}>{t("selfRunningLockHint")}</p> : null}
                {worktreeRunLocked ? <p className={styles.noticeText}>{t("selfWorktreeRunningLockHint")}</p> : null}
                {actionFeedback ? <p className={styles.feedbackText}>{actionFeedback}</p> : null}
                {errorMessage ? <p className={styles.errorText}>{errorMessage}</p> : null}
                <VButton
                  type="button"
                  className={styles.secondaryAction}
                  isDisabled={runLocked || worktreeRunLocked || startPending}
                  onClick={onStartRun}
                >
                  {startPending ? <LoaderCircle size={15} className={styles.spinning} /> : <ArrowUpRight size={15} />}
                  {t("startSelfWorktreeRun")}
                </VButton>
              </div>
            </section>

            <section className={`${styles.petCompanionSurface} ${styles[`petCompanionTone_${petCompanionState.tone}`]}`}>
              <div className={styles.sectionHeader}>
                <div>
                  <p className={styles.eyebrow}>{t("petSelfCompanion")}</p>
                  <h3 className={styles.sectionTitle}>{pet?.name ?? t("loadingPetState")}</h3>
                </div>
                <span className={styles.statusPill}>{t(petCompanionState.stateKey)}</span>
              </div>

              <div className={styles.petAvatarStage}>
                <div className={styles.petAvatarHalo} />
                <div className={styles.petAvatarMark} aria-label={pet?.name ?? "pet"} role="img">
                  <span className={styles.petAvatarClaw} />
                  <span className={styles.petAvatarBody} />
                  <span className={styles.petAvatarClaw} />
                </div>
                <div className={styles.petAvatarBadge}>{petPresetLabel} {t("preset")}</div>
              </div>

              <div className={styles.petCompanionCopy}>
                <p>{t(petCompanionState.detailKey)}</p>
                <span>{pet?.statusLine ?? t("readingCompanionState")}</span>
                <span>{petCompanionLine}</span>
              </div>
            </section>

            <section className={styles.surface}>
              <div className={styles.sectionHeader}>
                <div>
                  <p className={styles.eyebrow}>{t("petSpace")}</p>
                  <h3 className={styles.sectionTitle}>{t("mood")} / {t("heart")}</h3>
                </div>
                <span className={styles.secondaryPill}>{pet?.mood ?? 0}</span>
              </div>

              <div className={styles.compactMetricGrid}>
                <article className={styles.stripItem}>
                  <span>{t("tokens")}</span>
                  <strong>{pet?.totalTokens ?? 0}</strong>
                </article>
                <article className={styles.stripItem}>
                  <span>{t("dailyTokens")}</span>
                  <strong>{pet?.dailyTokens ?? 0}</strong>
                </article>
                <article className={styles.stripItem}>
                  <span>{t("heart")}</span>
                  <strong>{pet?.heartActive ? t("heartActive") : t("heartIdle")}</strong>
                </article>
                <article className={styles.stripItem}>
                  <span>{t("dream")}</span>
                  <strong>{pet?.inDream ? t("dreamSleeping") : t("dreamAwake")}</strong>
                </article>
              </div>

              <div className={styles.vitalList}>
                {petVitals.map((vital) => (
                  <div key={vital.key} className={styles.vitalItem}>
                    <div className={styles.itemTop}>
                      <strong>{vital.label}</strong>
                      <span className={styles.secondaryPill}>{vital.value}</span>
                    </div>
                    <div className={styles.vitalTrack}>
                      <div className={styles.vitalFill} style={{ width: `${vital.value}%` }} />
                    </div>
                  </div>
                ))}
              </div>
            </section>
          </aside>

          <PaneCollapseHandle
            side="left"
            collapsed={sidebarCollapsed}
            separatorLabel={lang === "zh" ? "调整自进化侧栏宽度" : "Resize self-evolution sidebar"}
            collapseLabel={lang === "zh" ? "收起自进化侧栏" : "Collapse self-evolution sidebar"}
            expandLabel={lang === "zh" ? "展开自进化侧栏" : "Expand self-evolution sidebar"}
            className={styles.sidebarResizer}
            onToggle={() => setSidebarCollapsed((current) => !current)}
            onPointerDown={beginSidebarResize}
          />

          <main className={styles.centerColumn}>
            <div className={styles.workflowCardGrid} aria-label={lang === "zh" ? "自进化步骤导航" : "Self-evolution workflow"}>
              {workflowSteps.map((step) => {
                const definition = SELF_EVOLUTION_WORKFLOW_STEPS.find((item) => item.id === step.id);
                const selected = selectedWorkflowStep?.id === step.id;
                return (
                  <VButton
                    key={step.id}
                    type="button"
                    className={selected ? `${styles.workflowCard} ${styles.workflowCardActive}` : styles.workflowCard}
                    aria-pressed={selected}
                    onClick={() => setSelectedWorkflowStepId(step.id as SelfEvolutionWorkflowStepId)}
                  >
                    <span>{definition ? (lang === "zh" ? definition.zh : definition.en) : step.label}</span>
                    <strong>{statusLabel(step.status)}</strong>
                    <small>{step.livePreview || step.summary || "--"}</small>
                  </VButton>
                );
              })}
            </div>
            <div className={styles.conversationShell}>
              {selectedWorkflowStep?.id === "approval" ? (
                <section className={styles.approvalPanel}>
                  <div className={styles.subsurfaceHeader}>
                    <div>
                      <p className={styles.eyebrow}>{approvalStep.label}</p>
                      <h3 className={styles.sectionTitle}>{lang === "zh" ? "人工审批" : "Human approval"}</h3>
                    </div>
                    <span className={styles.statusPill}>{statusLabel(approvalStep.status)}</span>
                  </div>
                  <div className={styles.detailStack}>
                    {approvalEvidenceItems.map((item) => (
                      <div key={item.label} className={styles.detailRow}>
                        <span>{item.label}</span>
                        <strong>{item.value}</strong>
                      </div>
                    ))}
                  </div>
                  <div className={styles.conversationActions}>
                    <VButton
                      type="button"
                      className={styles.secondaryAction}
                      isDisabled={!worktreeRun || worktreeActionPending || !approveReviewAction?.enabled}
                      title={disabledReason(approveReviewAction) || undefined}
                      onClick={() => worktreeRun && onWorktreeAction(worktreeRun.runId, "approve_review")}
                    >
                      {worktreeActionPending ? <LoaderCircle size={15} className={styles.spinning} /> : <CheckSquare size={15} />}
                      {lang === "zh" ? "通过审批" : "Approve"}
                    </VButton>
                    <VButton
                      type="button"
                      className={styles.secondaryAction}
                      isDisabled={!worktreeRun || worktreeActionPending || !mergeAction?.enabled}
                      title={disabledReason(mergeAction) || undefined}
                      onClick={() => worktreeRun && onWorktreeAction(worktreeRun.runId, "merge")}
                    >
                      {worktreeActionPending ? <LoaderCircle size={15} className={styles.spinning} /> : <ShieldCheck size={15} />}
                      {lang === "zh" ? "合并入库" : "Merge"}
                    </VButton>
                    <VButton
                      type="button"
                      className={styles.secondaryAction}
                      isDisabled={!worktreeRun || worktreeActionPending || !discardAction?.enabled}
                      title={disabledReason(discardAction) || undefined}
                      onClick={() => worktreeRun && onWorktreeAction(worktreeRun.runId, "discard")}
                    >
                      {worktreeActionPending ? <LoaderCircle size={15} className={styles.spinning} /> : <X size={15} />}
                      {lang === "zh" ? "丢弃候选" : "Discard"}
                    </VButton>
                  </div>
                </section>
              ) : (
                <LazyConversationView
                  sessionId={selectedWorkflowStep?.conversationSessionId || worktreeRun?.runId || "self-evolution"}
                  density="compact"
                  eyebrowLabel={selfEvolutionStep.label}
                  title={selectedWorkflowStep?.label || t("selfWorkspacePage")}
                  phase={selectedWorkflowStep?.status || worktreeRun?.status || overview.readiness.state}
                  messages={conversationMessages}
                  assistantDisplayName={pet?.name}
                  assistantAvatarFallback={petAvatarFallback}
                  userDisplayName={runtime?.userName}
                  taskSummary={conversationTask.latestSummary}
                  defaultFileContext={conversationTask.changedFiles.at(-1) || conversationTask.readFiles.at(-1) || "workspace"}
                  summaryItems={[]}
                  stats={[
                    { label: t("selfGoal"), value: conversationTask.goal },
                    { label: t("selfTransactions"), value: transactionItems.length },
                    { label: t("filesChanged"), value: changedFiles.length || overview.worktree.dirtyFileCount },
                    { label: t("lastUpdated"), value: compactTimestamp(conversationTask.updatedAt) },
                  ]}
                  headerActions={(
                    <div className={styles.conversationActions}>
                      {runIsActive && worktreeRun ? (
                        <VButton
                          type="button"
                          className={styles.secondaryAction}
                          isDisabled={worktreeActionPending || !terminateAction?.enabled}
                          title={disabledReason(terminateAction) || undefined}
                          onClick={() => onWorktreeAction(worktreeRun.runId, "terminate")}
                        >
                          {worktreeActionPending ? <LoaderCircle size={15} className={styles.spinning} /> : <X size={15} />}
                          {terminateRequested ? t("selfStopRequested") : t("stopSelfRun")}
                        </VButton>
                      ) : null}
                    </div>
                  )}
                  autoScrollToLatest={runIsActive}
                  composerValue={goalInput}
                  composerPlaceholder={t("selfGoalPlaceholder")}
                  composerDisabled={!startSelfAction?.enabled || runLocked || worktreeRunLocked || startPending}
                  composerPending={startPending}
                  submitLabel={t("startSelfWorktreeRun")}
                  submitPendingLabel={t("loading")}
                  onComposerChange={onGoalInputChange}
                  onSubmit={onStartRun}
                  fallback={<div className={styles.loadingShell}>{t("loadingSession")}</div>}
                />
              )}
            </div>
          </main>
        </div>
      ) : (
        <div className={styles.statusPage}>
          <div className={styles.panelStack}>
            <div className={styles.metricStrip}>
              <article className={styles.stripItem}>
                <span>{t("sceneStateTitle")}</span>
                <strong>{sceneSemantics?.sceneTitle || statusLabel(overview.readiness.state)}</strong>
              </article>
              <article className={styles.stripItem}>
                <span>{t("currentRunTitle")}</span>
                <strong>{runSemantics?.phaseLabel || runSemantics?.runStatusLabel || "--"}</strong>
              </article>
              <article className={styles.stripItem}>
                <span>{t("rollbackStateTitle")}</span>
                <strong>{statusLabel(reviewGate?.status || worktreeRun?.mergeAnalysis?.status || "pending")}</strong>
              </article>
              <article className={styles.stripItem}>
                <span>{t("selfTransactions")}</span>
                <strong>{transactionItems.length}</strong>
              </article>
            </div>

            {actionFeedback || errorMessage ? (
              <div className={styles.noticeBanner}>
                {actionFeedback ? <p className={styles.feedbackText}>{actionFeedback}</p> : null}
                {errorMessage ? <p className={styles.errorText}>{errorMessage}</p> : null}
              </div>
            ) : null}

            <div className={styles.supportColumns}>
              <section className={styles.subsurface}>
                <div className={styles.subsurfaceHeader}>
                  <div>
                    <p className={styles.eyebrow}>{t("sceneStateTitle")}</p>
                    <h4 className={styles.subsurfaceTitle}>{sceneSemantics?.sceneTitle || t("selfWorktree")}</h4>
                  </div>
                  <span className={styles.secondaryPill}>
                    {overview.worktree.snapshotId || compactRevision(overview.worktree.baseRev)}
                  </span>
                </div>

                <div className={styles.detailStack}>
                  <div className={styles.detailRow}>
                    <span>{t("sceneStateTitle")}</span>
                    <strong>{sceneSemantics?.sceneTitle || statusLabel(overview.readiness.state)}</strong>
                  </div>
                  <div className={styles.detailRow}>
                    <span>{t("currentRunTitle")}</span>
                    <strong>{runSemantics?.phaseLabel || runSemantics?.runStatusLabel || "--"}</strong>
                  </div>
                  <div className={styles.detailRow}>
                    <span>{t("rollbackStateTitle")}</span>
                    <strong>{statusLabel(reviewGate?.status || worktreeRun?.mergeAnalysis?.status || "pending")}</strong>
                  </div>
                  <div className={styles.detailRow}>
                    <span>{t("dirtyFlags")}</span>
                    <strong>{worktreeFlags.join(" / ") || t("worktreeClean")}</strong>
                  </div>
                </div>

                <div className={styles.subsection}>
                  <h5 className={styles.subsectionTitle}>{t("selfCurrentState")}</h5>
                  <div className={styles.listBlock}>
                    {currentStateNotes.map((item) => (
                      <div key={item} className={styles.listItem}>
                        {item}
                      </div>
                    ))}
                  </div>
                </div>

                <div className={styles.subsection}>
                  <div className={styles.paginationBar}>
                    <h5 className={styles.subsectionTitle}>{t("filesChanged")}</h5>
                    <div className={styles.paginationGroup}>
                      <span className={styles.mutedText}>
                        {worktreeFiles.length > 0
                          ? `${worktreePageStart}-${worktreePageEnd} / ${worktreeFiles.length}`
                          : `0 / ${worktreeFiles.length}`}
                      </span>
                      <VButton
                        type="button"
                        className={styles.paginationButton}
                        isDisabled={clampedWorktreePage <= 1}
                        onClick={() => setWorktreePage((current) => Math.max(1, current - 1))}
                        title={t("pagePrevious")}
                      >
                        <ChevronLeft size={15} />
                      </VButton>
                      {pageNumbers.map((page) => (
                        <VButton
                          key={page}
                          type="button"
                          className={page === clampedWorktreePage ? `${styles.paginationButton} ${styles.paginationButtonActive}` : styles.paginationButton}
                          onClick={() => setWorktreePage(page)}
                        >
                          {page}
                        </VButton>
                      ))}
                      <VButton
                        type="button"
                        className={styles.paginationButton}
                        isDisabled={clampedWorktreePage >= totalWorktreePages}
                        onClick={() => setWorktreePage((current) => Math.min(totalWorktreePages, current + 1))}
                        title={t("pageNext")}
                      >
                        <ChevronRight size={15} />
                      </VButton>
                    </div>
                  </div>

                  <div className={styles.worktreeFiles}>
                    {currentWorktreeFiles.length === 0 ? (
                      <div className={styles.listItem}>{overview.worktree.error || compactWorktreeSummary}</div>
                    ) : (
                      currentWorktreeFiles.map((file) => (
                        <div key={`${file.status}-${file.path}`} className={styles.listItem}>
                          <div className={styles.itemTop}>
                            <strong>{file.path}</strong>
                            <span className={styles.secondaryPill}>{file.status}</span>
                          </div>
                          <span className={styles.mutedText}>{worktreeFileFlags(t, file) || t("worktreeClean")}</span>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </section>

              <section className={styles.subsurface}>
                <div className={styles.subsurfaceHeader}>
                  <div>
                    <p className={styles.eyebrow}>{approvalStep.label}</p>
                    <h4 className={styles.subsurfaceTitle}>{worktreeRun?.runId || (lang === "zh" ? "等待候选" : "Waiting for candidate")}</h4>
                  </div>
                  <ShieldCheck size={16} className={styles.headerIcon} />
                </div>

                {worktreeRun ? (
                  <>
                    <p className={styles.sectionSummary}>{worktreeRun.mergeAnalysis?.reason || worktreeRun.decision?.reason || approvalStep.summary}</p>
                    <div className={styles.detailStack}>
                      {approvalEvidenceItems.map((item) => (
                        <div key={item.label} className={styles.detailRow}>
                          <span>{item.label}</span>
                          <strong>{item.value}</strong>
                        </div>
                      ))}
                    </div>
                    <div className={styles.listBlock}>
                      {changedFiles.length === 0 ? (
                        <div className={styles.listItem}>{lang === "zh" ? "暂无候选变更文件。" : "No candidate changed files yet."}</div>
                      ) : (
                        changedFiles.slice(0, 8).map((item) => (
                          <div key={`${item.path}-${item.changeType || item.status}`} className={styles.listItem}>
                            <div className={styles.itemTop}>
                              <strong>{item.path}</strong>
                              <span className={styles.secondaryPill}>{item.changeType || item.status}</span>
                            </div>
                            <span className={styles.mutedText}>
                              {item.highRisk ? (lang === "zh" ? "高风险路径" : "High risk path") : item.status || "--"}
                            </span>
                          </div>
                        ))
                      )}
                    </div>
                  </>
                ) : (
                  <div className={styles.emptyState}>{lang === "zh" ? "启动一轮自进化后，这里会显示审批证据。" : "Start a self-evolution run to show approval evidence here."}</div>
                )}
              </section>
            </div>

            <div className={styles.supportColumns}>
              <section className={styles.subsurface}>
                <div className={styles.subsurfaceHeader}>
                  <div>
                    <p className={styles.eyebrow}>{t("selfTransactions")}</p>
                    <h4 className={styles.subsurfaceTitle}>{t("selfTransactions")}</h4>
                  </div>
                  <div className={styles.headerActionCluster}>
                    <span className={styles.counter}>{transactionItems.length}</span>
                    <VButton
                      type="button"
                      className={styles.selectionToggle}
                      isDisabled={visibleTransactionIds.length === 0}
                      onClick={toggleAllVisibleHistoryGroups}
                    >
                      <CheckSquare size={14} />
                      {allVisibleHistorySelected ? t("clearSelection") : t("selectForBatchDelete")}
                    </VButton>
                  </div>
                </div>

                <div className={styles.transactionFilterBar} aria-label={t("selfTransactionFilterLabel")}>
                  {transactionFilterOptions.map((option) => (
                    <VButton
                      key={option.id}
                      type="button"
                      className={
                        option.id === transactionFilter
                          ? `${styles.transactionFilterButton} ${styles.transactionFilterButtonActive}`
                          : styles.transactionFilterButton
                      }
                      onClick={() => setTransactionFilter(option.id)}
                    >
                      <span>{option.label}</span>
                      <strong>{option.count}</strong>
                    </VButton>
                  ))}
                </div>

                <div className={styles.transactionDateFilterBar} aria-label={t("selfTransactionDateFilterLabel")}>
                  <span>{t("selfTransactionDateFilterLabel")}</span>
                  <VButton
                    type="button"
                    className={
                      transactionDateFilter === "all"
                        ? `${styles.transactionFilterButton} ${styles.transactionFilterButtonActive}`
                        : styles.transactionFilterButton
                    }
                    onClick={() => setTransactionDateFilter("all")}
                  >
                    <span>{t("selfTransactionDateAll")}</span>
                    <strong>{filteredTransactions.length}</strong>
                  </VButton>
                  {transactionDateOptions.map((option) => (
                    <VButton
                      key={option.key}
                      type="button"
                      className={
                        option.key === transactionDateFilter
                          ? `${styles.transactionFilterButton} ${styles.transactionFilterButtonActive}`
                          : styles.transactionFilterButton
                      }
                      onClick={() => setTransactionDateFilter(option.key)}
                    >
                      <span>{option.label}</span>
                      <strong>{option.count}</strong>
                    </VButton>
                  ))}
                </div>

                <div className={styles.historyToolbar}>
                  <span className={styles.noticeText}>
                    {t("selfHistoryGroup")} {t("selectedCount")} {selectedHistoryTxnIds.length}
                  </span>
                  <div className={styles.toolbarActions}>
                    <span className={styles.transactionVisibleSummary}>
                      {lang === "zh"
                        ? `${t("selfTransactionVisibleSummary")} ${visibleTransactions.length}/${dateFilteredTransactions.length} 条`
                        : `${t("selfTransactionVisibleSummary")} ${visibleTransactions.length}/${dateFilteredTransactions.length}`}
                      {hiddenTransactionCount > 0 ? ` · ${hiddenTransactionCount} ${t("selfTransactionHiddenSuffix")}` : ""}
                    </span>
                    {dateFilteredTransactions.length > SELF_TRANSACTION_COLLAPSED_LIMIT ? (
                      <VButton
                        type="button"
                        className={styles.secondaryAction}
                        onClick={() => setTransactionHistoryExpanded((current) => !current)}
                      >
                        {transactionHistoryExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                        {transactionHistoryExpanded ? t("selfTransactionCollapseRecent") : t("selfTransactionShowAll")}
                      </VButton>
                    ) : null}
                    <VButton
                      type="button"
                      className={styles.secondaryAction}
                      isDisabled={selectedHistoryTxnIds.length === 0 || deleteHistoryPending}
                      onClick={() => setSelectedHistoryTxnIds([])}
                    >
                      <X size={14} />
                      {t("clearSelection")}
                    </VButton>
                    <VButton
                      type="button"
                      className={styles.secondaryAction}
                      isDisabled={selectedHistoryTxnIds.length === 0 || deleteHistoryPending}
                      title={selectedHistoryTxnIds.length === 0 ? t("deleteSelectedDisabledHistory") : undefined}
                      onClick={() => onDeleteHistoryGroups(selectedHistoryTxnIds)}
                    >
                      {deleteHistoryPending ? <LoaderCircle size={15} className={styles.spinning} /> : <ScrollText size={15} />}
                      {deleteHistoryPending ? t("deletingSelectedHistory") : t("deleteSelected")}
                    </VButton>
                  </div>
                </div>
                <p className={styles.noticeText}>{t("batchDeleteHint")}</p>

                <div className={styles.listBlock}>
                  {transactionItems.length === 0 ? (
                    <div className={styles.emptyState}>{t("selfNoTransactions")}</div>
                  ) : visibleTransactions.length === 0 ? (
                    <div className={styles.emptyState}>{t("selfTransactionFilterEmpty")}</div>
                  ) : (
                    visibleTransactionGroups.map((group) => (
                      <div key={group.key} className={styles.transactionDateGroup}>
                        <div className={styles.transactionDateHeader}>
                          <strong>{group.label}</strong>
                          <span>
                            {lang === "zh"
                              ? `${group.count}条 · ${group.needsReviewCount}条需复盘`
                              : `${group.count} items · ${group.needsReviewCount} need review`}
                          </span>
                        </div>
                        <div className={styles.transactionGroupList}>
                          {group.items.map((item) => {
                            const displayTitle = buildTransactionDisplayTitle(item, {
                              closedLabel: lang === "zh" ? "已收口事务" : "Closed transaction",
                              openLabel: lang === "zh" ? "进行中事务" : "Open transaction",
                            });
                            const outcomeLabel = buildTransactionOutcomeLabel(item, lang);
                            const validationLabel = lang === "zh"
                              ? `验证 ${item.validationPassed}/${item.validationFailed}`
                              : `Validation ${item.validationPassed}/${item.validationFailed}`;
                            const mutationLabel = lang === "zh"
                              ? `变更 ${item.mutationsRecorded} · 阻塞 ${item.mutationsBlocked}`
                              : `Changes ${item.mutationsRecorded} · blocked ${item.mutationsBlocked}`;
                            const durationLabel = lang === "zh"
                              ? `耗时 ${compactDuration(item.durationSeconds, lang)}`
                              : `Duration ${compactDuration(item.durationSeconds, lang)}`;
                            const evidenceLabel = lang === "zh"
                              ? `证据 ${item.auditEventCount}`
                              : `Evidence ${item.auditEventCount}`;
                            const detailsExpanded = expandedHistorySet.has(item.txnId);
                            const batchLabel = buildTransactionBatchLabel(item, lang);
                            return (
                              <div
                                key={item.txnId}
                                className={
                                  selectedHistorySet.has(item.txnId)
                                    ? `${styles.listItem} ${styles.listItemSelected}`
                                    : styles.listItem
                                }
                              >
                                <div className={styles.itemTop}>
                                  <label className={styles.checkboxRow}>
                                    <VNativeInput
                                      type="checkbox"
                                      checked={selectedHistorySet.has(item.txnId)}
                                      onChange={() => toggleHistorySelection(item.txnId)}
                                    />
                                    <span className={styles.transactionTitleStack}>
                                      <strong>{displayTitle}</strong>
                                      <span>{batchLabel} · {compactTimestamp(item.closedAt || item.openedAt)} · {item.txnId}</span>
                                    </span>
                                  </label>
                                  <div className={styles.pillRow}>
                                    <span className={styles.secondaryPill}>{outcomeLabel}</span>
                                    <span className={styles.secondaryPill}>{statusLabel(item.status)}</span>
                                    <span className={styles.secondaryPill}>{t("selfLinkedAuditCount")} {auditCountByTxnId.get(item.txnId) || 0}</span>
                                    <VButton
                                      type="button"
                                      className={styles.transactionDetailsToggle}
                                      aria-expanded={detailsExpanded}
                                      onClick={() => toggleTransactionDetails(item.txnId)}
                                    >
                                      {detailsExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                                      {detailsExpanded ? t("hideDetails") : t("showDetails")}
                                    </VButton>
                                  </div>
                                </div>
                                <div className={styles.transactionMetaGrid}>
                                  <span>{validationLabel}</span>
                                  <span>{mutationLabel}</span>
                                  <span>{durationLabel}</span>
                                  <span>{evidenceLabel}</span>
                                </div>
                                {detailsExpanded ? (
                                  <div className={styles.transactionDetailsPanel}>
                                    <div className={styles.transactionDetailRow}>
                                      <span>{t("selfGoal")}</span>
                                      <strong>{item.goalPreview || item.summary || "--"}</strong>
                                    </div>
                                    <div className={styles.transactionDetailRow}>
                                      <span>{t("selfFinishedAt")}</span>
                                      <strong>{compactTimestamp(item.closedAt || item.openedAt)}</strong>
                                    </div>
                                    <div className={styles.transactionDetailRow}>
                                      <span>{t("sourceRun")}</span>
                                      <strong>{compactRevision(item.baseRevShort || item.baseRev)}</strong>
                                    </div>
                                    <div className={styles.transactionDetailRow}>
                                      <span>{t("selfAuditTrail")}</span>
                                      <strong>{item.lastAuditEvent || "--"}</strong>
                                    </div>
                                  </div>
                                ) : item.goalPreview ? (
                                  <p className={styles.transactionGoalPreview}>{item.goalPreview}</p>
                                ) : null}
                                <span className={styles.mutedText}>
                                  {compactRevision(item.baseRevShort || item.baseRev)}
                                  {item.lastAuditEvent ? ` · ${item.lastAuditEvent}` : ""}
                                </span>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </section>

              <section className={styles.subsurface}>
                <div className={styles.subsurfaceHeader}>
                  <div>
                    <p className={styles.eyebrow}>{t("selfAuditTrail")}</p>
                    <h4 className={styles.subsurfaceTitle}>{t("selfAuditTrail")}</h4>
                  </div>
                  <span className={styles.counter}>{overview.auditTail.length}</span>
                </div>

                <div className={styles.listBlock}>
                  {visibleAuditTrail.length === 0 ? (
                    <div className={styles.emptyState}>{t("selfNoAudit")}</div>
                  ) : (
                    visibleAuditTrail.map((item) => (
                      <div
                        key={`${item.timestamp}-${item.event}-${item.txnId}`}
                        className={
                          item.txnId && selectedHistorySet.has(item.txnId)
                            ? `${styles.listItem} ${styles.listItemSelected}`
                            : styles.listItem
                        }
                      >
                        <div className={styles.itemTop}>
                          <strong>{item.event}</strong>
                          <div className={styles.pillRow}>
                            {item.txnId ? (
                              <span className={styles.secondaryPill}>{t("selfHistoryGroup")} {item.txnId}</span>
                            ) : null}
                            <span className={styles.secondaryPill}>{item.txnId || "--"}</span>
                          </div>
                        </div>
                        <span className={styles.mutedText}>{item.summary}</span>
                      </div>
                    ))
                  )}
                </div>
              </section>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
