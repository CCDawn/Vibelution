import type { TeamWorkflowSourceCollectionRunStartPayload } from "../../../api/types";

import type { SourceCollectionStepState } from "./runModel";

export type SourceCollectionStageModuleId = "finding" | "extraction" | "relations" | "ingestion";

export type SourceCollectionActionReadiness = {
  disabled: boolean;
  loading: boolean;
  reason: string;
};

export type SourceCollectionCoverageSummary = {
  applicable?: boolean;
  coverageKind?: string;
  complete?: boolean;
  total?: number;
  processed?: number;
  missing?: number;
  invalid?: number;
  blocked?: number;
  duplicate?: number;
};

export type SourceCollectionStageTaskToolProgress = {
  required?: boolean;
  total?: number;
  completed?: number;
  complete?: boolean;
  completedIds?: string[];
  pendingIds?: string[];
};

export type SourceCollectionStageChecklistItem = {
  id?: string;
  description?: string;
  order?: number;
};

export type SourceCollectionStageCompletionGate = {
  requiresTaskChecklist?: boolean;
  requiresArtifact?: boolean;
  taskChecklistComplete?: boolean;
  artifactComplete?: boolean;
  passed?: boolean;
};

export type SourceCollectionStageActionReadinessProjection = {
  canStart?: boolean;
  reasonCode?: string;
  disabledReason?: string;
  recommendedAction?: "start" | "continue" | "retry" | "wait" | "inspect" | string;
  actionLabel?: string;
};

export type SourceCollectionStageClosureSummary = {
  userStatus?: "success" | "partial" | "failed" | string;
  artifactStatus?: string;
  agentTurnStatus?: string;
  targetLabel?: string;
  message?: string;
  progressLabel?: string;
  successCount?: number;
  excludedSourceCount?: number;
  failedCount?: number;
  blockedCount?: number;
  invalidIds?: string[];
  retryInstruction?: string;
  nextAction?: string;
  artifactComplete?: boolean;
  taskChecklistComplete?: boolean;
  completionGatePassed?: boolean;
  taskToolProgress?: SourceCollectionStageTaskToolProgress;
  completionGate?: SourceCollectionStageCompletionGate;
};

export type SourceCollectionStageCardProjection = {
  stageId: SourceCollectionStageModuleId;
  status: string;
  isClosedLoop?: boolean;
  userStatusLabel?: string;
  userSummary?: string;
  actionReadiness?: SourceCollectionStageActionReadinessProjection;
  agentTaskStatus?: string;
  artifactStatus?: string;
  artifactSummary?: string;
  currentCoverageSummary?: SourceCollectionCoverageSummary;
  counts?: {
    input?: number;
    artifact?: number;
    output?: number;
    pending?: number;
    task?: number;
    historicalTask?: number;
    excluded?: number;
    rawRecord?: number;
  };
  latestTask?: {
    taskId?: string;
    stageId?: string;
    agentId?: string;
    agentRole?: string;
    sessionId?: string;
    status?: string;
    summary?: string;
    updatedAt?: string;
    resultKeys?: string[];
    evidenceRefCount?: number;
    nextActionCount?: number;
    coverageSummary?: SourceCollectionCoverageSummary;
    invalidCandidateIds?: string[];
    invalidRecordIds?: string[];
    closureSummary?: SourceCollectionStageClosureSummary;
    taskToolRequired?: boolean;
    taskChecklist?: SourceCollectionStageChecklistItem[];
    taskToolProgress?: SourceCollectionStageTaskToolProgress;
    completionGate?: SourceCollectionStageCompletionGate;
    materializedSources?: Record<string, unknown>;
    materializedContentExtraction?: Record<string, unknown>;
  };
  resultKeys?: string[];
  nextActions?: string[];
  blockingReasons?: string[];
};

export type ResearchStageType = "knowledge_collection" | "experiment" | "iteration";

export type ResearchStageRound = {
  stageRoundId: string;
  stageType: ResearchStageType;
  roundNumber: number;
  status: string;
  title?: string;
  topic: string;
  goal: string;
  sourceRunIds?: string[];
  querySeeds?: string[];
  promptCachePolicy?: TeamWorkflowSourceCollectionRunStartPayload["promptCachePolicy"];
  sourceCollectionStageCards?: SourceCollectionStageCardProjection[];
  sourceCollectionStageCardSummary?: {
    stageCount?: number;
    closedLoopCount?: number;
    agentTaskCount?: number;
    recordCount?: number;
    rawRecordCount?: number;
    excludedSourceCount?: number;
    sourceCandidateCount?: number;
    assessedSourceCandidateCount?: number;
    approvedSourceCandidateCount?: number;
    graphNodeCount?: number;
    stewardPackCount?: number;
    formalKnowledgeSyncCount?: number;
  };
  experimentPlanRef?: {
    planId: string;
    status: string;
    storagePath: string;
    updatedAt: string;
  };
  teamMemoryRecordId?: string;
  coordinationContract?: {
    linkedChatRoomId?: string;
    autoStarted?: boolean;
    expectedAction?: string;
  };
  warnings?: Array<{ code?: string; severity?: string; message?: string }>;
};

export type ResearchStagePhaseStatus = {
  stageType: ResearchStageType;
  label: string;
  status: string;
  roundCount: number;
  activeRoundId: string;
  latestRound?: ResearchStageRound | null;
  primaryAction: string;
  secondaryAction: string;
  canStart: boolean;
  canContinue: boolean;
  canNewRound: boolean;
  requiresUserDecision: boolean;
  readiness?: {
    ready?: boolean;
    reason?: string;
  };
};

export type ResearchStageRoundStatusPayload = {
  schemaVersion: number;
  teamId: string;
  status: string;
  currentStage: string;
  phases: ResearchStagePhaseStatus[];
  activeRounds: ResearchStageRound[];
  latestRound?: ResearchStageRound | null;
  roundCount: number;
  boundaries: {
    externalSearchTriggered: boolean;
    writesFormalKnowledge: boolean;
    writesRag: boolean;
    writesOfficialGraph: boolean;
    autoTransitionsNextStage: boolean;
    stageRecordsOnly: boolean;
  };
};

type SourceCollectionStageRoundCards = {
  stageRoundId?: string;
  stageType?: string;
  roundNumber?: number;
  sourceCollectionStageCards?: SourceCollectionStageCardProjection[];
};

export type SourceCollectionStageCardsStatus = {
  stageCards?: SourceCollectionStageCardProjection[];
  phases?: Array<{
    stageType?: string;
    latestRound?: SourceCollectionStageRoundCards | null;
  }>;
  latestRound?: SourceCollectionStageRoundCards | null;
  activeRounds?: SourceCollectionStageRoundCards[];
};

export type SourceCollectionPhaseCloseGateStage = {
  stageId: SourceCollectionStageModuleId;
  status?: string;
  passed?: boolean;
  blockingReasons?: string[];
};

export type SourceCollectionPhaseCloseGate = {
  runId: string;
  stageRoundId?: string;
  stageRoundStatus?: string;
  status: "idle" | "needs_continue" | "ready_to_close" | "closed_loop" | string;
  passed?: boolean;
  stageGatePassed?: boolean;
  stateReconciliationRequired?: boolean;
  stageCount?: number;
  closedLoopCount?: number;
  stages?: SourceCollectionPhaseCloseGateStage[];
  blockingReasons?: string[];
};

export type SourceCollectionPhaseCloseGateSummary = {
  scope?: {
    kind?: string;
    runId?: string;
    includesHistorical?: boolean;
    eligibleForPhaseCloseGate?: boolean;
  };
  phaseCloseGate?: SourceCollectionPhaseCloseGate;
};

const SOURCE_COLLECTION_ACTION_READY: SourceCollectionActionReadiness = {
  disabled: false,
  loading: false,
  reason: "",
};

export function sourceCollectionPhaseCloseGateForRun(
  summary: SourceCollectionPhaseCloseGateSummary | null | undefined,
  selectedRunId: string | null | undefined,
) {
  const runId = String(selectedRunId || "").trim();
  const scope = summary?.scope;
  const gate = summary?.phaseCloseGate;
  if (
    !runId
    || !scope
    || scope.kind !== "source_run"
    || scope.runId !== runId
    || scope.includesHistorical === true
    || scope.eligibleForPhaseCloseGate !== true
    || !gate
    || gate.runId !== runId
  ) {
    return null;
  }
  return gate;
}

export function sourceCollectionPhaseCloseGateNextStage(
  gate: SourceCollectionPhaseCloseGate | null | undefined,
) {
  return gate?.stages?.find((stage) => stage?.passed !== true)?.stageId ?? null;
}

export function sourceCollectionStageProjectionState(
  projection: SourceCollectionStageCardProjection | null | undefined,
  fallback: SourceCollectionStepState,
): SourceCollectionStepState {
  if (!projection?.status) {
    return fallback;
  }
  if (projection.status === "agent_running") {
    return "active";
  }
  if (projection.status === "agent_interrupted") {
    return "failed";
  }
  if (projection.status === "closed_loop" || projection.status === "artifact_ready_no_latest_agent_task") {
    return "done";
  }
  if (projection.status === "agent_blocked") {
    return "failed";
  }
  if (projection.status === "partial_current_inputs" || projection.status === "agent_done_artifact_pending" || projection.status === "pending") {
    return "pending";
  }
  return projection.status === "idle" ? "idle" : fallback;
}

export function sourceCollectionCompletionFlowNodeState(status: string | undefined | null): SourceCollectionStepState {
  const normalized = String(status || "").trim().toLowerCase();
  if (normalized === "running" || normalized === "in_progress" || normalized === "active") {
    return "active";
  }
  if (normalized === "completed" || normalized === "done" || normalized === "closed_loop") {
    return "done";
  }
  if (normalized === "failed" || normalized === "blocked" || normalized.includes("failed")) {
    return "failed";
  }
  if (normalized === "pending" || normalized === "pending_review" || normalized === "queued") {
    return "pending";
  }
  return "idle";
}

export function sourceCollectionStageProjectionCount(
  projection: SourceCollectionStageCardProjection | null | undefined,
  key: keyof NonNullable<SourceCollectionStageCardProjection["counts"]>,
  fallback: number,
): number {
  const value = projection?.counts?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

export function sourceCollectionNonNegativeCount(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? Math.max(0, value) : 0;
}

export function sourceCollectionCoverageMetric(
  coverage: SourceCollectionCoverageSummary | null | undefined,
  lang: "zh" | "en",
  stageId?: SourceCollectionStageModuleId | string | null,
) {
  if (!coverage?.applicable) {
    return "";
  }
  const total = typeof coverage.total === "number" ? coverage.total : 0;
  const processed = typeof coverage.processed === "number" ? coverage.processed : 0;
  const missing = typeof coverage.missing === "number" ? coverage.missing : 0;
  const invalid = typeof coverage.invalid === "number" ? coverage.invalid : 0;
  if (!total) {
    return "";
  }
  if (lang === "zh") {
    const normalizedStageId = String(stageId || "").toLowerCase();
    const stageCopy: Record<string, { verb: string; missing: string }> = {
      finding: { verb: "已寻找", missing: "待补找" },
      extraction: { verb: "已提炼/审查", missing: "待补提炼" },
      relations: { verb: "已整理", missing: "待补关系" },
      ingestion: { verb: "已入库审核", missing: "待补入库" },
    };
    const copy = stageCopy[normalizedStageId] ?? { verb: "已处理", missing: "待补读" };
    return `${copy.verb} ${processed}/${total}${missing > 0 ? ` · ${copy.missing} ${missing}` : ""}${invalid > 0 ? ` · 无效 ID ${invalid}` : ""}`;
  }
  return `processed ${processed}/${total}${missing > 0 ? ` · missing ${missing}` : ""}${invalid > 0 ? ` · invalid IDs ${invalid}` : ""}`;
}

export function sourceCollectionTaskToolProgressMetric(
  progress: SourceCollectionStageTaskToolProgress | null | undefined,
  lang: "zh" | "en",
  checklist?: SourceCollectionStageChecklistItem[] | null,
) {
  if (!progress?.required) {
    return "";
  }
  const total = typeof progress.total === "number" ? progress.total : 0;
  const completed = typeof progress.completed === "number" ? progress.completed : 0;
  if (!total) {
    return "";
  }
  const pendingDescriptions = sourceCollectionTaskToolPendingDescriptions(progress, checklist);
  const pendingText = pendingDescriptions.length > 0
    ? (lang === "zh" ? ` · 剩余 ${pendingDescriptions.length} 项` : ` · ${pendingDescriptions.length} pending`)
    : "";
  return lang === "zh" ? `检查项 ${completed}/${total}${pendingText}` : `checklist ${completed}/${total}${pendingText}`;
}

function sourceCollectionTaskToolPendingDescriptions(
  progress: SourceCollectionStageTaskToolProgress | null | undefined,
  checklist?: SourceCollectionStageChecklistItem[] | null,
) {
  const pendingIds = Array.isArray(progress?.pendingIds)
    ? progress.pendingIds.map((id) => String(id || "").trim()).filter(Boolean)
    : [];
  if (!pendingIds.length) {
    return [];
  }
  const checklistById = new Map(
    (Array.isArray(checklist) ? checklist : [])
      .filter((item) => item?.id)
      .map((item) => [String(item.id), item.description || item.id || ""]),
  );
  return pendingIds
    .map((id) => checklistById.get(id) || id)
    .map((description) => String(description || "").trim())
    .filter(Boolean);
}

function sourceCollectionTaskToolProgressDetail(
  progress: SourceCollectionStageTaskToolProgress | null | undefined,
  checklist: SourceCollectionStageChecklistItem[] | null | undefined,
  lang: "zh" | "en",
) {
  if (!progress?.required) {
    return "";
  }
  const total = typeof progress.total === "number" ? progress.total : 0;
  const completed = typeof progress.completed === "number" ? progress.completed : 0;
  if (!total) {
    return "";
  }
  const pendingDescriptions = sourceCollectionTaskToolPendingDescriptions(progress, checklist);
  if (lang === "zh") {
    return pendingDescriptions.length
      ? `检查项 ${completed}/${total}；剩余检查项：${pendingDescriptions.join("、")}`
      : `检查项 ${completed}/${total}`;
  }
  return pendingDescriptions.length
    ? `checklist ${completed}/${total}; pending: ${pendingDescriptions.join(", ")}`
    : `checklist ${completed}/${total}`;
}

function sourceCollectionStageTaskStatusLabel(status: string | null | undefined, lang: "zh" | "en") {
  const normalized = String(status || "").trim().toLowerCase();
  if (lang !== "zh") {
    return normalized || "task";
  }
  const labels: Record<string, string> = {
    queued: "待执行",
    running: "进行中",
    completed: "已回写",
    needs_review: "待补齐",
    blocked: "受阻",
    failed: "失败",
    cancelled: "已取消",
    interrupted: "已中断，需要继续",
  };
  return labels[normalized] ?? (normalized || "任务");
}

export function sourceCollectionStageProjectionTaskMetric(
  projection: SourceCollectionStageCardProjection | null | undefined,
  lang: "zh" | "en",
  syncing = false,
) {
  if (syncing) {
    return lang === "zh" ? "等待团队页刷新最新写回" : "Waiting for latest writeback";
  }
  const latestTask = projection?.latestTask;
  const historicalTaskCount = typeof projection?.counts?.historicalTask === "number" ? projection.counts.historicalTask : 0;
  if (!latestTask?.taskId) {
    if (historicalTaskCount > 0) {
      return lang === "zh" ? `历史任务 ${historicalTaskCount} 已忽略` : `${historicalTaskCount} historical tasks ignored`;
    }
    return "";
  }
  const evidenceCount = typeof latestTask.evidenceRefCount === "number" ? latestTask.evidenceRefCount : 0;
  const nextActionCount = typeof latestTask.nextActionCount === "number" ? latestTask.nextActionCount : 0;
  const taskStatusLabel = sourceCollectionStageTaskStatusLabel(latestTask.status || projection?.agentTaskStatus, lang);
  const currentCoverageMetric = sourceCollectionCoverageMetric(projection?.currentCoverageSummary, lang, projection?.stageId);
  const coverageMetric = sourceCollectionCoverageMetric(latestTask.coverageSummary, lang, projection?.stageId);
  const taskProgressMetric = sourceCollectionTaskToolProgressMetric(
    latestTask.closureSummary?.taskToolProgress || latestTask.taskToolProgress,
    lang,
    latestTask.taskChecklist,
  );
  if (currentCoverageMetric && projection?.currentCoverageSummary?.complete === false) {
    return `${taskStatusLabel}${taskProgressMetric ? ` · ${taskProgressMetric}` : ""} · ${currentCoverageMetric}${historicalTaskCount > 0 ? (lang === "zh" ? ` · 历史 ${historicalTaskCount}` : ` · historical ${historicalTaskCount}`) : ""}`;
  }
  if (coverageMetric) {
    return `${taskStatusLabel}${taskProgressMetric ? ` · ${taskProgressMetric}` : ""} · ${coverageMetric}${historicalTaskCount > 0 ? (lang === "zh" ? ` · 历史 ${historicalTaskCount}` : ` · historical ${historicalTaskCount}`) : ""}`;
  }
  if (lang === "zh") {
    return `${taskStatusLabel}${taskProgressMetric ? ` · ${taskProgressMetric}` : ""} · 证据引用 ${evidenceCount} · 后续建议 ${nextActionCount}${historicalTaskCount > 0 ? ` · 历史任务 ${historicalTaskCount}` : ""}`;
  }
  return `${taskStatusLabel}${taskProgressMetric ? ` · ${taskProgressMetric}` : ""} · evidence ${evidenceCount} · next ${nextActionCount}${historicalTaskCount > 0 ? ` · historical ${historicalTaskCount}` : ""}`;
}

function sourceCollectionStageArtifactSummaryLabel(
  projection: SourceCollectionStageCardProjection | null | undefined,
  lang: "zh" | "en",
) {
  if (!projection) {
    return "";
  }
  if (lang !== "zh") {
    return projection.artifactSummary || "";
  }
  const counts = projection.counts ?? {};
  const artifact = typeof counts.artifact === "number" ? counts.artifact : 0;
  const output = typeof counts.output === "number" ? counts.output : 0;
  const pending = typeof counts.pending === "number" ? counts.pending : 0;
  const excluded = typeof counts.excluded === "number" ? counts.excluded : 0;
  const excludedText = excluded > 0 ? `；已移出 ${excluded} 条无效来源` : "";
  if (projection.stageId === "finding") {
    return `${artifact} 条可处理原始资料${excludedText}；${pending} 个搜索任务待执行`;
  }
  if (projection.stageId === "extraction") {
    const coverage = sourceCollectionCoverageMetric(
      projection.currentCoverageSummary?.complete === false ? projection.currentCoverageSummary : projection.latestTask?.coverageSummary,
      lang,
      projection.stageId,
    );
    if (coverage) {
      return `${coverage}${excludedText}`;
    }
    if (artifact <= 0 && excluded > 0) {
      return `暂无候选资料；已移出 ${excluded} 条无有效内容来源`;
    }
    return `${artifact} 条候选资料来自本轮；通过 ${output}${excludedText}`;
  }
  if (projection.stageId === "relations") {
    return `节点 ${artifact} / 关系 ${output}`;
  }
  if (projection.stageId === "ingestion") {
    return `${pending} 个入库包待处理；${output} 个正式同步标记`;
  }
  return projection.artifactSummary || "";
}

function sourceCollectionStageBlockingReasonLabel(reason: string, lang: "zh" | "en") {
  if (lang !== "zh") {
    return reason;
  }
  const normalized = reason.trim();
  if (normalized.startsWith("Current stage coverage is partial:")) {
    return "当前批次还有资料未处理，需要继续本阶段补齐。";
  }
  if (normalized.startsWith("Agent writeback has partial candidate coverage:")) {
    return "Agent 只处理了部分候选，需要继续分页读取并补齐逐候选结果。";
  }
  const labels: Record<string, string> = {
    "Latest Agent turn was interrupted before stage writeback.":
      "最近一次 Agent 会话在阶段写回前中断，需要继续这次任务或重试。",
    "Agent task wrote back a structured result, but the expected stage artifact has not been created yet.":
      "已收到 Agent 结果，但还没有生成本阶段可用资料。",
    "Latest Agent task is blocked or failed.":
      "最近一次 Agent 任务受阻或失败。",
    "Inputs exist, but this stage has not produced its expected artifact yet.":
      "上游资料已存在，但这里还没有生成可用结果。",
  };
  return labels[normalized] ?? normalized;
}

function sourceCollectionStageBlockingReasonsLabel(
  reasons: string[] | undefined,
  lang: "zh" | "en",
) {
  return (reasons ?? [])
    .map((reason) => sourceCollectionStageBlockingReasonLabel(reason, lang))
    .filter(Boolean);
}

function sourceCollectionStageRecoveryActionLabel(
  stageId: SourceCollectionStageModuleId | string | null | undefined,
  lang: "zh" | "en",
) {
  const normalized = String(stageId || "").toLowerCase();
  if (lang !== "zh") {
    const labels: Record<string, string> = {
      finding: "continue finding sources",
      extraction: "continue extraction",
      relations: "rebuild source relations",
      ingestion: "continue ingestion",
    };
    return labels[normalized] ?? "continue this stage";
  }
  const labels: Record<string, string> = {
    finding: "继续补充资料",
    extraction: "继续补全提炼",
    relations: "重新整理关系",
    ingestion: "继续入库",
  };
  return labels[normalized] ?? "继续处理本阶段";
}

export function sourceCollectionStageRecoveryStatusLabel(
  stageId: SourceCollectionStageModuleId | string | null | undefined,
  lang: "zh" | "en",
) {
  const normalized = String(stageId || "").toLowerCase();
  if (lang !== "zh") {
    const labels: Record<string, string> = {
      finding: "Needs more sources",
      extraction: "Needs extraction",
      relations: "Needs relation mapping",
      ingestion: "Needs ingestion",
    };
    return labels[normalized] ?? "Needs follow-up";
  }
  const labels: Record<string, string> = {
    finding: "待补资料",
    extraction: "待补提炼",
    relations: "待补关系",
    ingestion: "待入库",
  };
  return labels[normalized] ?? "待继续处理";
}

function sourceCollectionStageReadableObjectLabel(
  stageId: SourceCollectionStageModuleId | string | null | undefined,
  lang: "zh" | "en",
) {
  const normalized = String(stageId || "").toLowerCase();
  if (lang !== "zh") {
    const labels: Record<string, string> = {
      finding: "source records",
      extraction: "candidate sources",
      relations: "source relationships",
      ingestion: "ingestion pack",
    };
    return labels[normalized] ?? "usable results";
  }
  const labels: Record<string, string> = {
    finding: "原始资料",
    extraction: "候选资料",
    relations: "资料关系",
    ingestion: "入库结果",
  };
  return labels[normalized] ?? "可用资料";
}

export function sourceCollectionStageUserStatusLabel(
  projection: SourceCollectionStageCardProjection | null | undefined,
  lang: "zh" | "en",
  syncing = false,
) {
  if (!projection?.status) {
    return "";
  }
  if (projection.status === "agent_interrupted") {
    return lang === "zh"
      ? (projection.userStatusLabel || "已中断，需要继续")
      : "Interrupted; continue needed";
  }
  if (syncing) {
    return lang === "zh" ? "正在同步 Agent 结果" : "Syncing Agent result";
  }
  if (lang === "zh" && projection.userStatusLabel) {
    return projection.userStatusLabel;
  }
  const currentCoverage = projection.currentCoverageSummary;
  if (currentCoverage?.applicable && currentCoverage.complete === false) {
    return sourceCollectionStageRecoveryStatusLabel(projection.stageId, lang);
  }
  const closure = projection.latestTask?.closureSummary;
  if (closure?.userStatus === "failed") {
    if (projection.stageId === "extraction") {
      return lang === "zh" ? "本轮未生成候选资料" : "No candidate sources generated";
    }
    return lang === "zh" ? "本轮未完成闭环" : "This attempt did not close";
  }
  if (closure?.userStatus === "partial") {
    return lang === "zh" ? "本轮部分完成，待补齐" : "Partially completed";
  }
  if (closure?.userStatus === "success") {
    return lang === "zh" ? "本轮已成功闭环" : "Attempt closed successfully";
  }
  const coverage = projection.latestTask?.coverageSummary;
  if (coverage?.applicable && coverage.complete === false) {
    return sourceCollectionStageRecoveryStatusLabel(projection.stageId, lang);
  }
  if (projection.status === "partial_current_inputs") {
    return sourceCollectionStageRecoveryStatusLabel(projection.stageId, lang);
  }
  if (projection.status === "agent_done_artifact_pending") {
    if (
      projection.stageId === "extraction"
      && typeof projection.counts?.excluded === "number"
      && projection.counts.excluded > 0
      && Number(projection.counts?.artifact ?? 0) <= 0
    ) {
      return lang === "zh" ? "已移出无效来源" : "Invalid sources removed";
    }
    return lang === "zh" ? "已收到 Agent 结果，等待生成可用资料" : "Agent result received; waiting for usable output";
  }
  if (projection.status === "artifact_ready_agent_blocked") {
    return lang === "zh" ? "资料已生成，最近任务需排查" : "Output ready; latest task needs review";
  }
  if (projection.status === "pending" && Number(projection.counts?.artifact ?? 0) > 0) {
    return lang === "zh" ? "已有部分资料" : "Partial output ready";
  }
  const labels: Record<string, string> = lang === "zh"
    ? {
        agent_running: "Agent 正在处理",
        agent_interrupted: "已中断，需要继续",
        closed_loop: "本阶段已完成",
        artifact_ready_no_latest_agent_task: "资料已生成",
        agent_blocked: "Agent 任务受阻",
        pending: "等待本阶段产出",
        idle: "未开始",
      }
    : {
        agent_running: "Agent running",
        agent_interrupted: "Interrupted; continue needed",
        closed_loop: "Stage complete",
        artifact_ready_no_latest_agent_task: "Output ready",
        agent_blocked: "Agent blocked",
        pending: "Waiting for output",
        idle: "Not started",
      };
  return labels[projection.status] ?? (lang === "zh" ? "需要处理" : projection.status);
}

function sourceCollectionStageInterruptedSummary(
  projection: SourceCollectionStageCardProjection | null | undefined,
  lang: "zh" | "en",
) {
  const latestTask = projection?.latestTask;
  const closure = latestTask?.closureSummary;
  const progress = closure?.taskToolProgress || latestTask?.taskToolProgress;
  const progressDetail = sourceCollectionTaskToolProgressDetail(progress, latestTask?.taskChecklist, lang);
  const retryInstruction = closure?.retryInstruction || closure?.nextAction || (lang === "zh" ? "继续这次任务" : "continue this task");
  if (lang === "zh") {
    return `本轮已中断：Agent 私聊尚未完成阶段回写。${progressDetail ? `${progressDetail}。` : ""}建议：${retryInstruction}。`;
  }
  return `This attempt was interrupted before stage writeback.${progressDetail ? ` ${progressDetail}.` : ""} Next: ${retryInstruction}.`;
}

export function sourceCollectionStageUserSummary(
  projection: SourceCollectionStageCardProjection | null | undefined,
  lang: "zh" | "en",
) {
  if (!projection) {
    return "";
  }
  const objectLabel = sourceCollectionStageReadableObjectLabel(projection.stageId, lang);
  const closure = projection.latestTask?.closureSummary;
  const excluded = typeof projection.counts?.excluded === "number" ? projection.counts.excluded : 0;
  const artifact = typeof projection.counts?.artifact === "number" ? projection.counts.artifact : 0;
  if (projection.status === "agent_interrupted") {
    return sourceCollectionStageInterruptedSummary(projection, lang);
  }
  if (lang === "zh" && projection.userSummary) {
    return projection.userSummary;
  }
  const currentCoverage = projection.currentCoverageSummary;
  const currentTotal = typeof currentCoverage?.total === "number" ? currentCoverage.total : 0;
  const currentProcessed = typeof currentCoverage?.processed === "number" ? currentCoverage.processed : 0;
  const currentMissing = typeof currentCoverage?.missing === "number" ? currentCoverage.missing : 0;
  const currentInvalid = typeof currentCoverage?.invalid === "number" ? currentCoverage.invalid : 0;
  if (currentCoverage?.applicable && currentCoverage.complete === false && currentTotal > 0) {
    if (lang === "zh") {
      const invalidText = currentInvalid > 0 ? `无效 ID ${currentInvalid} 条。` : "";
      return `${objectLabel}当前进度 ${currentProcessed}/${currentTotal}，还有 ${currentMissing} 条需要补齐。${invalidText}建议：${sourceCollectionStageRecoveryActionLabel(projection.stageId, lang)}。`;
    }
    return `${currentProcessed}/${currentTotal} current inputs processed; ${currentMissing} still need work${currentInvalid > 0 ? `; ${currentInvalid} invalid IDs` : ""}.`;
  }
  if (closure?.userStatus === "failed" && projection.stageId === "extraction" && lang === "zh") {
    if (excluded > 0 && artifact <= 0) {
      return `本轮没有生成候选资料；已移出 ${excluded} 条无有效内容来源，避免后续重复处理。建议：继续搜索新资料。`;
    }
    const message = closure.message || "Agent 已回写，但没有生成候选资料。";
    const retryInstruction = closure.retryInstruction || closure.nextAction || "请使用完整 recordId 重试。";
    return `${message}建议：${retryInstruction}`;
  }
  if (closure?.message) {
    const retryInstruction = closure.retryInstruction || closure.nextAction || "";
    if (lang === "zh") {
      return closure.userStatus === "success" || !retryInstruction
        ? closure.message
        : `${closure.message}建议：${retryInstruction}`;
    }
    return closure.userStatus === "success" || !retryInstruction
      ? closure.message
      : `${closure.message} Next: ${retryInstruction}`;
  }
  const coverage = projection.latestTask?.coverageSummary;
  const total = typeof coverage?.total === "number" ? coverage.total : 0;
  const processed = typeof coverage?.processed === "number" ? coverage.processed : 0;
  const missing = typeof coverage?.missing === "number" ? coverage.missing : 0;
  const invalid = typeof coverage?.invalid === "number" ? coverage.invalid : 0;
  if (coverage?.applicable && coverage.complete === false && total > 0) {
    if (lang === "zh") {
      const invalidText = invalid > 0
        ? (coverage.coverageKind === "record_extractions"
          ? `Agent 返回的 recordId 没有匹配到本轮资料 ${invalid} 条。`
          : `Agent 返回的候选 ID 没有匹配到本轮资料 ${invalid} 条。`)
        : "";
      const recordIdHint = coverage.coverageKind === "record_extractions" ? "请使用完整 recordId 重试。" : "";
      return `${objectLabel}处理进度 ${processed}/${total}，还有 ${missing} 条需要补齐。${invalidText}建议：${sourceCollectionStageRecoveryActionLabel(projection.stageId, lang)}。${recordIdHint}`;
    }
    return `${processed}/${total} processed; ${missing} still need work${invalid > 0 ? `; ${invalid} writeback IDs did not match this run` : ""}.`;
  }
  if (projection.status === "agent_done_artifact_pending") {
    if (lang === "zh") {
      if (projection.stageId === "extraction" && excluded > 0) {
        return `Agent 已回写，本轮已移出 ${excluded} 条无有效内容来源；还没有生成可用候选资料。建议：继续搜索或补充新来源。`;
      }
      return `已收到 Agent 结果，但还没有生成可用${objectLabel}。建议：${sourceCollectionStageRecoveryActionLabel(projection.stageId, lang)}。`;
    }
    return `Agent returned a result, but usable ${objectLabel} has not been generated yet.`;
  }
  if (projection.status === "artifact_ready_agent_blocked") {
    return lang === "zh"
      ? `${objectLabel}已经可用，但最近一次 Agent 任务受阻；可以先查看结果，再决定是否重试。`
      : `${objectLabel} is available, but the latest Agent task is blocked.`;
  }
  if (projection.status === "agent_blocked") {
    return lang === "zh"
      ? "最近一次 Agent 任务没有完成。建议进入 Agent 私聊查看原因，或重新启动本阶段。"
      : "The latest Agent task did not complete. Open the Agent chat or restart this stage.";
  }
  const firstReason = sourceCollectionStageBlockingReasonsLabel(projection.blockingReasons, lang)[0];
  if (firstReason) {
    return firstReason;
  }
  return sourceCollectionStageArtifactSummaryLabel(projection, lang);
}

export function sourceCollectionStageBackendActionReadiness(
  projection: SourceCollectionStageCardProjection | null | undefined,
  fallback: SourceCollectionActionReadiness,
  noInputReason: string,
): SourceCollectionActionReadiness {
  const backendReadiness = projection?.actionReadiness;
  if (!backendReadiness || typeof backendReadiness.canStart !== "boolean") {
    return fallback;
  }
  if (backendReadiness.canStart) {
    return SOURCE_COLLECTION_ACTION_READY;
  }
  return {
    disabled: true,
    loading: false,
    reason: backendReadiness.disabledReason || fallback.reason || noInputReason,
  };
}

export function sourceCollectionStageCardsFromStatus(
  status: SourceCollectionStageCardsStatus | null | undefined,
) {
  if (status && "stageCards" in status) {
    return status.stageCards ?? [];
  }
  if (!status || !("phases" in status)) {
    return [];
  }
  const knowledgePhase = (status.phases ?? []).find((phase) => phase.stageType === "knowledge_collection");
  const rounds = [
    knowledgePhase?.latestRound ?? null,
    status.latestRound ?? null,
    ...(status.activeRounds ?? []),
  ].filter((round): round is SourceCollectionStageRoundCards => Boolean(round && round.stageType === "knowledge_collection"));
  const seen = new Set<string>();
  return rounds.flatMap((round) => {
    const key = round.stageRoundId || `${round.stageType}-${round.roundNumber}`;
    if (seen.has(key)) {
      return [];
    }
    seen.add(key);
    return round.sourceCollectionStageCards ?? [];
  });
}

export function selectSourceCollectionStageRound(
  summaryRound: ResearchStageRound | null | undefined,
  phases: ResearchStagePhaseStatus[],
  status: ResearchStageRoundStatusPayload | null | undefined,
  selectedRunId: string,
) {
  const knowledgePhase = phases.find((phase) => phase.stageType === "knowledge_collection");
  const candidateRounds = [
    summaryRound ?? null,
    knowledgePhase?.latestRound ?? null,
    status?.latestRound ?? null,
    ...(status?.activeRounds ?? []),
  ].filter((round): round is ResearchStageRound => Boolean(round && round.stageType === "knowledge_collection"));
  const dedupedRounds = new Map<string, ResearchStageRound>();
  candidateRounds.forEach((round) => {
    const key = round.stageRoundId || `${round.stageType}-${round.roundNumber}`;
    if (!dedupedRounds.has(key)) {
      dedupedRounds.set(key, round);
    }
  });
  const rounds = [...dedupedRounds.values()];
  if (!selectedRunId) {
    return rounds[0] ?? null;
  }
  return rounds.find((round) => (round.sourceRunIds ?? []).includes(selectedRunId)) ?? null;
}

export function sourceCollectionStageWritebackObservedTaskIds(cards: SourceCollectionStageCardProjection[]) {
  const taskIds = new Set<string>();
  cards.forEach((card) => {
    const taskId = String(card.latestTask?.taskId || "").trim();
    if (taskId) {
      taskIds.add(taskId);
    }
  });
  return taskIds;
}
