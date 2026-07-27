/**
 * Evolution route pure presentation helpers (structure M4).
 * Pure: no React hooks / Query / DOM.
 */
import type {
  EvolutionActiveRun,
  EvolutionActiveRunAgentBinding,
  EvolutionClosedLoopRecord,
  EvolutionLibraryEntry,
  EvolutionProposalDetail,
  EvolutionRoleConversationSession,
  EvolutionRun,
  EvolutionWorkbench,
  EvolutionWorkflowStep,
} from "../../api/types";
import { modelDisplayLabel } from "../agentDisplay";
import { supervisedDecisionLabel } from "../supervisedRunRecordLabel";

export type SupervisedMemberRole = "baseline" | "candidate" | "reviewer" | "auditor" | "judge";
export type SupervisedWorkflowStepId = "baseline_eval" | "improve" | "rerun_score" | "approval";
export type SupervisedRunMember = {
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
export type SupervisedClosedLoopRecord = EvolutionClosedLoopRecord;
export type SupervisedWorkflowDefinition = {
  id: SupervisedWorkflowStepId;
  zh: string;
  en: string;
  role: SupervisedMemberRole | null;
};
export type SupervisedWorkflowCard = EvolutionWorkflowStep & {
  id: SupervisedWorkflowStepId;
  member?: SupervisedRunMember;
};

export type SupervisedPreflightIssue = {
  title: string;
  detail: string;
  reason: string;
};

export const SUPERVISED_RUN_MEMBER_ROLES: SupervisedMemberRole[] = ["baseline", "candidate", "judge"];
export const SUPERVISED_WORKFLOW_STEPS: SupervisedWorkflowDefinition[] = [
  { id: "baseline_eval", zh: "基线评测", en: "Baseline", role: "baseline" },
  { id: "improve", zh: "提出建议与改良", en: "Improve", role: "candidate" },
  { id: "rerun_score", zh: "复跑与评分", en: "Rerun + Score", role: "candidate" },
  { id: "approval", zh: "用户审批", en: "Approval", role: null },
];
export const LOCAL_SUPERVISED_RUN_PREFIX = "local-supervised-start-";
export type ProposalEditDraft = {
  improvementType: string;
  expectedEffect: string;
  summary: string;
  candidatePrompt: string;
  baselinePrompt: string;
  editNote: string;
};

export type SupervisedMentalModelMode = "follow" | "enabled" | "disabled";

export function clampScore(value: number) {
  return Math.max(0, Math.min(100, Math.round(value)));
}

export function isLocalSupervisedStartPlaceholder(run: EvolutionActiveRun | null | undefined): run is EvolutionActiveRun {
  return String(run?.runId || "").startsWith(LOCAL_SUPERVISED_RUN_PREFIX);
}

export function buildSupervisedStartPlaceholder(input: {
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

export function hasSupervisedAgentBindings(bindings: Record<string, EvolutionActiveRunAgentBinding> | null | undefined) {
  return Boolean(bindings && Object.keys(bindings).length > 0);
}

export function supervisedWorkflowStepLabel(step: SupervisedWorkflowDefinition | SupervisedWorkflowCard, lang: "zh" | "en") {
  if ("label" in step && step.label) {
    return step.label;
  }
  const definition = SUPERVISED_WORKFLOW_STEPS.find((item) => item.id === step.id);
  return lang === "zh" ? definition?.zh ?? step.id : definition?.en ?? step.id;
}

export function activeSupervisedWorkflowStep(run: EvolutionActiveRun | null | undefined): SupervisedWorkflowStepId {
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

export function supervisedMemberModelId(binding: EvolutionActiveRunAgentBinding | undefined) {
  return String(
    binding?.dialogueModelId
    || binding?.llmBindings?.dialogue?.modelId
    || binding?.llmBindings?.primary?.modelId
    || "",
  ).trim();
}

export function supervisedMemberModelLabel(
  binding: EvolutionActiveRunAgentBinding | undefined,
  resolveModelLabel?: (modelId: string) => string | undefined,
) {
  const bindingLabel = String(binding?.dialogueModelLabel || binding?.dialogueModelName || "").trim();
  return bindingLabel || modelDisplayLabel(supervisedMemberModelId(binding), resolveModelLabel) || "--";
}

export function supervisedMemberAgentManagementRoute(agentId: string, returnTo: string) {
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

export function supervisedMemberChatRoute(sessionId: string, returnTo: string, returnLabel: string) {
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

export function supervisedPreflightIssue(run: EvolutionActiveRun | null | undefined, lang: "zh" | "en"): SupervisedPreflightIssue | null {
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

export function toLimitInput(value: number | null | undefined) {
  if (typeof value !== "number" || Number.isNaN(value) || value <= 0) {
    return "";
  }
  return String(value);
}

export function compactTimestamp(value: string) {
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

export function formatTurnRange(startTurn: number, endTurn: number) {
  if (startTurn > 0 && endTurn > 0) {
    return `T${startTurn}-${endTurn}`;
  }
  if (startTurn > 0) {
    return `T${startTurn}`;
  }
  return "--";
}

export function datasetUsabilityLabel(
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

export function datasetCatalogStatusLabel(
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

export function datasetBenchmarkDetail(
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

export function proposalEditDraftFromDetail(detail: EvolutionProposalDetail): ProposalEditDraft {
  return {
    improvementType: detail.proposal.improvementType || "",
    expectedEffect: detail.proposal.expectedEffect || "",
    summary: detail.proposal.summary || detail.review.changeSummary || "",
    candidatePrompt: detail.proposal.candidatePrompt || "",
    baselinePrompt: detail.proposal.baselinePrompt || "",
    editNote: detail.proposal.editNote || "",
  };
}

export function isSelfEvolutionCandidateItem(item: EvolutionLibraryEntry | null | undefined) {
  return item?.ingestMode === "self_evolution_candidate";
}

export function proposalDisplaySourceRun(item: EvolutionLibraryEntry | null | undefined) {
  if (!item) {
    return "";
  }
  if (isSelfEvolutionCandidateItem(item)) {
    return item.sourceSelfRunId || item.sourceRun;
  }
  return item.sourceRun;
}

export function canOpenProposalSourceRun(item: EvolutionLibraryEntry | null | undefined) {
  return Boolean(item?.sourceRun) && !isSelfEvolutionCandidateItem(item);
}

export function supervisedRunBucketLabel(status: string, lang: "zh" | "en", statusLabel: (status: string) => string) {
  const normalized = String(status || "").trim().toLowerCase();
  if (normalized === "failed") {
    return lang === "zh" ? "异常收口" : "closed with issues";
  }
  return statusLabel(status);
}

export function supervisedProposalStatusLabel(status: string, fallback: string, lang: "zh" | "en") {
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

export function displaySupervisedRunStatus(run: EvolutionRun, lang: "zh" | "en", statusLabel: (status: string) => string) {
  return run.runSemantics?.runStatusLabel || supervisedRunBucketLabel(run.status, lang, statusLabel);
}

export function displaySupervisedTechnicalText(
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

export function displaySupervisedRunSummary(
  run: EvolutionRun,
  lang: "zh" | "en",
  decisionLabel: (decision: string) => string,
) {
  return displaySupervisedTechnicalText(run.summary, run.decision, lang, decisionLabel);
}

export function compactCaseObject(value: Record<string, unknown> | undefined) {
  if (!value || Object.keys(value).length === 0) {
    return "";
  }
  const text = JSON.stringify(value);
  return text.length > 160 ? `${text.slice(0, 159)}...` : text;
}
