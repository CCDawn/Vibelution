import type {
  Team,
  TeamWorkflowCandidate,
  TeamWorkflowSourceCollectionPromptCachePolicy,
  TeamWorkflowSourceCollectionPromptCachePolicyRef,
} from "../../../api/types";
import type { TeamSourceResultTone } from "../../../components/vui/product/team-management";
import { isKnowledgeExpansionWorkflowTeam } from "../teamKindModel";
import {
  evidenceLedgerText,
  sourceCollectionEvidenceLedgerActionLabel,
  type SourceCollectionEvidenceLedgerSummary,
} from "./evidenceModel";

/** UI-agnostic evidence rows for source-detail panels. */
export type SourceCollectionEvidenceDetailItem = {
  id: string;
  label: string;
  value: string;
  title: string;
  href?: string;
};

export const SOURCE_COLLECTION_STAGE_WRITEBACK_SYNC_GRACE_MS = 30_000;
export const SOURCE_COLLECTION_RUN_PREVIEW_LIMIT = 20;
export const SOURCE_COLLECTION_RESULT_PAGE_SIZE = 8;
export const SOURCE_COLLECTION_SEARCH_EXECUTION_ROLES = new Set(["source_finder"]);
export const SOURCE_COLLECTION_LOCAL_SCAN_DEFAULT_ROOTS = "workspace/knowledge";
export const SOURCE_COLLECTION_PROMPT_CACHE_POLICY = {
  requirement: "required_for_llm_execution",
} as const;
export const SOURCE_COLLECTION_PROMPT_CACHE_MODEL_LABEL = "configured prompt-cache model";

export type SourceCollectionMode = "web_search" | "local_workspace" | "mixed";

export type SourceCollectionDraft = {
  title: string;
  topic: string;
  goal: string;
  querySeeds: string;
  inputRefs: string;
  searchLanguages: string;
  sourceTypes: string;
  maxResultsPerQuery: number;
  collectionMode: SourceCollectionMode;
  localScanRoots: string;
};

export type SourceCollectionStorageOpenTarget =
  | "run_directory"
  | "artifacts_directory"
  | "search_plan"
  | "search_events"
  | "records"
  | "candidates"
  | "candidate_store"
  | "data_processing_run"
  | "data_processing_records";

export type SourceCollectionStorageArtifacts = {
  runDirectory: string;
  artifactsDirectory: string;
  searchPlanPath: string;
  searchEventsPath: string;
  recordsPath: string;
  candidatesPath: string;
  candidateStorePath: string;
  dataProcessingRunPath: string;
  dataProcessingRecordsPath: string;
};

export function formatTime(value: string, lang: "zh" | "en") {
  const parsed = new Date(String(value || ""));
  if (Number.isNaN(parsed.getTime())) {
    return value || "-";
  }
  return new Intl.DateTimeFormat(lang === "zh" ? "zh-CN" : "en-US", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}

export function splitDraftList(value: string, limit = 12) {
  return value
    .split(/[\n,，;；]+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, limit);
}

export function compactSourceCollectionQuerySeeds(topic: string, querySeeds: string) {
  const seeds = splitDraftList(querySeeds, 12);
  const normalizedTopic = topic.trim();
  if (normalizedTopic && !seeds.some((item) => item.toLowerCase() === normalizedTopic.toLowerCase())) {
    seeds.push(normalizedTopic);
  }
  return seeds.slice(0, 12);
}

/** Fallback ingestion/status labels used by source-collection status mapping. */
export function workflowIngestionStatusLabel(value: string, lang: "zh" | "en") {
  const normalized = String(value || "").trim();
  const zh: Record<string, string> = {
    empty: "空",
    blocked: "阻塞",
    needs_screening: "待审查",
    needs_plan: "待规划",
    needs_revision: "需修订",
    needs_evidence: "补证据",
    needs_review: "待审核",
    in_progress: "推进中",
    pending: "待启动",
    ready: "已跑通",
    planned: "已规划",
    approved: "已通过",
    rejected: "已拒绝",
  };
  const en: Record<string, string> = {
    empty: "empty",
    blocked: "blocked",
    needs_screening: "screening",
    needs_plan: "needs plan",
    needs_revision: "revision",
    needs_evidence: "evidence",
    needs_review: "review",
    in_progress: "in progress",
    pending: "pending",
    ready: "ready",
    planned: "planned",
    approved: "approved",
    rejected: "rejected",
  };
  return (lang === "zh" ? zh : en)[normalized] ?? (normalized || "-");
}

export function sourceCollectionStatusLabel(value: string | undefined | null, lang: "zh" | "en") {
  const normalized = String(value || "").trim().toLowerCase();
  const zh: Record<string, string> = {
    active: "进行中",
    agent_notification_failed: "通知 Agent 失败",
    agent_notified: "等待资料入库 Agent",
    agent_wake_pending: "Agent 待唤醒",
    blocked: "阻塞",
    collecting: "待继续搜集",
    completed: "已完成",
    failed: "失败",
    in_progress: "推进中",
    needs_attention: "需处理",
    open: "待执行",
    pending: "待启动",
    pending_screening: "待 Agent 复核",
    planned: "已计划",
    processing: "已搜索待审查",
    reviewing: "待 Agent 复核",
    ready: "已就绪",
    ready_for_screening: "可审查",
    returned: "已退回",
    satisfied: "已通过",
    waiting_for_writeback: "待回写",
  };
  const en: Record<string, string> = {
    active: "active",
    agent_notification_failed: "Agent notification failed",
    agent_notified: "waiting for steward Agent",
    agent_wake_pending: "Agent wake pending",
    blocked: "blocked",
    collecting: "ready to continue",
    completed: "completed",
    failed: "failed",
    in_progress: "in progress",
    needs_attention: "needs attention",
    open: "open",
    pending: "pending",
    pending_screening: "pending screening",
    planned: "planned",
    processing: "ready for screening",
    reviewing: "ready for screening",
    ready: "ready",
    ready_for_screening: "ready for screening",
    returned: "returned",
    satisfied: "satisfied",
    waiting_for_writeback: "waiting for writeback",
  };
  return (lang === "zh" ? zh : en)[normalized] ?? workflowIngestionStatusLabel(normalized, lang);
}

export function sourceCollectionAgentRoleLabel(value: string | undefined | null, lang: "zh" | "en") {
  const normalized = String(value || "").trim();
  if (!normalized || lang !== "zh") {
    return normalized || "-";
  }
  const zh: Record<string, string> = {
    "Research Coordination Agent": "科研协调 Agent",
    source_finder: "资料寻找 Agent",
    source_extractor: "资料提炼 Agent",
    source_relation_mapper: "资料关系整理 Agent",
    source_ingestor: "资料入库 Agent",
  };
  return zh[normalized] ?? normalized;
}

export function sourceCollectionEvidenceLedgerDetailItems(
  summary: SourceCollectionEvidenceLedgerSummary,
  lang: "zh" | "en",
): SourceCollectionEvidenceDetailItem[] {
  const items: SourceCollectionEvidenceDetailItem[] = [
    {
      id: "status",
      label: lang === "zh" ? "账本状态" : "Ledger status",
      value: `${summary.status} · ${sourceCollectionEvidenceLedgerActionLabel(summary, lang)}`,
      title: summary.status,
    },
  ];
  if (summary.supportLevel) {
    items.push({
      id: "support",
      label: lang === "zh" ? "支持度" : "Support",
      value: summary.supportLevel,
      title: summary.supportLevel,
    });
  }
  [
    ["claim", lang === "zh" ? "Claim" : "Claim", summary.claims],
    ["finding", lang === "zh" ? "Key finding" : "Key finding", summary.keyFindings],
    ["citation", lang === "zh" ? "Citation" : "Citation", summary.citations],
    ["source-ref", lang === "zh" ? "来源锚点" : "Source ref", summary.sourceRefs],
    ["evidence-ref", lang === "zh" ? "证据锚点" : "Evidence ref", summary.evidenceRefs],
  ].forEach(([key, label, values]) => {
    (values as unknown[]).slice(0, 4).forEach((value, index) => {
      const text = evidenceLedgerText(value);
      if (!text) {
        return;
      }
      items.push({
        id: `${key}-${index}`,
        label: `${label} ${index + 1}`,
        value: text,
        title: text,
      });
    });
  });
  [
    ["risk", lang === "zh" ? "风险" : "Risk", summary.riskFlags],
    ["limitation", lang === "zh" ? "限制" : "Limitation", summary.limitations],
    ["uncertainty", lang === "zh" ? "不确定性" : "Uncertainty", summary.uncertainty],
  ].forEach(([key, label, values]) => {
    (values as string[]).slice(0, 3).forEach((value, index) => {
      items.push({
        id: `${key}-${index}`,
        label: `${label} ${index + 1}`,
        value,
        title: value,
      });
    });
  });
  if (summary.nextAction) {
    items.push({
      id: "next-action",
      label: lang === "zh" ? "下一步" : "Next action",
      value: summary.nextAction,
      title: summary.nextAction,
    });
  }
  return items;
}

export function sourceCollectionLanguageLabel(value: string | undefined | null, lang: "zh" | "en") {
  const normalized = String(value || "").trim().toLowerCase();
  const zh: Record<string, string> = {
    en: "英文",
    zh: "中文",
    cn: "中文",
  };
  const en: Record<string, string> = {
    en: "English",
    zh: "Chinese",
    cn: "Chinese",
  };
  return (lang === "zh" ? zh : en)[normalized] ?? (value || "-");
}

export function sourceCollectionStorageArtifactsForRun(
  teamId: string,
  runId: string,
): SourceCollectionStorageArtifacts | null {
  if (!teamId || !runId) {
    return null;
  }
  const runDirectory = `workspace/teams/${teamId}/source_collection_runs/${runId}`;
  return {
    runDirectory,
    artifactsDirectory: `${runDirectory}/artifacts`,
    searchPlanPath: `${runDirectory}/search_plan.json`,
    searchEventsPath: `${runDirectory}/search_events.jsonl`,
    recordsPath: `${runDirectory}/records.jsonl`,
    candidatesPath: `${runDirectory}/candidates.jsonl`,
    candidateStorePath: `workspace/teams/${teamId}/candidate_store/index.json`,
    dataProcessingRunPath: `workspace/data_processing/runs/${runId}/run.json`,
    dataProcessingRecordsPath: `workspace/data_processing/runs/${runId}/records.jsonl`,
  };
}

export function sourceCollectionStorageTargetLabel(target: SourceCollectionStorageOpenTarget, lang: "zh" | "en") {
  const zh: Record<SourceCollectionStorageOpenTarget, string> = {
    run_directory: "打开批次目录",
    artifacts_directory: "打开附件目录",
    search_plan: "打开搜索计划",
    search_events: "打开搜索步骤",
    records: "打开搜集记录",
    candidates: "打开候选镜像",
    candidate_store: "打开候选仓库",
    data_processing_run: "打开通用运行记录",
    data_processing_records: "打开资料记录",
  };
  const en: Record<SourceCollectionStorageOpenTarget, string> = {
    run_directory: "Open run folder",
    artifacts_directory: "Open artifacts",
    search_plan: "Open search plan",
    search_events: "Open search trace",
    records: "Open records",
    candidates: "Open candidates",
    candidate_store: "Open candidate store",
    data_processing_run: "Open generic run",
    data_processing_records: "Open DataRecord",
  };
  return lang === "zh" ? zh[target] : en[target];
}

export function sourceCollectionStorageTargetForRef(
  ref: string,
  artifacts: SourceCollectionStorageArtifacts | null,
): SourceCollectionStorageOpenTarget | null {
  if (!artifacts) {
    return null;
  }
  const normalizedRef = String(ref || "").trim();
  const mappings: Array<[keyof SourceCollectionStorageArtifacts, SourceCollectionStorageOpenTarget]> = [
    ["runDirectory", "run_directory"],
    ["artifactsDirectory", "artifacts_directory"],
    ["searchPlanPath", "search_plan"],
    ["searchEventsPath", "search_events"],
    ["recordsPath", "records"],
    ["candidatesPath", "candidates"],
    ["candidateStorePath", "candidate_store"],
    ["dataProcessingRunPath", "data_processing_run"],
    ["dataProcessingRecordsPath", "data_processing_records"],
  ];
  return mappings.find(([key]) => artifacts[key] === normalizedRef)?.[1] ?? null;
}

export function hasSourceCollectionPromptCachePolicy(
  policy: TeamWorkflowSourceCollectionPromptCachePolicy | undefined | null,
): policy is TeamWorkflowSourceCollectionPromptCachePolicy {
  return Boolean(policy?.policyId || policy?.requirement || policy?.promptCacheMode);
}

export function sourceCollectionPromptCacheStatusLabel(status: string, lang: "zh" | "en") {
  const normalized = String(status || "").toLowerCase();
  if (lang === "zh") {
    if (normalized === "satisfied") return "已通过";
    if (normalized === "warning") return "警告";
    if (normalized === "blocked") return "已阻断";
    if (normalized === "disabled") return "已关闭";
    return "待检查";
  }
  if (normalized === "satisfied") return "satisfied";
  if (normalized === "warning") return "warning";
  if (normalized === "blocked") return "blocked";
  if (normalized === "disabled") return "disabled";
  return "pending";
}

export function sourceCollectionPromptCacheModelDisplay(
  policy: TeamWorkflowSourceCollectionPromptCachePolicy | null,
  ref: TeamWorkflowSourceCollectionPromptCachePolicyRef | null,
  lang: "zh" | "en",
) {
  const rawLabel = policy?.modelName || ref?.modelId || SOURCE_COLLECTION_PROMPT_CACHE_MODEL_LABEL;
  const resolutionStatus = String(policy?.modelResolution?.status || "").toLowerCase();
  if (resolutionStatus === "fallback") {
    return lang === "zh" ? `${rawLabel}（自动兜底）` : `${rawLabel} (fallback)`;
  }
  if (resolutionStatus === "requested") {
    return lang === "zh" ? `${rawLabel}（指定）` : `${rawLabel} (requested)`;
  }
  return rawLabel;
}

export function sourceCollectionModeForTeam(
  team: Team | null | undefined,
  draft: SourceCollectionDraft,
): SourceCollectionMode {
  if (!isKnowledgeExpansionWorkflowTeam(team)) {
    return "web_search";
  }
  return draft.collectionMode || "mixed";
}

export function sourceCollectionLocalScanScopeForDraft(mode: SourceCollectionMode, draft: SourceCollectionDraft) {
  if (mode === "web_search") {
    return {};
  }
  return {
    roots: splitDraftList(draft.localScanRoots || SOURCE_COLLECTION_LOCAL_SCAN_DEFAULT_ROOTS, 12),
    maxFiles: 24,
  };
}

export function sourceCollectionCollectionModeLabel(mode: SourceCollectionMode, lang: "zh" | "en") {
  const labels: Record<SourceCollectionMode, { zh: string; en: string }> = {
    web_search: { zh: "网络搜集", en: "Web search" },
    local_workspace: { zh: "本地导入", en: "Local import" },
    mixed: { zh: "混合", en: "Mixed" },
  };
  return labels[mode][lang];
}

export function sourceCollectionResultTone(value: string): TeamSourceResultTone {
  const normalized = String(value || "").toLowerCase();
  if (normalized.includes("approved") || normalized.includes("ready") || normalized.includes("prefiltered")) {
    return "ready";
  }
  if (normalized.includes("invalid") || normalized.includes("broken") || normalized.includes("rejected")) {
    return "danger";
  }
  if (normalized.includes("revision") || normalized.includes("pending")) {
    return "warning";
  }
  return "neutral";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function candidateSourceQualityAssessmentSummary(candidate: TeamWorkflowCandidate) {
  const metadata = isRecord(candidate.metadata) ? candidate.metadata : {};
  const assessment = isRecord(metadata.sourceQualityAssessment) ? metadata.sourceQualityAssessment : null;
  if (!assessment) {
    return null;
  }
  const scores = isRecord(assessment.scores) ? assessment.scores : {};
  return {
    assessmentId: String(assessment.assessmentId || ""),
    decision: String(assessment.decision || ""),
    overallScore: Number(scores.overall || 0),
  };
}

export function sourceCollectionSimpleRecordStatusLabel(
  linkedCandidate: TeamWorkflowCandidate | null,
  sourceQualitySummary: ReturnType<typeof candidateSourceQualityAssessmentSummary>,
  lang: "zh" | "en",
) {
  if (!linkedCandidate) {
    return lang === "zh" ? "待提炼" : "extract";
  }
  const normalized = [
    sourceQualitySummary?.decision,
    linkedCandidate.qualityStatus,
    linkedCandidate.currentState,
  ].filter(Boolean).join(" ").toLowerCase();
  if (
    normalized.includes("approved")
    || normalized.includes("source_screened")
    || normalized.includes("ready")
    || normalized.includes("prefiltered")
  ) {
    return lang === "zh" ? "通过" : "kept";
  }
  if (
    normalized.includes("rejected")
    || normalized.includes("invalid")
    || normalized.includes("broken")
    || normalized.includes("revision")
  ) {
    return lang === "zh" ? "需补" : "revise";
  }
  if (sourceQualitySummary || normalized.includes("screened")) {
    return lang === "zh" ? "已审" : "reviewed";
  }
  return lang === "zh" ? "待审" : "review";
}

export function sourceCollectionSimpleCandidateStatusLabel(candidate: TeamWorkflowCandidate, lang: "zh" | "en") {
  return sourceCollectionSimpleRecordStatusLabel(candidate, candidateSourceQualityAssessmentSummary(candidate), lang);
}

export function sourceCollectionCandidateQualityState(candidate: TeamWorkflowCandidate) {
  const summary = candidateSourceQualityAssessmentSummary(candidate);
  const normalized = `${candidate.currentState || ""} ${candidate.qualityStatus || ""}`.toLowerCase();
  const assessed =
    Boolean(summary)
    || normalized.includes("screened")
    || normalized.includes("approved")
    || normalized.includes("revision");
  const approved =
    summary?.decision === "approved"
    || normalized.includes("source_screened")
    || normalized.includes(" approved");
  return {
    assessed,
    approved,
  };
}
