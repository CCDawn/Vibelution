import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowUpRight,
  ChevronDown,
  ChevronRight,
  CheckCircle2,
  Clock3,
  Gauge,
  LibraryBig,
  LoaderCircle,
  Pause,
  Play,
  RefreshCw,
  Save,
  Sparkles,
  Square,
  Pencil,
  Trash2,
  TriangleAlert,
  Wrench,
  X,
} from "lucide-react";
import { Suspense, lazy, type CSSProperties, type KeyboardEvent, type PointerEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  EvolutionRunStartResponse,
  EvolutionRunCommandAccepted,
  EvolutionRunCommandStatus,
  EvolutionRunDeleteResponse,
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
  ConversationMessage,
} from "../api/types";
import { resolvePollingInterval, usePageVisibility } from "../app/pollingPolicy";
import { PaneCollapseHandle } from "../components/layout/PaneCollapseHandle";
import { LazyConversationView } from "../components/conversation/LazyConversationView";
import { useAppI18n } from "../i18n/useAppI18n";
import { useShellStore } from "../store/shellStore";
import { SupervisedWorkspaceControls } from "./SupervisedWorkspaceControls";
import { type SupervisedWorkspaceWorkflowStep } from "./SupervisedWorkspaceTabs";
import { isSelfEvolutionWorktreeRun } from "./supervisedWorktreeReview";
import {
  isCompletedEvolutionRunCommandFailure,
  isCompletedEvolutionRunCommandSuccess,
  isLiveSupervisedRunStatus,
  isEvolutionRunCommandAccepted,
  parseRunStreamSnapshot,
  requireEvolutionRunSnapshot,
  selectRunSnapshotWithRunId,
  selectSupervisedRunStreamTarget,
  shouldIgnoreActiveRunSnapshot,
} from "./evolutionLiveRun";
import { buildSupervisedRunRecordDisplay, supervisedDecisionLabel } from "./supervisedRunRecordLabel";
import { buildSupervisedRunControlSummary } from "./supervisedRunSummary";
import { buildSupervisedCaseTraceItems, type SupervisedCaseTraceItem } from "./supervisedCaseTrace";
import { createEvolutionWorkspaceCache } from "./evolutionWorkspaceCache";
import { modelDisplayLabel } from "./agentDisplay";
import {
  clampPaneSize,
  clampPaneWidth,
  keyboardPaneHeight,
  keyboardPaneWidth,
  storedPaneSize,
  storedPaneWidth,
} from "./resizablePane";
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
type DatasetCatalogFilter = "all" | "runnable" | "blocked" | "roadmap";
type EvolutionRouteTrack = "supervised" | "self";
type SupervisedRouteView = "live" | "runs" | "library";
type EvolutionRouteProps = {
  forcedTrack?: EvolutionRouteTrack;
  forcedView?: SupervisedRouteView;
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

type SupervisedMemberRole = "baseline" | "candidate" | "reviewer" | "auditor" | "judge";
type SupervisedWorkflowStepId = "baseline_eval" | "improve" | "rerun_score" | "approval";
type SupervisedRunMember = {
  role: SupervisedMemberRole;
  label: string;
  name: string;
  model: string;
  modelId: string;
  agentId: string;
  status: "active" | "configured" | "missing";
  conversationSession?: EvolutionRoleConversationSession;
  chatRoute: string;
  configRoute: string;
};
type SupervisedClosedLoopRecord = EvolutionClosedLoopRecord;
type SupervisedWorkflowDefinition = {
  id: SupervisedWorkflowStepId;
  zh: string;
  en: string;
  role: SupervisedMemberRole | null;
};
type SupervisedWorkflowCard = EvolutionWorkflowStep & {
  id: SupervisedWorkflowStepId;
  member?: SupervisedRunMember;
};

type SupervisedPreflightIssue = {
  title: string;
  detail: string;
  reason: string;
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
const EVOLUTION_LIVE_IO_DEFAULT_HEIGHT = 340;
const SUPERVISED_RUN_MEMBER_ROLES: SupervisedMemberRole[] = ["baseline", "candidate"];
const SUPERVISED_WORKFLOW_STEPS: SupervisedWorkflowDefinition[] = [
  { id: "baseline_eval", zh: "基线评测", en: "Baseline", role: "baseline" },
  { id: "improve", zh: "提出建议与改良", en: "Improve", role: "candidate" },
  { id: "rerun_score", zh: "复跑与评分", en: "Rerun + Score", role: "candidate" },
  { id: "approval", zh: "用户审批", en: "Approval", role: null },
];
const LOCAL_SUPERVISED_RUN_PREFIX = "local-supervised-start-";
const LazySelfEvolutionTrack = lazy(() =>
  import("./SelfEvolutionTrack").then((module) => ({ default: module.SelfEvolutionTrack })),
);

type ProposalEditDraft = {
  improvementType: string;
  expectedEffect: string;
  summary: string;
  candidatePrompt: string;
  baselinePrompt: string;
  editNote: string;
};

type SupervisedMentalModelMode = "follow" | "enabled" | "disabled";

function clampScore(value: number) {
  return Math.max(0, Math.min(100, Math.round(value)));
}

function isLocalSupervisedStartPlaceholder(run: EvolutionActiveRun | null | undefined): run is EvolutionActiveRun {
  return String(run?.runId || "").startsWith(LOCAL_SUPERVISED_RUN_PREFIX);
}

function buildSupervisedStartPlaceholder(input: {
  sourceKind: "dataset" | "bundle";
  datasetName: string;
  datasetLimit: number | null;
  bundleName: string;
  keepWorktree: boolean;
  mentalModelMode: SupervisedMentalModelMode;
  agentBindings?: Record<string, EvolutionActiveRunAgentBinding>;
  lang: "zh" | "en";
}): EvolutionActiveRun {
  const timestamp = new Date().toISOString();
  const sourceKind = input.sourceKind;
  const sourceName = sourceKind === "dataset" ? input.datasetName : input.bundleName;
  const isZh = input.lang === "zh";
  const summary = isZh
    ? `正在提交监督运行请求，来源${sourceKind === "dataset" ? "数据集" : "评测包"} ${sourceName || "--"}。`
    : `Submitting supervised run request from ${sourceKind === "dataset" ? "dataset" : "bundle"} ${sourceName || "--"}.`;

  return {
    runId: `${LOCAL_SUPERVISED_RUN_PREFIX}${Date.now()}`,
    status: "queued",
    currentPhase: "submitted",
    runtimeStatus: "submitted",
    sourceKind,
    sessionId: "",
    bundleName: sourceKind === "bundle" ? input.bundleName : "",
    datasetName: sourceKind === "dataset" ? input.datasetName : "",
    datasetLimit: input.datasetLimit,
    keepWorktree: input.keepWorktree,
    mentalModelMode: input.mentalModelMode,
    mentalModelEnabled: input.mentalModelMode === "enabled" ? true : input.mentalModelMode === "disabled" ? false : null,
    startedAt: timestamp,
    updatedAt: timestamp,
    finishedAt: "",
    caseTotal: 0,
    currentCaseIndex: 0,
    currentCaseId: "",
    currentRole: "",
    currentCaseScenario: "",
    currentCaseMode: "",
    currentCasePrompt: "",
    currentAgentBinding: {},
    currentCaseIo: null,
    currentTask: isZh ? "启动请求已提交，等待后端接收并返回真实运行记录。" : "Start request submitted; waiting for the backend to return the real run record.",
    decision: "",
    reason: "",
    decisionPath: "",
    policyAction: "",
    lineageIndexPath: "",
    lineageSummary: "",
    activeAdvisoryCount: 0,
    pauseRequested: false,
    pauseRequestedAt: "",
    pausedAt: "",
    stopRequested: false,
    stopRequestedAt: "",
    latestMessage: summary,
    eventTail: [
      {
        timestamp,
        event: "start_submitted",
        title: isZh ? "启动请求已提交" : "Start request submitted",
        summary,
        status: "queued",
        sourceKind,
        datasetName: sourceKind === "dataset" ? input.datasetName : "",
        datasetLimit: input.datasetLimit,
        bundleName: sourceKind === "bundle" ? input.bundleName : "",
        keepWorktree: input.keepWorktree,
        mentalModelMode: input.mentalModelMode,
        mentalModelEnabled: input.mentalModelMode === "enabled" ? true : input.mentalModelMode === "disabled" ? false : null,
      },
    ],
    agentBindings: input.agentBindings ?? {},
    actionStates: {
      pause: { enabled: false, reason: isZh ? "等待真实运行记录返回后才能暂停。" : "Pause is available after the real run record is returned." },
      resume: { enabled: false, reason: isZh ? "启动请求尚未进入可恢复状态。" : "The start request is not resumable yet." },
      retry: { enabled: false, reason: isZh ? "启动完成或失败后才能重跑。" : "Retry is available after the start completes or fails." },
      terminate: { enabled: false, reason: isZh ? "等待真实运行记录返回后才能终止。" : "Terminate is available after the real run record is returned." },
      delete: { enabled: false, reason: isZh ? "本地启动占位不会写入运行记录。" : "This local placeholder is not persisted as a run record." },
    },
  };
}

function hasSupervisedAgentBindings(bindings: Record<string, EvolutionActiveRunAgentBinding> | null | undefined) {
  return Boolean(bindings && Object.keys(bindings).length > 0);
}

function supervisedWorkflowStepLabel(step: SupervisedWorkflowDefinition | SupervisedWorkflowCard, lang: "zh" | "en") {
  if ("label" in step && step.label) {
    return step.label;
  }
  const definition = SUPERVISED_WORKFLOW_STEPS.find((item) => item.id === step.id);
  return lang === "zh" ? definition?.zh ?? step.id : definition?.en ?? step.id;
}

function activeSupervisedWorkflowStep(run: EvolutionActiveRun | null | undefined): SupervisedWorkflowStepId {
  const backendCurrent = (run?.workflowSteps ?? []).find((step) => step.current);
  const backendId = String(backendCurrent?.id || "").trim() as SupervisedWorkflowStepId;
  if (SUPERVISED_WORKFLOW_STEPS.some((step) => step.id === backendId)) {
    return backendId;
  }
  const role = String(run?.currentRole || "").trim().toLowerCase();
  const phase = String(run?.currentPhase || run?.runtimeStatus || "").trim().toLowerCase();
  const status = String(run?.status || "").trim().toLowerCase();
  const decision = String(run?.decision || "").trim().toUpperCase();
  const hasProposalSignal = Boolean(
    decision
    || String(run?.decisionPath || "").trim()
    || String(run?.policyAction || "").trim(),
  );
  if (role === "baseline") {
    return "baseline_eval";
  }
  if (role === "candidate") {
    return "rerun_score";
  }
  if (hasProposalSignal || (status === "done" && decision)) {
    return "approval";
  }
  if (
    ["reflection", "candidate_worktree", "candidate_modify"].includes(phase)
  ) {
    return "improve";
  }
  if (
    ["candidate_evaluation", "decision"].includes(phase)
  ) {
    return "rerun_score";
  }
  if (
    ["submitted", "queued", "preflight", "session_start", "starting", "baseline"].includes(phase)
    || ["submitted", "queued", "running"].includes(status)
  ) {
    return "baseline_eval";
  }
  return "baseline_eval";
}

function supervisedMemberModelId(binding: EvolutionActiveRunAgentBinding | undefined) {
  return String(
    binding?.dialogueModelId
    || binding?.llmBindings?.dialogue?.modelId
    || binding?.llmBindings?.primary?.modelId
    || "",
  ).trim();
}

function supervisedMemberModelLabel(
  binding: EvolutionActiveRunAgentBinding | undefined,
  resolveModelLabel?: (modelId: string) => string | undefined,
) {
  const bindingLabel = String(binding?.dialogueModelLabel || binding?.dialogueModelName || "").trim();
  return bindingLabel || modelDisplayLabel(supervisedMemberModelId(binding), resolveModelLabel) || "--";
}

function supervisedMemberAgentManagementRoute(agentId: string, returnTo: string) {
  const params = new URLSearchParams({ pane: "config", returnLabel: "supervised_evolution" });
  const normalizedAgentId = String(agentId || "").trim();
  const normalizedReturnTo = String(returnTo || "").trim();
  if (normalizedAgentId) {
    params.set("agent", normalizedAgentId);
  }
  if (normalizedReturnTo) {
    params.set("returnTo", normalizedReturnTo);
  }
  return `/agents?${params.toString()}`;
}

function supervisedMemberChatRoute(sessionId: string, returnTo: string, returnLabel: string) {
  const normalizedSessionId = String(sessionId || "").trim();
  if (!normalizedSessionId) {
    return "";
  }
  const params = new URLSearchParams({ session: normalizedSessionId });
  const normalizedReturnTo = String(returnTo || "").trim();
  const normalizedReturnLabel = String(returnLabel || "").trim();
  if (normalizedReturnTo) {
    params.set("returnTo", normalizedReturnTo);
  }
  if (normalizedReturnLabel) {
    params.set("returnLabel", normalizedReturnLabel);
  }
  return `/chat?${params.toString()}`;
}

function supervisedPreflightIssue(run: EvolutionActiveRun | null | undefined, lang: "zh" | "en"): SupervisedPreflightIssue | null {
  const latestPreflightEvent = [...(run?.eventTail ?? [])].reverse().find((event) => {
    const phase = String((event as { phase?: unknown }).phase || "").trim();
    const summary = String(event.summary || "").toLowerCase();
    const reason = String(event.reason || "").toLowerCase();
    return phase === "environment_preflight"
      || summary.includes("environment_preflight")
      || reason.includes("环境预检")
      || reason.includes("preflight");
  });
  const preflightSummary = String(latestPreflightEvent?.summary || "").trim();
  const preflightReason = String(latestPreflightEvent?.reason || "").trim();
  const runReason = String(run?.reason || "").trim();
  const latestMessage = String(run?.latestMessage || "").trim();
  const hasPreflightFailure =
    Boolean(latestPreflightEvent)
    || /missing_verifier_dependency|环境预检|预检状态|未启动 agent|not start(ed)? agent/i.test(`${runReason}\n${latestMessage}`);
  const terminal = ["done", "failed", "cancelled"].includes(String(run?.status || "").trim().toLowerCase());
  const noCaseIo = !run?.currentCaseIo?.latestOutput
    && !(run?.currentCaseIo?.transcript ?? []).length
    && !(run?.currentCaseIo?.conversationMessages ?? []).length;
  if (!hasPreflightFailure || !terminal || !noCaseIo) {
    return null;
  }

  const reason = preflightReason || runReason || preflightSummary || latestMessage;
  return {
    title: lang === "zh" ? "任务环境预检失败，未启动 Agent" : "Task environment preflight failed; no agent was started",
    detail: lang === "zh"
      ? "当前 case 没有 agent 输出，因为评测在验证环境检查阶段已结束。"
      : "There is no agent output for this case because evaluation stopped during verifier environment checks.",
    reason,
  };
}

function statusIcon(status: string, decision = "") {
  const normalized = String(status).trim().toLowerCase();
  const normalizedDecision = String(decision).trim().toUpperCase();
  if (normalizedDecision === "INCONCLUSIVE") {
    return <TriangleAlert size={16} />;
  }
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
  dataset: {
    effective?: boolean;
    usabilityStatus?: string;
    adapterStatus?: string;
    officialVerifierStatus?: string;
    evaluationMode?: string;
    scoreLabel?: string;
    caseCount?: number | null;
  },
  lang: string,
) {
  const status = String(dataset.usabilityStatus || "").trim();
  const caseCount = typeof dataset.caseCount === "number" ? dataset.caseCount : null;
  if (status === "custom_harness_ready" || status === "agent_harness_ready") {
    return lang === "zh" ? `自定义评测 ${caseCount ?? 0} 例` : `custom eval ${caseCount ?? 0} cases`;
  }
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
  if (String(dataset.officialVerifierStatus || "").trim() === "harbor_pending") {
    return lang === "zh" ? "官方判分待接" : "official verifier pending";
  }
  if (status === "invalid") {
    return lang === "zh" ? "格式异常" : "invalid";
  }
  if (status === "blocked") {
    return String(dataset.adapterStatus || status || "blocked");
  }
  return String(dataset.adapterStatus || status || (lang === "zh" ? "不可用" : "unavailable"));
}

function datasetCatalogStatusLabel(
  item: NonNullable<EvolutionWorkbench["datasets"]>[number],
  lang: string,
) {
  if (item.selectable !== false && item.effective && item.visibility === "primary") {
    return lang === "zh" ? "可运行" : "Runnable";
  }
  if (String(item.defaultVisibility || "").trim() === "roadmap" || item.usabilityStatus === "roadmap_only") {
    return lang === "zh" ? "路线图" : "Roadmap";
  }
  if (item.usabilityStatus === "missing_source") {
    return lang === "zh" ? "缺源文件" : "Missing source";
  }
  if (item.usabilityStatus === "requires_external_harness") {
    return lang === "zh" ? "需外部 harness" : "Needs harness";
  }
  if (item.usabilityStatus === "custom_harness_ready" && item.visibility !== "primary") {
    return lang === "zh" ? "环境未就绪" : "Environment blocked";
  }
  return lang === "zh" ? "未进入下拉" : "Hidden";
}

function datasetBenchmarkDetail(
  item: NonNullable<EvolutionWorkbench["datasets"]>[number],
  lang: string,
) {
  const base = `${item.bundleName || "--"} · ${lang === "zh" ? "数据集，运行前物化" : "dataset, materialized before run"}`;
  const taskType = String(item.taskType || "").trim();
  const budget = String(item.runBudgetClass || "").trim();
  const benchmarkBits = [taskType, budget].filter(Boolean);
  if (benchmarkBits.length === 0) {
    return base;
  }
  return `${base} · ${benchmarkBits.join(" · ")}`;
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

function supervisedRunBucketLabel(status: string, lang: "zh" | "en", statusLabel: (status: string) => string) {
  const normalized = String(status || "").trim().toLowerCase();
  if (normalized === "failed") {
    return lang === "zh" ? "异常收口" : "closed with issues";
  }
  return statusLabel(status);
}

function supervisedProposalStatusLabel(status: string, fallback: string, lang: "zh" | "en") {
  const raw = String(status || fallback || "").trim();
  const normalized = raw.toLowerCase();
  if (normalized === "rejected" || normalized === "reject") {
    return lang === "zh" ? "未入库" : "not stored";
  }
  if (normalized === "missing") {
    return lang === "zh" ? "无提案" : "no proposal";
  }
  return fallback || raw || "--";
}

function displaySupervisedRunStatus(run: EvolutionRun, lang: "zh" | "en", statusLabel: (status: string) => string) {
  return run.runSemantics?.runStatusLabel || supervisedRunBucketLabel(run.status, lang, statusLabel);
}

function displaySupervisedTechnicalText(
  value: string,
  decision: string,
  lang: "zh" | "en",
  decisionLabel: (decision: string) => string,
) {
  const text = String(value || "").trim();
  if (!text) {
    return "";
  }
  const decisionText = supervisedDecisionLabel(decision, lang, decisionLabel);
  const rejectedText = lang === "zh" ? "未入库" : "not stored";
  const riskGateText = lang === "zh" ? "风险 gate" : "risk gate";
  const judgmentNoteText = lang === "zh" ? "判定说明:" : "judgment note:";
  return text
    .replace(/\bdecision\s*=\s*REJECT\b/gi, lang === "zh" ? `治理结论=${decisionText}` : `governance=${decisionText}`)
    .replace(/\bagent_judgment\s+fail:?/gi, judgmentNoteText)
    .replace(/\bREJECT\b/g, decisionText)
    .replace(/\brejected\b/g, rejectedText)
    .replace(/失败\s*gate/g, riskGateText)
    .replace(/失败项/g, lang === "zh" ? "问题项" : "issue items")
    .replace(/监督结论/g, lang === "zh" ? "治理结论" : "governance result");
}

function displaySupervisedRunSummary(
  run: EvolutionRun,
  lang: "zh" | "en",
  decisionLabel: (decision: string) => string,
) {
  return displaySupervisedTechnicalText(run.summary, run.decision, lang, decisionLabel);
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
  const [selectedDatasetCatalogFilter, setSelectedDatasetCatalogFilter] = useState<DatasetCatalogFilter>("all");
  const [datasetLimitInput, setDatasetLimitInput] = useState("");
  const [bundleNameInput, setBundleNameInput] = useState("");
  const [keepWorktree, setKeepWorktree] = useState(false);
  const [supervisedMentalModelMode, setSupervisedMentalModelMode] = useState<SupervisedMentalModelMode>("follow");
  const [selectedSupervisedWorkflowStepId, setSelectedSupervisedWorkflowStepId] = useState<SupervisedWorkflowStepId | null>(null);
  const [liveActiveRun, setLiveActiveRun] = useState<EvolutionActiveRun | null>(null);
  const [supervisedStartCommand, setSupervisedStartCommand] = useState<EvolutionRunCommandAccepted | null>(null);
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
  const [runsQueueCollapsed, setRunsQueueCollapsed] = useState(false);
  const [libraryListCollapsed, setLibraryListCollapsed] = useState(false);
  const [liveLaunchCollapsed, setLiveLaunchCollapsed] = useState(false);
  const [liveRunCollapsed, setLiveRunCollapsed] = useState(false);
  const [expandedCaseTraceItems, setExpandedCaseTraceItems] = useState<Record<string, boolean>>({});
  const configQuery = useQuery({
    queryKey: queryKeys.configPublic(),
    queryFn: () => fetchJson<ConfigSummary>("/api/config/public"),
    refetchInterval: resolvePollingInterval(pageVisible, 8_000),
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
    refetchInterval: resolvePollingInterval(pageVisible, 4_000),
    refetchIntervalInBackground: false,
    enabled: supervisedTrackQueriesEnabled || selfTrackQueriesEnabled,
  });
  const workbenchCatalogQuery = useQuery({
    queryKey: queryKeys.evolutionWorkbench(),
    queryFn: () => fetchJson<EvolutionWorkbench>("/api/evolution/workbench"),
    refetchInterval: resolvePollingInterval(pageVisible, 8_000),
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
    refetchInterval: resolvePollingInterval(pageVisible, 8_000),
    refetchIntervalInBackground: false,
    enabled: selfTrackQueriesEnabled,
  });
  const selectedSelfObservationRunQuery = useQuery({
    queryKey: queryKeys.evolutionSelfObservationRun(selectedSelfObservationRunId || "__none__"),
    queryFn: () =>
      fetchJson<SelfObservationRun>(`/api/evolution/self/observation-runs/${encodeURIComponent(selectedSelfObservationRunId)}`),
    refetchInterval: resolvePollingInterval(pageVisible, 2_000),
    refetchIntervalInBackground: false,
    enabled: Boolean(selfTrackQueriesEnabled && selectedSelfObservationRunId),
  });
  const supervisedStartCommandId = supervisedStartCommand?.commandId ?? "";
  const supervisedStartCommandStatusQuery = useQuery({
    queryKey: queryKeys.evolutionRunCommand(supervisedStartCommandId || "__none__"),
    queryFn: () =>
      fetchJson<EvolutionRunCommandStatus>(`/api/evolution/runs/commands/${encodeURIComponent(supervisedStartCommandId)}`),
    refetchInterval: resolvePollingInterval(pageVisible, 1_500),
    refetchIntervalInBackground: false,
    enabled: Boolean(
      supervisedTrackQueriesEnabled
        && pageVisible
        && supervisedStartCommandId
        && isLocalSupervisedStartPlaceholder(liveActiveRun),
    ),
  });
  const selectedDatasetLimit = useMemo(
    () => (
      sourceKind === "dataset" && datasetLimitInput.trim()
        ? Number(datasetLimitInput.trim())
        : null
    ),
    [datasetLimitInput, sourceKind],
  );
  const startRunMutation = useMutation({
    onMutate: () => {
      const placeholderAgentBindings = activeRunSnapshot?.agentBindings
        ?? workspaceSnapshot?.currentAgentBindings
        ?? EMPTY_AGENT_BINDINGS;
      setSupervisedStartCommand(null);
      setActionFeedback(lang === "zh" ? "启动请求已提交，正在等待运行记录刷新。" : "Start request submitted; waiting for the run record to refresh.");
      setLiveActiveRun(buildSupervisedStartPlaceholder({
        sourceKind,
        datasetName: sourceKind === "dataset" ? datasetName : "",
        datasetLimit: selectedDatasetLimit,
        bundleName: sourceKind === "bundle" ? bundleNameInput : "",
        keepWorktree,
        mentalModelMode: supervisedMentalModelMode,
        agentBindings: placeholderAgentBindings,
        lang,
      }));
    },
    mutationFn: () =>
      fetchJson<EvolutionRunStartResponse>("/api/evolution/runs", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          sourceKind,
          datasetName: sourceKind === "dataset" ? datasetName : "",
          datasetLimit: selectedDatasetLimit,
          bundleName: sourceKind === "bundle" ? bundleNameInput : "",
          keepWorktree,
          mentalModelMode: supervisedMentalModelMode,
        }),
      }),
    onSuccess: async (payload) => {
      if (isEvolutionRunCommandAccepted(payload)) {
        setSupervisedStartCommand(payload);
        setActionFeedback(payload.summary || (lang === "zh" ? "启动命令已排队，等待运行记录刷新。" : "Start command queued; waiting for the run record to refresh."));
        await evolutionWorkspaceCache.refreshSupervisedActiveRun();
        return;
      }
      const snapshot = requireEvolutionRunSnapshot(payload, "supervised evolution start");
      setSupervisedStartCommand(null);
      setActionFeedback("");
      setLiveActiveRun(snapshot);
      await evolutionWorkspaceCache.afterSupervisedWorkspaceChanged();
    },
    onError: () => {
      setSupervisedStartCommand(null);
      setLiveActiveRun((current) => (isLocalSupervisedStartPlaceholder(current) ? null : current));
      void evolutionWorkspaceCache.refreshSupervisedActiveRun();
    },
  });
  const startWorktreeRunMutation = useMutation({
    onMutate: () => {
      setActionFeedback("");
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
          executionMode: "real",
          confirmRealLlmCost: true,
          mentalModelMode: supervisedMentalModelMode,
          uiRoute: `${location.pathname}${location.search}`,
          clientAction: "start_supervised_worktree_run",
        }),
      }),
    onSuccess: async (snapshot) => {
      setActionFeedback(snapshot.latestMessage || t("startClosedLoopQueued"));
      await evolutionWorkspaceCache.afterWorktreeRunChanged();
    },
  });
  const startSimulationWorktreeRunMutation = useMutation({
    onMutate: () => {
      setActionFeedback("");
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
          mentalModelMode: supervisedMentalModelMode,
          uiRoute: `${location.pathname}${location.search}`,
          clientAction: "start_supervised_worktree_simulation",
        }),
      }),
    onSuccess: async (snapshot) => {
      setActionFeedback(snapshot.latestMessage || t("startClosedLoopQueued"));
      await evolutionWorkspaceCache.afterWorktreeRunChanged();
    },
  });
  const invalidateSupervisedEvolution = async () => {
    await evolutionWorkspaceCache.afterSupervisedWorkspaceChanged();
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
  const retryRunMutation = useMutation({
    onMutate: () => {
      setActionFeedback("");
    },
    mutationFn: (runId: string) =>
      fetchJson<EvolutionActiveRun>(`/api/evolution/runs/${runId}/retry`, {
        method: "POST",
      }).then((snapshot) => requireEvolutionRunSnapshot(snapshot, "supervised retry")),
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
      if (!isEvolutionRunCommandAccepted(payload)) {
        setLiveActiveRun(null);
      }
      await invalidateSupervisedEvolution();
    },
  });
  const invalidateSelfEvolution = async () => {
    await evolutionWorkspaceCache.afterSelfEvolutionChanged();
  };
  const startSelfWorktreeRunMutation = useMutation({
    onMutate: () => {
      setSelfActionFeedback("");
    },
    mutationFn: () => {
      const fallbackBundleName =
        bundleNameInput.trim()
        || workbenchCatalogQuery.data?.defaultBundleName
        || workbenchCatalogQuery.data?.bundles?.[0]?.name
        || workspaceSnapshotQuery.data?.workbench?.defaultBundleName
        || workspaceSnapshotQuery.data?.workbench?.bundles?.[0]?.name
        || "";
      return fetchJson<SupervisedWorktreeRun>("/api/evolution/self/worktree-runs", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          goal: selfGoalInput.trim(),
          sourceKind: "bundle",
          bundleName: fallbackBundleName,
          mode: "manual",
          executionMode: "simulation",
          confirmRealLlmCost: false,
          uiRoute: `${location.pathname}${location.search}`,
        }),
      });
    },
    onSuccess: async (snapshot) => {
      setSelfActionFeedback(snapshot.latestMessage || t("startSelfWorktreeQueued"));
      await evolutionWorkspaceCache.afterWorktreeRunChanged();
    },
  });
  const startSelfObservationMutation = useMutation({
    onMutate: () => {
      setSelfActionFeedback("");
    },
    mutationFn: (payload: SelfObservationRunStartRequest) =>
      fetchJson<SelfObservationRun>("/api/evolution/self/observation-runs", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ ...payload, uiRoute: "/evolution?track=self" }),
      }),
    onSuccess: async (snapshot) => {
      setSelectedSelfObservationRunId(snapshot.runId);
      setSelfActionFeedback(snapshot.latestMessage || "");
      await evolutionWorkspaceCache.afterSelfEvolutionChanged();
    },
  });
  const selfObservationActionMutation = useMutation({
    onMutate: () => {
      setSelfActionFeedback("");
    },
    mutationFn: ({ runId, action }: { runId: string; action: string }) =>
      fetchJson<SelfObservationRun>(`/api/evolution/self/observation-runs/${encodeURIComponent(runId)}/actions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ action }),
      }),
    onSuccess: async (snapshot) => {
      setSelectedSelfObservationRunId(snapshot.runId);
      setSelfActionFeedback(snapshot.latestMessage || "");
      await evolutionWorkspaceCache.afterSelfEvolutionChanged();
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
      await evolutionWorkspaceCache.afterSupervisedWorkspaceChanged();
    },
  });
  const approvalWorktreeActionMutation = useMutation({
    onMutate: () => {
      setActionFeedback("");
    },
    mutationFn: (variables: { runId: string; action: string; reviewerNote?: string }) =>
      fetchJson<SupervisedWorktreeRun>(`/api/evolution/worktree-runs/${encodeURIComponent(variables.runId)}/actions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          action: variables.action,
          reviewerNote: variables.reviewerNote ?? "",
        }),
      }),
    onSuccess: async (snapshot) => {
      setActionFeedback(snapshot.latestMessage || statusLabel(snapshot.status));
      if (isSelfEvolutionWorktreeRun(snapshot)) {
        setSelfActionFeedback(snapshot.latestMessage || statusLabel(snapshot.status));
      }
      await evolutionWorkspaceCache.afterWorktreeRunChanged();
    },
  });
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
  const activeRunSnapshot = selectRunSnapshotWithRunId(workspaceSnapshot?.activeRun);
  const latestSupervisedRunSnapshot = selectRunSnapshotWithRunId(workspaceSnapshot?.latestRun);
  const currentSupervisedAgentBindings = workspaceSnapshot?.currentAgentBindings ?? EMPTY_AGENT_BINDINGS;
  const activeWorktreeRun = workspaceSnapshot?.worktreeActiveRun ?? null;
  const supervisedWorktreeLiveRun = activeWorktreeRun && !isSelfEvolutionWorktreeRun(activeWorktreeRun)
    ? activeWorktreeRun
    : null;
  const worktreeRuns = workspaceSnapshot?.worktreeRuns ?? EMPTY_WORKTREE_RUNS;
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
  const supervisedWorkflowRun = supervisedWorktreeLiveRun ?? monitoredRun;
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
  const monitoredRunStatus = String(monitoredRun?.status || "").toLowerCase();
  const monitoredCaseTranscript = monitoredRun?.currentCaseIo?.transcript ?? [];
  const monitoredCaseConversationMessages = monitoredRun?.currentCaseIo?.conversationMessages ?? [];
  const monitoredCaseHasConversationMessages = monitoredCaseConversationMessages.length > 0;
  const monitoredCaseConversationSessionId =
    monitoredRun?.currentCaseIo?.conversationSessionId
    || monitoredRun?.currentCaseIo?.conversationPath?.replace(/^session:/, "")
    || monitoredRun?.runId
    || "supervised-case";
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
  const monitoredCaseHasOutput = Boolean(
    monitoredRun?.currentCaseIo?.latestOutput || monitoredCaseHasConversationMessages || monitoredCaseTraceItems.length > 0,
  );
  const monitoredPreflightIssue = supervisedPreflightIssue(monitoredRun, lang);
  const monitoredCaseHasVisibleIo = Boolean(
    monitoredRun?.currentCasePrompt || monitoredRun?.currentCaseIo?.latestInput || monitoredCaseHasOutput || monitoredPreflightIssue,
  );
  const runPauseRequested = Boolean(monitoredRun?.pauseRequested) && monitoredRunStatus !== "paused";
  const runPaused = monitoredRunStatus === "paused";
  const runStopping = monitoredRunStatus === "stopping" || Boolean(monitoredRun?.stopRequested);
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
  }, [supervisedMembersRunIdentity]);
  const supervisedRunMembers = useMemo<SupervisedRunMember[]>(() => {
    const bindings = supervisedMembersBindings;
    const roleSessions = supervisedMembersRun?.roleConversationSessions ?? {};
    const currentRole = String(supervisedMembersRun?.currentRole || "").trim().toLowerCase();
    const currentAgentId = String(supervisedMembersRun?.currentAgentBinding?.agentId || "").trim();
    return SUPERVISED_RUN_MEMBER_ROLES.map((role) => {
      const binding = bindings[role] ?? {};
      const conversationSession = roleSessions[role];
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
    supervisedMembersRun?.currentAgentBinding?.agentId,
    supervisedMembersRun?.currentRole,
    supervisedMembersRun?.roleConversationSessions,
  ]);
  const supervisedRunMemberByRole = useMemo(
    () => new Map(supervisedRunMembers.map((member) => [member.role, member])),
    [supervisedRunMembers],
  );
  const backendWorkflowSteps = supervisedWorkflowRun?.workflowSteps ?? [];
  const backendWorkflowCurrent = backendWorkflowSteps.find((step) => step.current);
  const supervisedRuntimeWorkflowStepId = (
    SUPERVISED_WORKFLOW_STEPS.some((step) => step.id === backendWorkflowCurrent?.id)
      ? backendWorkflowCurrent?.id
      : activeSupervisedWorkflowStep(supervisedMembersRun)
  ) as SupervisedWorkflowStepId;
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
  const approvalEvidenceItems = [
    {
      label: lang === "zh" ? "最终运行结果" : "Final result",
      value: supervisedWorkflowRun?.status ? statusLabel(supervisedWorkflowRun.status) : "--",
    },
    {
      label: lang === "zh" ? "改进提案" : "Improvement proposal",
      value: String(supervisedWorkflowRun?.latestMessage || monitoredRun?.reason || "--"),
    },
    {
      label: lang === "zh" ? "样本评审" : "Sample review",
      value: supervisedWorkflowRun?.workflowSteps?.find((step) => step.id === "approval")?.summary || "--",
    },
  ];
  const selectedWorkflowConversationMessages: ConversationMessage[] =
    supervisedSelectedWorkflowStep.conversationMessages?.length
      ? supervisedSelectedWorkflowStep.conversationMessages
      : supervisedSelectedWorkflowStep.id === supervisedRuntimeWorkflowStepId
        ? monitoredCaseConversationMessages
        : [];
  const selectedWorkflowHasConversationMessages = selectedWorkflowConversationMessages.length > 0;
  const selectedWorkflowConversationSessionId =
    supervisedSelectedWorkflowStep.conversationSessionId
    || (supervisedSelectedWorkflowStep.id === supervisedRuntimeWorkflowStepId ? monitoredCaseConversationSessionId : "")
    || supervisedSelectedWorkflowStep.id;
  const selectedWorkflowAssistantName =
    supervisedSelectedWorkflowStep.member?.name
    || monitoredRun?.currentAgentBinding?.displayName
    || runRoleLabel(String(supervisedSelectedWorkflowStep.role || monitoredRun?.currentRole || ""));
  const selectedWorkflowTaskSummary =
    supervisedSelectedWorkflowStep.summary
    || supervisedSelectedWorkflowStep.livePreview
    || monitoredRun?.currentCasePrompt
    || monitoredRun?.currentTask
    || "";
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
    if (evolutionView !== "live") {
      goToSupervisedView("live");
    }
  }, [evolutionView]);
  const pauseSupervisedAction = monitoredRun?.actionStates?.pause;
  const resumeSupervisedAction = monitoredRun?.actionStates?.resume;
  const retrySupervisedAction = monitoredRun?.actionStates?.retry;
  const legacyTerminateSupervisedAction = monitoredRun?.actionStates?.terminate;
  const terminateWorktreeAction = supervisedWorktreeLiveRun?.actionStates?.terminate;
  const terminateSupervisedAction = terminateWorktreeAction ?? legacyTerminateSupervisedAction;
  const deleteSupervisedAction = monitoredRun?.actionStates?.delete;
  const canPauseSupervisedRun = Boolean(monitoredRun && pauseSupervisedAction?.enabled);
  const canResumeSupervisedRun = Boolean(monitoredRun && resumeSupervisedAction?.enabled);
  const canRetrySupervisedRun = Boolean(monitoredRun && retrySupervisedAction?.enabled);
  const canTerminateSupervisedRun = Boolean(
    supervisedWorktreeLiveRun
      ? terminateWorktreeAction?.enabled
      : monitoredRun && legacyTerminateSupervisedAction?.enabled,
  );
  const canDeleteSupervisedRun = Boolean(monitoredRun && deleteSupervisedAction?.enabled);
  const terminateSupervisedPending = supervisedWorktreeLiveRun
    ? approvalWorktreeActionMutation.isPending
    : terminateRunMutation.isPending;
  const handleTerminateSupervisedRun = () => {
    if (supervisedWorktreeLiveRun) {
      approvalWorktreeActionMutation.mutate({ runId: supervisedWorktreeLiveRun.runId, action: "terminate" });
      return;
    }
    if (monitoredRun) {
      terminateRunMutation.mutate(monitoredRun.runId);
    }
  };
  const supervisedControlError =
    pauseRunMutation.error?.message
    ?? resumeRunMutation.error?.message
    ?? retryRunMutation.error?.message
    ?? approvalWorktreeActionMutation.error?.message
    ?? terminateRunMutation.error?.message
    ?? deleteRunMutation.error?.message
    ?? startRunMutation.error?.message
    ?? startWorktreeRunMutation.error?.message
    ?? startSimulationWorktreeRunMutation.error?.message
    ?? "";
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
      await evolutionWorkspaceCache.afterProposalChanged(payload.sessionId);
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
      await evolutionWorkspaceCache.afterProposalChanged(payload.sessionId);
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
      await evolutionWorkspaceCache.afterProposalChanged(selectedProposalRunId ?? "__none__");
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
      await evolutionWorkspaceCache.afterProposalChanged(payload.sessionId);
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
      await evolutionWorkspaceCache.afterProposalChanged(selectedRunId ?? "__none__");
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
      setSupervisedStartCommand(null);
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
    const commandStatus = supervisedStartCommandStatusQuery.data;
    if (!supervisedStartCommand || !commandStatus?.completed) {
      return;
    }
    if (isCompletedEvolutionRunCommandSuccess(commandStatus)) {
      setSupervisedStartCommand(null);
      if (commandStatus.snapshot) {
        setActionFeedback("");
        setLiveActiveRun(commandStatus.snapshot);
      }
      void evolutionWorkspaceCache.afterSupervisedWorkspaceChanged();
      return;
    }
    if (!isCompletedEvolutionRunCommandFailure(commandStatus)) {
      return;
    }

    const isZh = lang === "zh";
    const timestamp = new Date().toISOString();
    const errorType = commandStatus.errorType || (isZh ? "启动失败" : "Start failed");
    const message = commandStatus.message || (isZh ? "监督运行启动失败。" : "Supervised run start failed.");
    setSupervisedStartCommand(null);
    setActionFeedback(message);
    setLiveActiveRun((current) => {
      if (!isLocalSupervisedStartPlaceholder(current)) {
        return current;
      }
      return {
        ...current,
        agentBindings: hasSupervisedAgentBindings(current.agentBindings)
          ? current.agentBindings
          : currentSupervisedAgentBindings,
        status: "failed",
        currentPhase: "failed",
        runtimeStatus: "failed",
        updatedAt: timestamp,
        finishedAt: timestamp,
        currentTask: message,
        reason: message,
        latestMessage: message,
        eventTail: [
          ...(current.eventTail ?? []),
          {
            timestamp,
            event: "start_failed",
            title: isZh ? "启动失败" : "Start failed",
            summary: message,
            status: "failed",
            commandId: commandStatus.commandId,
            errorType,
          },
        ].slice(-12),
        actionStates: {
          ...current.actionStates,
          pause: { enabled: false, reason: message },
          resume: { enabled: false, reason: message },
          retry: { enabled: false, reason: message },
          terminate: { enabled: false, reason: message },
          delete: { enabled: false, reason: isZh ? "本地启动占位没有写入运行记录。" : "This local placeholder was not persisted." },
        },
      };
    });
    void evolutionWorkspaceCache.refreshSupervisedActiveRun();
  }, [
    evolutionWorkspaceCache,
    currentSupervisedAgentBindings,
    lang,
    supervisedStartCommand,
    supervisedStartCommandStatusQuery.data,
  ]);

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
    if (runsQueueCollapsed) {
      return;
    }
    event.preventDefault();
    beginPaneResize(event.clientX, runsQueueWidth, EVOLUTION_RUNS_QUEUE_BOUNDS, setRunsQueueWidth);
  }

  function handleRunsResizeKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (runsQueueCollapsed) {
      return;
    }
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
    if (liveLaunchCollapsed) {
      return;
    }
    event.preventDefault();
    beginPaneResize(event.clientX, liveLaunchWidth, EVOLUTION_LIVE_LAUNCH_BOUNDS, setLiveLaunchWidth);
  }

  function handleLiveLaunchResizeKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (liveLaunchCollapsed) {
      return;
    }
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
    if (liveRunCollapsed) {
      return;
    }
    event.preventDefault();
    beginPaneResize(event.clientX, liveRunWidth, EVOLUTION_LIVE_RUN_BOUNDS, setLiveRunWidth, true);
  }

  function handleLiveRunResizeKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (liveRunCollapsed) {
      return;
    }
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
    if (libraryListCollapsed) {
      return;
    }
    event.preventDefault();
    beginPaneResize(event.clientX, libraryListWidth, EVOLUTION_LIBRARY_LIST_BOUNDS, setLibraryListWidth);
  }

  function handleLibraryResizeKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (libraryListCollapsed) {
      return;
    }
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
          <p title={item.reason || item.outcomeSemantics.runtimeExplanation}>
            {displaySupervisedTechnicalText(item.reason || item.outcomeSemantics.runtimeExplanation, item.decision, lang, decisionLabel)}
          </p>
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
          <p className={styles.noticeText} title={item.outcomeSemantics.runtimeExplanation}>
            {displaySupervisedTechnicalText(item.outcomeSemantics.runtimeExplanation, item.decision, lang, decisionLabel)}
          </p>
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
              activeWorkflowStepId={supervisedSelectedWorkflowStepId}
              onWorkflowStepSelect={handleSupervisedWorkflowStepSelect}
              overviewIntakeMode={overview?.intakeMode}
              configIntakeMode={configQuery.data?.intakeMode}
              tabSummaries={supervisedTabSummaries}
            />
          ) : null}
        </div>
      </section>

      {activeTrack === "self" ? (
        <div className={styles.selfModeStack}>
          <Suspense fallback={(
          <section className={`${styles.surface} ${styles.structuredEmptyState}`}>
            <LoaderCircle size={18} className={styles.spinIcon} aria-hidden="true" />
            <div>
              <h3>{lang === "zh" ? "正在加载自进化工作台" : "Loading self-evolution workspace"}</h3>
              <p>{lang === "zh" ? "监督进化工作台已先保持可用，自进化面板正在按需载入。" : "The supervised workspace stays available while the self-evolution panel loads on demand."}</p>
            </div>
          </section>
        )}>
          <LazySelfEvolutionTrack
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
          </Suspense>
        </div>
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
            <div className={`${styles.surface} ${styles.launchSurface} ${styles.supervisedRunConsole}`}>
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

              <div className={styles.sourceInventoryBar}>
                <span>{lang === "zh" ? "数据集" : "Datasets"} <strong>{workbenchCatalogLoading ? "--" : primaryDatasets.length}</strong></span>
                <span>{lang === "zh" ? "评测包" : "Bundles"} <strong>{workbenchCatalogLoading ? "--" : availableBundles.length}</strong></span>
                {hiddenDatasetCount > 0 ? (
                  <span>{lang === "zh" ? "隐藏" : "Hidden"} <strong>{hiddenDatasetCount}</strong></span>
                ) : null}
              </div>
              {datasetCatalog.length > 0 ? (
                <div className={styles.datasetCatalogPanel}>
                  <div className={styles.datasetCatalogHeader}>
                    <div>
                      <strong>{t("datasetCatalog")}</strong>
                      <span>
                        {datasetCatalog.length} · {lang === "zh" ? "可运行" : "runnable"} {datasetCatalogGroups.runnable.length}
                      </span>
                    </div>
                    <div className={styles.datasetCatalogFilterRow} role="tablist" aria-label={t("datasetCatalog")}>
                      {([
                        ["all", t("datasetCatalogAll"), datasetCatalogGroups.all.length],
                        ["runnable", t("datasetCatalogRunnable"), datasetCatalogGroups.runnable.length],
                        ["blocked", t("datasetCatalogBlocked"), datasetCatalogGroups.blocked.length],
                        ["roadmap", t("datasetCatalogRoadmap"), datasetCatalogGroups.roadmap.length],
                      ] as Array<[DatasetCatalogFilter, string, number]>).map(([filter, label, count]) => (
                        <button
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
                        </button>
                      ))}
                    </div>
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
                              <strong title={item.name}>{item.name}</strong>
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
                      <div
                        className={styles.formField}
                        title={lang === "zh"
                          ? "数据集会先物化，评测包可直接运行。"
                          : "A dataset is materialized first; a bundle runs directly."}
                      >
                        <label htmlFor="supervised-source">{lang === "zh" ? "评测来源" : "Evaluation source"}</label>
                        <select
                          id="supervised-source"
                          className={styles.selectInput}
                          value={selectedSourceValue}
                          onChange={(event) => {
                            const [nextKind, ...nameParts] = event.target.value.split(":");
                            const nextName = nameParts.join(":");
                            if (nextKind === "bundle") {
                              setSourceKind("bundle");
                              setBundleNameInput(nextName);
                              return;
                            }
                            setSourceKind("dataset");
                            setDatasetName(nextName);
                          }}
                        >
                          {primaryDatasets.length > 0 ? (
                            <optgroup label={lang === "zh" ? "可运行数据集：运行前自动物化为评测包" : "Runnable datasets: materialized before run"}>
                              {primaryDatasets.map((item) => (
                                <option key={`dataset:${item.name}`} value={`dataset:${item.name}`}>
                                  {item.name} [{datasetUsabilityLabel(item, lang)}]
                                </option>
                              ))}
                            </optgroup>
                          ) : null}
                          {availableBundles.length > 0 ? (
                            <optgroup label={lang === "zh" ? "已有评测包：直接运行" : "Existing bundles: run directly"}>
                              {availableBundles.map((item) => (
                                <option key={`bundle:${item.name}`} value={`bundle:${item.name}`}>
                                  {item.name} [{item.caseCount} cases]
                                </option>
                              ))}
                            </optgroup>
                          ) : null}
                        </select>
                      </div>
                      {sourceKind === "dataset" ? (
                        <div className={styles.formField} title={t("caseLimitHint")}>
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
                    <label className={styles.checkboxRow} title={t("keepWorktreeLabel")}>
                      <input
                        type="checkbox"
                        checked={keepWorktree}
                        onChange={(event) => setKeepWorktree(event.target.checked)}
                      />
                      <span className={styles.checkboxLabel}>{lang === "zh" ? "保留 worktree" : "Keep worktree"}</span>
                    </label>
                    <div className={styles.formField} title={t("supervisedMentalModeHint")}>
                      <label htmlFor="supervised-mental-mode">{t("supervisedMentalMode")}</label>
                      <select
                        id="supervised-mental-mode"
                        className={styles.selectInput}
                        value={supervisedMentalModelMode}
                        onChange={(event) => setSupervisedMentalModelMode(event.target.value as SupervisedMentalModelMode)}
                      >
                        <option value="follow">{t("supervisedMentalModeFollow")}</option>
                        <option value="enabled">{t("supervisedMentalModeEnabled")}</option>
                        <option value="disabled">{t("supervisedMentalModeDisabled")}</option>
                      </select>
                    </div>
                  </div>

                  <div className={styles.controlFooter}>
                    <div className={styles.controlActions}>
                      <button
                        type="button"
                        className={styles.inlineAction}
                        disabled={
                          runLocked
                          || worktreeRunLocked
                          || !workbenchControl
                          || startWorktreeRunMutation.isPending
                          || (sourceKind === "dataset" && !datasetName)
                          || (sourceKind === "bundle" && !selectedBundleExists)
                        }
                        onClick={() => startWorktreeRunMutation.mutate()}
                        title={t("launchSupervisedRunHint")}
                      >
                        {supervisedStartSubmitting || supervisedPrimaryRunning ? <LoaderCircle size={15} /> : <Play size={15} />}
                        {supervisedStartButtonLabel}
                      </button>
                    </div>
                    <div className={styles.closedLoopLaunchBlock} title={t("closedLoopLaunchPanelHint")}>
                      <div>
                        <div className={styles.closedLoopTitleRow}>
                          <strong>{t("closedLoopLaunchPanelTitle")}</strong>
                          <span className={styles.closedLoopModeBadge}>{lang === "zh" ? "模拟" : "Simulation"}</span>
                        </div>
                        <span>
                          {lang === "zh"
                            ? "当前只演练编排链路，不调用真实 LLM 自改。"
                            : "Runs the orchestration rehearsal without real LLM self-editing."}
                        </span>
                      </div>
                      <button
                        type="button"
                        className={styles.inlineAction}
                        disabled={
                          runLocked
                          || worktreeRunLocked
                          || !workbenchControl
                          || startSimulationWorktreeRunMutation.isPending
                          || (sourceKind === "dataset" && !datasetName)
                          || (sourceKind === "bundle" && !selectedBundleExists)
                        }
                        onClick={() => startSimulationWorktreeRunMutation.mutate()}
                        title={t("startClosedLoopHint")}
                      >
                        {startSimulationWorktreeRunMutation.isPending ? <LoaderCircle size={15} /> : <Sparkles size={15} />}
                        {t("startClosedLoopRun")}
                      </button>
                    </div>
                    {runLocked || worktreeRunLocked ? <p className={styles.noticeText}>{t("runningLockHint")}</p> : null}
                    {supervisedControlError ? (
                      <p className={styles.errorText}>{supervisedControlError}</p>
                    ) : null}
                  </div>
                </div>

                <aside
                  className={styles.supervisedWorkflowPanel}
                  title={
                    supervisedMembersSource === "current_config"
                      ? lang === "zh" ? "当前 Agent 配置；启动后锁定为本轮绑定。" : "Current Agent config; a run locks its own bindings after start."
                      : undefined
                  }
                >
                  <div className={styles.supervisedMembersHeader}>
                    <div>
                      <p className={styles.eyebrow}>
                        {supervisedMembersSource === "run" ? lang === "zh" ? "运行步骤" : "Run steps" : lang === "zh" ? "当前步骤" : "Current steps"}
                      </p>
                      <h3 className={styles.sectionTitle}>{supervisedWorkflowStepLabel(supervisedSelectedWorkflowStep, lang)}</h3>
                    </div>
                    <div className={styles.supervisedMembersHeaderActions}>
                      {supervisedWorkflowManualSelection ? (
                        <button
                          type="button"
                          className={styles.supervisedWorkflowFollowButton}
                          onClick={() => setSelectedSupervisedWorkflowStepId(null)}
                          title={lang === "zh" ? "回到当前执行阶段" : "Follow the current run stage"}
                        >
                          {lang === "zh" ? "跟随现场" : "Follow live"}
                        </button>
                      ) : null}
                      <span className={styles.secondaryPill}>{supervisedWorkflowCards.length}</span>
                    </div>
                  </div>
                  <div className={styles.supervisedWorkflowCardGrid} aria-label={lang === "zh" ? "监督进化步骤导航" : "Supervised evolution step navigation"}>
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
                        <article
                          key={step.id}
                          className={
                            selected
                              ? `${styles.supervisedWorkflowCard} ${styles.supervisedWorkflowCardActive}`
                              : current
                                ? `${styles.supervisedWorkflowCard} ${styles.supervisedWorkflowCardCurrent}`
                                : styles.supervisedWorkflowCard
                          }
                        >
                          <button
                            type="button"
                            className={styles.supervisedWorkflowCardButton}
                            aria-pressed={selected}
                            onClick={() => setSelectedSupervisedWorkflowStepId(step.id)}
                            title={lang === "zh" ? `查看${supervisedWorkflowStepLabel(step, lang)}` : `View ${supervisedWorkflowStepLabel(step, lang)}`}
                          >
                            <span className={styles.supervisedWorkflowCardTopline}>
                              <span>{supervisedWorkflowStepLabel(step, lang)}</span>
                              {current ? <em>{lang === "zh" ? "当前" : "Live"}</em> : null}
                            </span>
                            <strong>{stepMeta}</strong>
                            <span className={styles.supervisedWorkflowLivePreview}>
                              {step.livePreview || step.summary || (lang === "zh" ? "等待实时输出" : "Waiting for live output")}
                            </span>
                          </button>
                          <div className={styles.supervisedWorkflowCardFooter}>
                            <span>{stepMetric}</span>
                            {stepRoute ? (
                              <Link
                                className={styles.supervisedWorkflowSessionLink}
                                to={stepRoute}
                                title={
                                  member?.chatRoute
                                    ? lang === "zh" ? `打开监督成员 ${member.name} 的会话` : `Open supervised member session for ${member.name}`
                                    : lang === "zh" ? "打开监督会话" : "Open supervised session"
                                }
                                aria-label={
                                  member?.chatRoute
                                    ? lang === "zh" ? `打开监督成员 ${member.name} 的会话` : `Open supervised member session for ${member.name}`
                                    : lang === "zh" ? "打开监督会话" : "Open supervised session"
                                }
                              >
                                <span>{lang === "zh" ? "会话" : "Session"}</span>
                                <ArrowUpRight size={13} aria-hidden="true" />
                              </Link>
                            ) : member?.configRoute ? (
                              <Link
                                className={styles.supervisedWorkflowSessionLink}
                                to={member.configRoute}
                                title={lang === "zh" ? `配置 ${member.name}` : `Configure ${member.name}`}
                              >
                                <span>{lang === "zh" ? "配置" : "Config"}</span>
                                <ArrowUpRight size={13} aria-hidden="true" />
                              </Link>
                            ) : null}
                          </div>
                        </article>
                      );
                    })}
                  </div>
                </aside>
              </div>
            </div>

          </section>

          <PaneCollapseHandle
            side="left"
            collapsed={liveLaunchCollapsed}
            separatorLabel={resizeLiveLaunchLabel}
            collapseLabel={lang === "zh" ? "收起启动卡片" : "Collapse launch card"}
            expandLabel={lang === "zh" ? "展开启动卡片" : "Expand launch card"}
            className={`${styles.resizeHandle} ${styles.liveResizeHandle} ${styles.liveResizeHandleLaunch}`}
            onToggle={() => setLiveLaunchCollapsed((current) => !current)}
            onPointerDown={handleLiveLaunchResizeStart}
            onKeyDown={handleLiveLaunchResizeKeyDown}
          />

          <section
            className={
              liveRunCollapsed
                ? `${styles.surface} ${styles.liveSurface} ${styles.dashboardRun} ${styles.paneCollapsed}`
                : `${styles.surface} ${styles.liveSurface} ${styles.dashboardRun}`
            }
            aria-hidden={liveRunCollapsed}
          >
              <div className={styles.surfaceHeaderCompact}>
                <div>
                  <p className={styles.eyebrow}>{t("activeSupervisedRun")}</p>
                  <h2 className={`${styles.sectionTitle} ${styles.truncateText}`} title={monitoredRunIdentity || undefined}>
                    {monitoredRunIdentity || t("activeSupervisedRun")}
                  </h2>
                </div>
                {monitoredRun ? (
                  <div className={styles.liveStatusRow}>
                    <span className={styles.statusPill}>{monitoredStatusLabel}</span>
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
                        disabled={!canRetrySupervisedRun || retryRunMutation.isPending}
                        title={disabledReason(retrySupervisedAction) || t("retrySupervisedRun")}
                        onClick={() => monitoredRun && retryRunMutation.mutate(monitoredRun.runId)}
                        aria-label={t("retrySupervisedRun")}
                      >
                        {retryRunMutation.isPending ? <LoaderCircle size={15} /> : <RefreshCw size={15} />}
                      </button>
                      <button
                        type="button"
                        className={styles.compactIconAction}
                        disabled={!canTerminateSupervisedRun || terminateSupervisedPending}
                        title={disabledReason(terminateSupervisedAction) || t("terminateSupervisedRun")}
                        onClick={handleTerminateSupervisedRun}
                        aria-label={t("terminateSupervisedRun")}
                      >
                        {terminateSupervisedPending ? <LoaderCircle size={15} /> : <Square size={15} />}
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
                    <div className={`${styles.liveSummaryRow} ${monitoredControlSummary ? styles[`runSummaryTone_${monitoredControlSummary.tone}`] : ""}`}>
                      <span className={styles.statusIcon}>{statusIcon(monitoredRun.status, monitoredRun.decision)}</span>
                      <div className={styles.runControlSummaryBody}>
                        <p className={styles.heroSummary}>
                          {monitoredControlSummary?.headline || monitoredRun.latestMessage}
                        </p>
                        {monitoredControlSummary?.reason ? (
                          <p className={styles.runControlReason}>{monitoredControlSummary.reason}</p>
                        ) : null}
                      </div>
                    </div>
                    {monitoredControlSummary?.nextAction ? (
                      <div className={styles.runNextActionStrip}>
                        <strong>{t("nextRecommendedAction")}</strong>
                        <span>{monitoredControlSummary.nextAction}</span>
                      </div>
                    ) : null}
                  </div>

                  <div className={styles.monitorMetricsDense}>
                    <article className={styles.metricTile}>
                      <span>{t("activeRunSession")}</span>
                      <strong title={monitoredRunIdentity}>{monitoredRunIdentity}</strong>
                    </article>
                    <article className={styles.metricTile}>
                      <span>{t("activeRunPhase")}</span>
                      <strong>{monitoredControlSummary?.stageLabel || statusLabel(monitoredRun.currentPhase || monitoredRun.status)}</strong>
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
                      <span>{t("activeRunResult")}</span>
                      <strong>{monitoredControlSummary?.resultLabel || monitoredTaskLabel}</strong>
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
                  {supervisedClosedLoopRecord ? (
                    <div className={styles.closedLoopLedger}>
                      <div className={styles.closedLoopLedgerHeader}>
                        <div>
                          <span className={styles.eyebrow}>{lang === "zh" ? "闭环记录库" : "Closed-loop ledger"}</span>
                          <strong className={styles.truncateText} title={supervisedClosedLoopRecord.runId}>
                            {supervisedClosedLoopRecord.runId}
                          </strong>
                        </div>
                        <span className={supervisedClosedLoopRecord.status === "failed" ? styles.statusPill : styles.secondaryPill}>
                          {supervisedClosedLoopDecisionLabel || "--"}
                        </span>
                      </div>
                      <p>
                        {displaySupervisedTechnicalText(
                          supervisedClosedLoopRecord.policySummary
                          || supervisedClosedLoopRecord.reason
                          || supervisedClosedLoopRecord.nextAction.description,
                          supervisedClosedLoopRecord.decision,
                          lang,
                          decisionLabel,
                        ) || "--"}
                      </p>
                      <div className={styles.closedLoopLedgerEvidenceGrid}>
                        <article>
                          <span>{lang === "zh" ? "审查入口" : "Review entry"}</span>
                          <strong>{supervisedClosedLoopRecord.nextAction.label || "--"}</strong>
                        </article>
                        <article>
                          <span>{lang === "zh" ? "Agent 会话" : "Agent sessions"}</span>
                          <strong>{supervisedClosedLoopRecord.counts.roleSessionCount}</strong>
                        </article>
                        <article>
                          <span>{lang === "zh" ? "提案证据" : "Proposal evidence"}</span>
                          <strong>{supervisedClosedLoopProposalCount}</strong>
                        </article>
                        <article>
                          <span>{lang === "zh" ? "lineage" : "lineage"}</span>
                          <strong>{supervisedClosedLoopLineageLabel}</strong>
                        </article>
                      </div>
                      <div className={styles.actionRow}>
                        <button
                          type="button"
                          className={styles.inlineAction}
                          onClick={() => {
                            setLibraryView("pending");
                            goToSupervisedView("library");
                          }}
                          title={supervisedClosedLoopRecord.nextAction.description}
                        >
                          <LibraryBig size={15} />
                          {lang === "zh" ? "审查入口" : "Review"}
                        </button>
                      </div>
                    </div>
                  ) : null}
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

          <PaneCollapseHandle
            side="right"
            collapsed={liveRunCollapsed}
            separatorLabel={resizeLiveRunLabel}
            collapseLabel={lang === "zh" ? "收起当前任务卡片" : "Collapse active run card"}
            expandLabel={lang === "zh" ? "展开当前任务卡片" : "Expand active run card"}
            className={`${styles.resizeHandle} ${styles.liveResizeHandle} ${styles.liveResizeHandleRun}`}
            onToggle={() => setLiveRunCollapsed((current) => !current)}
            onPointerDown={handleLiveRunResizeStart}
            onKeyDown={handleLiveRunResizeKeyDown}
          />

          <section className={`${styles.surface} ${styles.ioSurface} ${styles.dashboardIo}`}>
              <div className={styles.surfaceHeaderCompact}>
                <div>
                  <p className={styles.eyebrow}>{supervisedWorkflowStepLabel(supervisedSelectedWorkflowStep, lang)}</p>
                  <h2 className={`${styles.sectionTitle} ${styles.truncateText}`} title={selectedWorkflowTaskSummary || undefined}>
                    {supervisedSelectedWorkflowStep.label || t("currentCaseOutput")}
                  </h2>
                </div>
                <div className={styles.liveStatusRow}>
                  {supervisedSelectedWorkflowStep.role ? (
                    <span className={styles.secondaryPill}>{runRoleLabel(supervisedSelectedWorkflowStep.role)}</span>
                  ) : null}
                  <span className={styles.secondaryPill}>{statusLabel(supervisedSelectedWorkflowStep.status)}</span>
                  {monitoredRun?.currentCaseScenario && supervisedSelectedWorkflowStep.id === supervisedRuntimeWorkflowStepId ? (
                    <span className={styles.secondaryPill}>{monitoredRun.currentCaseScenario}</span>
                  ) : null}
                  {monitoredRun?.currentCaseMode && supervisedSelectedWorkflowStep.id === supervisedRuntimeWorkflowStepId ? (
                    <span className={styles.secondaryPill}>{monitoredRun.currentCaseMode}</span>
                  ) : null}
                </div>
              </div>

              <div className={styles.liveIoPane}>
                {supervisedSelectedWorkflowStep.id === "approval" ? (
                  <div className={styles.approvalEvidencePanel}>
                    {approvalEvidenceItems.map((item) => (
                      <article key={item.label} className={styles.approvalEvidenceItem}>
                        <span>{item.label}</span>
                        <strong>{item.value}</strong>
                      </article>
                    ))}
                    <div className={styles.approvalEvidenceActions}>
                      {reviewCandidateWorktree?.actionStates?.approveReview?.enabled ? (
                        <button
                          type="button"
                          className={styles.inlineAction}
                          disabled={approvalWorktreeActionMutation.isPending}
                          onClick={() => approvalWorktreeActionMutation.mutate({ runId: reviewCandidateWorktree.runId, action: "approve_review" })}
                        >
                          {approvalWorktreeActionMutation.isPending ? <LoaderCircle size={15} /> : <CheckCircle2 size={15} />}
                          {lang === "zh" ? "审批通过" : "Approve"}
                        </button>
                      ) : null}
                      {reviewCandidateWorktree?.actionStates?.merge?.enabled ? (
                        <button
                          type="button"
                          className={styles.inlineAction}
                          disabled={approvalWorktreeActionMutation.isPending}
                          onClick={() => approvalWorktreeActionMutation.mutate({ runId: reviewCandidateWorktree.runId, action: "merge" })}
                        >
                          {approvalWorktreeActionMutation.isPending ? <LoaderCircle size={15} /> : <Save size={15} />}
                          {lang === "zh" ? "人工入库" : "Store"}
                        </button>
                      ) : null}
                    </div>
                    {approvalWorktreeActionMutation.error?.message ? (
                      <p className={styles.errorTextCompact}>{approvalWorktreeActionMutation.error.message}</p>
                    ) : null}
                  </div>
                ) : selectedWorkflowHasConversationMessages ? (
                  <div className={styles.ioStack}>
                    <div className={styles.caseConversationShell}>
                      <LazyConversationView
                        sessionId={selectedWorkflowConversationSessionId}
                        className={styles.caseConversationTranscript}
                        density="compact"
                        eyebrowLabel={supervisedWorkflowStepLabel(supervisedSelectedWorkflowStep, lang)}
                        title={supervisedSelectedWorkflowStep.label || t("currentCaseOutput")}
                        phase={supervisedSelectedWorkflowStep.status}
                        messages={selectedWorkflowConversationMessages}
                        assistantDisplayName={selectedWorkflowAssistantName}
                        userDisplayName={lang === "zh" ? "监督任务" : "Supervised task"}
                        taskSummary={selectedWorkflowTaskSummary}
                        defaultFileContext={monitoredRun?.currentCaseScenario || "supervised"}
                        summaryItems={[]}
                        showHeader={false}
                        showSessionOverview={false}
                        showComposer={false}
                        autoScrollToLatest={true}
                        composerValue=""
                        composerPlaceholder={t("caseIoWaiting")}
                        composerDisabled={true}
                        composerPending={false}
                        onComposerChange={() => undefined}
                        onSubmit={() => undefined}
                        fallback={<div className={styles.caseConversationFallback}>{t("loadingSession")}</div>}
                      />
                    </div>
                  </div>
                ) : monitoredCaseHasVisibleIo && supervisedSelectedWorkflowStep.id === supervisedRuntimeWorkflowStepId ? (
                  <div className={styles.ioStack}>
                    {monitoredCaseHasConversationMessages ? (
                      <div className={styles.caseConversationShell}>
                        <LazyConversationView
                          sessionId={monitoredCaseConversationSessionId}
                          className={styles.caseConversationTranscript}
                          density="compact"
                          eyebrowLabel={t("currentCaseTranscript")}
                          title={monitoredRun?.currentCaseId || t("currentCaseOutput")}
                          phase={monitoredRun?.currentPhase || monitoredRun?.status || ""}
                          messages={monitoredCaseConversationMessages}
                          assistantDisplayName={
                            monitoredRun?.currentAgentBinding?.displayName
                            || runRoleLabel(monitoredRun?.currentRole || "")
                          }
                          userDisplayName={lang === "zh" ? "监督任务" : "Supervised task"}
                          taskSummary={monitoredRun?.currentCasePrompt || monitoredRun?.currentTask || ""}
                          defaultFileContext={monitoredRun?.currentCaseScenario || "supervised"}
                          summaryItems={[]}
                          showHeader={false}
                          showSessionOverview={false}
                          showComposer={false}
                          autoScrollToLatest={true}
                          composerValue=""
                          composerPlaceholder={t("caseIoWaiting")}
                          composerDisabled={true}
                          composerPending={false}
                          onComposerChange={() => undefined}
                          onSubmit={() => undefined}
                          fallback={<div className={styles.caseConversationFallback}>{t("loadingSession")}</div>}
                        />
                      </div>
                    ) : (
                      <>
                        {monitoredRun?.currentCasePrompt ? (
                          <details className={`${styles.rawBlock} ${styles.collapsibleEvidence}`}>
                            <summary>{t("currentCasePrompt")}</summary>
                            <pre className={styles.ioContent}>{monitoredRun.currentCasePrompt}</pre>
                          </details>
                        ) : null}

                        <div className={`${styles.detailSection} ${styles.detailSectionCompact} ${styles.transcriptSection}`}>
                          {monitoredCaseTraceItems.length > 0 ? (
                            <div ref={caseTraceTimelineRef} className={styles.caseTraceTimeline}>
                              <div className={styles.caseTraceStack}>
                                {monitoredCaseTraceItems.map((entry) => {
                                  const expanded = caseTraceItemExpanded(entry);
                                  return (
                                    <article
                                      key={entry.key}
                                      className={`${styles.caseTraceTurn} ${styles[`caseTraceTurn_${entry.tone}`]}`}
                                    >
                                      <button
                                        type="button"
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
                                      </button>
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
                          ) : monitoredPreflightIssue ? (
                            <div className={styles.casePreflightIssue}>
                              <strong>{monitoredPreflightIssue.title}</strong>
                              <span>{monitoredPreflightIssue.detail}</span>
                              {monitoredPreflightIssue.reason ? <small>{monitoredPreflightIssue.reason}</small> : null}
                            </div>
                          ) : (
                            <p className={styles.noticeText}>{t("caseIoWaiting")}</p>
                          )}
                        </div>

                        {monitoredRun?.currentCaseIo?.latestOutput ? (
                          <details className={`${styles.rawBlock} ${styles.collapsibleEvidence} ${styles.caseRawEvidence}`}>
                            <summary>{currentCaseOutputLabel(monitoredRun)}</summary>
                            <pre className={styles.ioContent}>{monitoredRun.currentCaseIo.latestOutput}</pre>
                          </details>
                        ) : null}
                      </>
                    )}
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
                    {filter === "all" ? t("allRuns") : supervisedRunBucketLabel(filter, lang, statusLabel)}
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
          </section>

          <div className={styles.runsWorkspace} style={runsWorkspaceStyle}>
            <section
              className={
                runsQueueCollapsed
                  ? `${styles.surface} ${styles.runQueuePanel} ${styles.paneCollapsed}`
                  : `${styles.surface} ${styles.runQueuePanel}`
              }
              aria-hidden={runsQueueCollapsed}
            >
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
                  {filteredRuns.map((run) => {
                    const runDisplay = buildSupervisedRunRecordDisplay(run, lang, {
                      statusLabel,
                      decisionLabel: displayDecisionLabel,
                    });
                    return (
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
                        <div className={`${styles.listRowTop} ${styles.runRecordTitleRow}`}>
                          <div className={styles.runRecordIdentity}>
                            <strong>{runDisplay.title}</strong>
                            <span>{runDisplay.idLabel}</span>
                          </div>
                          <span className={styles.secondaryPill}>{displayDecisionLabel(run.decision)}</span>
                        </div>
                        <div className={styles.metaRow}>
                          <span>{displaySupervisedRunStatus(run, lang, statusLabel)}</span>
                          <span>{supervisedProposalStatusLabel(run.outcomeSemantics.proposalStatus, run.outcomeSemantics.proposalStatusLabel, lang)}</span>
                        </div>
                        <div className={styles.scoreRow}>
                          <span>{runDisplay.subtitle}</span>
                          <strong>{run.candidateScore}</strong>
                        </div>
                        <p>{displaySupervisedRunSummary(run, lang, decisionLabel)}</p>
                        <div className={styles.cardFooter}>
                          <span>{riskLabel(run.riskLevel)}</span>
                          <span title={run.nextAction || ""}>
                            {displaySupervisedTechnicalText(run.nextAction, run.decision, lang, decisionLabel) || "--"}
                          </span>
                        </div>
                      </button>
                      {!run.canDelete && run.deleteBlockReason ? (
                        <p className={styles.noticeText}>{run.deleteBlockReason}</p>
                      ) : null}
                    </article>
                    );
                  })}
                </div>
              )}
            </section>

            <PaneCollapseHandle
              side="left"
              collapsed={runsQueueCollapsed}
              separatorLabel={resizeRunsQueueLabel}
              collapseLabel={lang === "zh" ? "收起运行列表" : "Collapse run list"}
              expandLabel={lang === "zh" ? "展开运行列表" : "Expand run list"}
              className={styles.resizeHandle}
              onToggle={() => setRunsQueueCollapsed((current) => !current)}
              onPointerDown={handleRunsResizeStart}
              onKeyDown={handleRunsResizeKeyDown}
            />

            <section className={`${styles.surface} ${styles.runDetailPanel}`}>
              {selectedRun ? (
                <>
                  <div className={styles.detailHeader}>
                    <div>
                      <p className={styles.eyebrow}>{t("runDetail")}</p>
                      <h2 className={styles.detailTitle}>
                        {buildSupervisedRunRecordDisplay(selectedRun, lang, { statusLabel, decisionLabel: displayDecisionLabel }).title}
                      </h2>
                      <p className={styles.detailSubtleId}>{selectedRun.id}</p>
                    </div>
                    <div className={styles.detailHeaderActions}>
                      <span className={styles.secondaryPill}>{displayDecisionLabel(selectedRun.decision)}</span>
                      <span className={styles.secondaryPill}>
                        {supervisedProposalStatusLabel(
                          selectedRun.outcomeSemantics.proposalStatus,
                          selectedRun.outcomeSemantics.proposalStatusLabel,
                          lang,
                        )}
                      </span>
                    </div>
                  </div>

                  <div className={styles.runDetailOverview}>
                    <div className={styles.runScorePanel}>
                      <span>{t("candidateScore")}</span>
                      <p className={styles.detailLead}>{selectedRun.candidateScore}</p>
                      <p>{displaySupervisedRunSummary(selectedRun, lang, decisionLabel)}</p>
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
                          <strong>{displaySupervisedRunStatus(selectedRun, lang, statusLabel)}</strong>
                        </article>
                        <article className={styles.compactFact}>
                          <span>{t("decision")}</span>
                          <strong>{displayDecisionLabel(selectedRun.outcomeSemantics.decision || selectedRun.decision)}</strong>
                        </article>
                        <article className={styles.compactFact}>
                          <span>{t("proposalLayer")}</span>
                          <strong>
                            {supervisedProposalStatusLabel(
                              selectedRun.outcomeSemantics.proposalStatus,
                              selectedRun.outcomeSemantics.proposalStatusLabel,
                              lang,
                            )}
                          </strong>
                        </article>
                        <article className={styles.compactFact}>
                          <span>{t("runtimeLayer")}</span>
                          <strong>{selectedRun.outcomeSemantics.runtimeEffectLabel}</strong>
                        </article>
                        <article className={styles.compactFact}>
                          <span>{t("nextRecommendedAction")}</span>
                          <strong title={selectedRun.runSemantics.nextAction || ""}>
                            {displaySupervisedTechnicalText(selectedRun.runSemantics.nextAction, selectedRun.decision, lang, decisionLabel) || "--"}
                          </strong>
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
                      <p title={selectedRun.outcomeSemantics.runtimeExplanation}>
                        {displaySupervisedTechnicalText(selectedRun.outcomeSemantics.runtimeExplanation, selectedRun.decision, lang, decisionLabel)}
                      </p>
                      {selectedRun.riskReasons.length > 0 ? (
                        <p title={selectedRun.riskReasons.join(" / ")}>
                          {displaySupervisedTechnicalText(selectedRun.riskReasons.join(" / "), selectedRun.decision, lang, decisionLabel)}
                        </p>
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
            <section
              className={
                libraryListCollapsed
                  ? `${styles.surface} ${styles.listPanel} ${styles.paneCollapsed}`
                  : `${styles.surface} ${styles.listPanel}`
              }
              aria-hidden={libraryListCollapsed}
            >
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
                            <span>{displayDecisionLabel(item.decision)}</span>
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
                            <span>{displayDecisionLabel(item.decision)}</span>
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

            <PaneCollapseHandle
              side="left"
              collapsed={libraryListCollapsed}
              separatorLabel={resizeLibraryListLabel}
              collapseLabel={lang === "zh" ? "收起提案列表" : "Collapse proposal list"}
              expandLabel={lang === "zh" ? "展开提案列表" : "Expand proposal list"}
              className={styles.resizeHandle}
              onToggle={() => setLibraryListCollapsed((current) => !current)}
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
                      <p className={styles.noticeText} title={proposalDetailQuery.data.outcomeSemantics.runtimeExplanation}>
                        {displaySupervisedTechnicalText(
                          proposalDetailQuery.data.outcomeSemantics.runtimeExplanation,
                          proposalDetailQuery.data.decision,
                          lang,
                          decisionLabel,
                        )}
                      </p>
                      <p title={proposalDetailQuery.data.supervised.decisionReason}>
                        {displaySupervisedTechnicalText(
                          proposalDetailQuery.data.supervised.decisionReason,
                          proposalDetailQuery.data.decision,
                          lang,
                          decisionLabel,
                        )}
                      </p>
                      {proposalDetailQuery.data.supervised.riskReasons.length > 0 ? (
                        <p title={proposalDetailQuery.data.supervised.riskReasons.join(" / ")}>
                          {displaySupervisedTechnicalText(
                            proposalDetailQuery.data.supervised.riskReasons.join(" / "),
                            proposalDetailQuery.data.decision,
                            lang,
                            decisionLabel,
                          )}
                        </p>
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
