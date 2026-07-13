import type {
  DataProcessingRunListPayload,
  RuntimeSummary,
  WorkRunSnapshot,
} from "../../../api/types";

export type SourceCollectionStepState = "idle" | "active" | "pending" | "done" | "failed";

export type SourceCollectionRunSummaryValue = DataProcessingRunListPayload["runs"][number] | null | undefined;

export type SourceCollectionDisplayPhase =
  | "done"
  | "failed"
  | "idle"
  | "ingesting"
  | "needs_continue"
  | "needs_downstream"
  | "needs_screening"
  | "ready_for_experiment"
  | "running"
  | "screening"
  | "starting"
  | "waiting_for_writeback"
  | "writing";

export type SourceCollectionDisplayInput = {
  lang: "zh" | "en";
  hasRun: boolean;
  startPending: boolean;
  searchPending: boolean;
  backgroundActive: boolean;
  recordOutputPending: boolean;
  extractionPending: boolean;
  sourceQualityPending: boolean;
  graphPending: boolean;
  knowledgeIngestionPending: boolean;
  failed: boolean;
  searchOpenAssignmentCount: number;
  downstreamOpenAssignmentCount: number;
  pendingScreeningCount: number;
  rawRecordCount: number;
  candidateCount: number;
  activeWorkSummary?: string;
};

export type SourceCollectionDisplayState = {
  phase: SourceCollectionDisplayPhase;
  active: boolean;
  consoleState: SourceCollectionStepState;
  searchStepState: SourceCollectionStepState;
  statusText: string;
  decisionText: string;
};

function sourceCollectionRunMetric(run: SourceCollectionRunSummaryValue, keys: string[]) {
  if (!run) {
    return 0;
  }
  const scopes = [
    run.summary,
    (run.scope as Record<string, unknown> | undefined)?.sourceCollectionSummary,
    (run.metadata as Record<string, unknown> | undefined)?.sourceCollectionSummary,
    run.scope,
    run.metadata,
  ].filter((value): value is Record<string, unknown> => Boolean(value && typeof value === "object"));
  for (const scope of scopes) {
    for (const key of keys) {
      const value = Number(scope[key]);
      if (Number.isFinite(value) && value > 0) {
        return value;
      }
    }
  }
  return 0;
}

export function sourceCollectionRunRecordCount(run: SourceCollectionRunSummaryValue) {
  return sourceCollectionRunMetric(run, ["recordCount", "rawRecordCount", "createdUniqueRecordCount"]);
}

export function sourceCollectionRunCandidateMetric(run: SourceCollectionRunSummaryValue) {
  return sourceCollectionRunMetric(run, ["sourceCandidateCount", "candidateCount", "importedCount"]);
}

export function sourceCollectionRunHasUsableRecords(run: SourceCollectionRunSummaryValue) {
  return sourceCollectionRunRecordCount(run) > 0 || sourceCollectionRunCandidateMetric(run) > 0;
}

export function selectDefaultSourceCollectionRun(
  runs: DataProcessingRunListPayload["runs"],
  requestedRunId: string,
) {
  return runs.find((run) => run.runId === requestedRunId)
    ?? runs.find(sourceCollectionRunHasUsableRecords)
    ?? runs[0]
    ?? null;
}

export function sourceCollectionRunsForTeam(payload: DataProcessingRunListPayload | undefined, teamId: string) {
  return (payload?.runs ?? []).filter(
    (run) =>
      run.metadata?.startedFrom === "team_workflow_source_collection"
      && run.metadata?.teamId === teamId,
  );
}

export function sourceCollectionStableCountText(input: {
  loading: boolean;
  value: number;
  lang: "zh" | "en";
  zhUnit?: string;
  enUnit?: string;
  loadingText: string;
  syncingText: string;
}) {
  const value = Number.isFinite(input.value) ? Math.max(0, Math.floor(input.value)) : 0;
  const countText = input.lang === "zh"
    ? [String(value), input.zhUnit].filter(Boolean).join(" ")
    : input.enUnit ? `${value} ${input.enUnit}` : String(value);
  if (!input.loading) {
    return countText;
  }
  return value > 0 ? `${countText} · ${input.syncingText}` : input.loadingText;
}

export function sourceCollectionRunLabel(runId: string) {
  return runId ? `${runId.slice(0, 10)}...` : "-";
}

export function translateResearchPhrase(value: string | undefined | null, lang: "zh" | "en") {
  const text = String(value || "").trim();
  if (!text || lang !== "zh") {
    return text;
  }
  const normalized = text.toLowerCase();
  const zh: Record<string, string> = {
    "neural algorithm source batch": "神经算法资料搜索批次",
    "neural predictive coding": "神经预测编码",
    "predictive coding cortical hierarchy": "预测编码皮层层级",
    "synaptic plasticity learning rule": "突触可塑性学习规则",
    "neural gating attention mechanism": "神经门控注意机制",
    "collect traceable neuroscience sources that can support neural-network algorithm hypotheses.": "搜集可追踪的神经科学资料，用来支撑神经网络算法假设。",
  };
  return zh[normalized] ?? text;
}

export function sourceCollectionRunTitleLabel(title: string | undefined | null, lang: "zh" | "en") {
  return translateResearchPhrase(title, lang) || (lang === "zh" ? "资料搜索批次" : "Source collection run");
}

export function sourceCollectionRunOptionLabel(run: DataProcessingRunListPayload["runs"][number], lang: "zh" | "en") {
  const recordCount = sourceCollectionRunRecordCount(run);
  const candidateCount = sourceCollectionRunCandidateMetric(run);
  const title = sourceCollectionRunTitleLabel(run.title, lang);
  return lang === "zh"
    ? `${sourceCollectionRunLabel(run.runId)} · ${title} · ${recordCount} 条资料 / ${candidateCount} 候选`
    : `${sourceCollectionRunLabel(run.runId)} · ${title} · ${recordCount} records / ${candidateCount} candidates`;
}

export function deriveSourceCollectionDisplayState(input: SourceCollectionDisplayInput): SourceCollectionDisplayState {
  const materialCount = Math.max(0, input.rawRecordCount || 0, input.candidateCount || 0);
  const zh = input.lang === "zh";
  const runningSummary = input.activeWorkSummary?.trim();
  const state = (
    phase: SourceCollectionDisplayPhase,
    consoleState: SourceCollectionStepState,
    searchStepState: SourceCollectionStepState,
    statusText: string,
    decisionText: string,
    active = false,
  ): SourceCollectionDisplayState => ({ phase, active, consoleState, searchStepState, statusText, decisionText });

  if (input.failed) {
    return state(
      "failed",
      "failed",
      "failed",
      zh ? "处理失败" : "Failed",
      zh ? "处理失败，先查看下方失败步骤，再重试当前按钮。" : "A step failed. Review the failed step below, then retry its action.",
    );
  }
  if (input.searchPending || input.backgroundActive) {
    return state(
      "running",
      "active",
      "active",
      zh ? "正在团队搜索" : "Team search running",
      runningSummary || (zh ? "后台资料搜索正在运行，记录和候选会按批刷新。" : "Background source collection is running; records and candidates refresh in batches."),
      true,
    );
  }
  if (input.startPending) {
    return state(
      "starting",
      "active",
      "active",
      zh ? "正在启动搜集" : "Starting collection",
      zh ? "正在创建本轮查询计划、团队 Agent 分工和后台搜索任务。" : "Creating the query plan, team-agent assignments, and background search work.",
      true,
    );
  }
  if (input.recordOutputPending || input.extractionPending) {
    return state(
      "writing",
      "active",
      materialCount > 0 ? "done" : "active",
      input.recordOutputPending ? (zh ? "正在写入候选" : "Writing candidates") : (zh ? "正在提炼资料" : "Extracting sources"),
      zh ? "正在把资料记录提炼为候选资料。" : "Data records are being converted into candidate sources.",
      true,
    );
  }
  if (input.sourceQualityPending) {
    return state(
      "screening",
      "active",
      "done",
      zh ? "正在筛选资料" : "Screening sources",
      zh ? "资料提炼 Agent 正在复核候选资料。" : "The source extraction Agent is reviewing candidate sources.",
      true,
    );
  }
  if (input.graphPending || input.knowledgeIngestionPending) {
    return state(
      "ingesting",
      "active",
      "done",
      input.graphPending ? (zh ? "正在生成入库关系图" : "Building ingestion map") : (zh ? "正在等待管理员审核" : "Waiting for admin review"),
      zh ? "资料已通过搜集阶段，正在准备入库链路。" : "Source collection is ready; the ingestion path is being prepared.",
      true,
    );
  }
  if (!input.hasRun) {
    return state(
      "idle",
      "idle",
      "idle",
      zh ? "未开始" : "Not started",
      zh ? "点击开始搜集，生成本轮搜索任务和存储目录。" : "Start collection to create the search work and storage folder.",
    );
  }
  if (input.searchOpenAssignmentCount > 0) {
    return state(
      "needs_continue",
      "pending",
      "pending",
      materialCount > 0 ? (zh ? "已返回一批" : "Batch returned") : (zh ? "需补充资料" : "More sources needed"),
      materialCount > 0
        ? (zh
          ? `已返回 ${materialCount} 条资料，还有 ${input.searchOpenAssignmentCount} 个搜索任务可继续。`
          : `${materialCount} sources have returned; ${input.searchOpenAssignmentCount} search assignments can continue.`)
        : (zh
          ? `还有 ${input.searchOpenAssignmentCount} 个搜索任务未完成，点击搜索下一批推进。`
          : `${input.searchOpenAssignmentCount} search assignments remain. Run the next search to proceed.`),
    );
  }
  if (input.downstreamOpenAssignmentCount > 0) {
    return state(
      "needs_downstream",
      "pending",
      materialCount > 0 ? "done" : "pending",
      zh ? "待提炼/审查" : "Extraction or review pending",
      zh
        ? `搜索已停止，还有 ${input.downstreamOpenAssignmentCount} 个后续任务等待提炼或筛选。`
        : `Search is idle; ${input.downstreamOpenAssignmentCount} downstream tasks wait for extraction or screening.`,
    );
  }
  if (input.pendingScreeningCount > 0) {
    return state(
      "needs_screening",
      "pending",
      materialCount > 0 ? "done" : "pending",
      zh ? "待审查资料" : "Needs review",
      zh ? "候选资料已到位，下一步执行资料提炼复核。" : "Candidate sources are ready. Run extraction review next.",
    );
  }
  if (input.candidateCount > 0) {
    return state(
      "ready_for_experiment",
      "done",
      "done",
      zh ? "可进入实验" : "Ready for experiment",
      zh ? "资料链路已具备，可进入实验规划或继续补充资料。" : "The source chain is ready. Move to experiment planning or collect more.",
    );
  }
  return state(
    "waiting_for_writeback",
    "pending",
    materialCount > 0 ? "done" : "pending",
    zh ? "待回写" : "Waiting for writeback",
    zh ? "等待 Agent 回写搜集结果。" : "Waiting for agent writeback.",
  );
}

export function sourceCollectionActiveWorkRunFromRuntime(
  runtime: RuntimeSummary | null | undefined,
  runId: string,
): WorkRunSnapshot | null {
  const activeItems = runtime?.workRuns?.activeItems?.source_collection_run ?? [];
  const active = runtime?.workRuns?.active as unknown as Record<string, WorkRunSnapshot | null | undefined> | undefined;
  const candidates = [
    ...activeItems,
    active?.source_collection_run,
  ].filter((item): item is WorkRunSnapshot => Boolean(item));
  const normalizedRunId = String(runId || "").trim();
  return candidates.find((item) => {
    const status = String(item.status || "").toLowerCase();
    if (status !== "queued" && status !== "running") {
      return false;
    }
    return !normalizedRunId || String(item.runId || "") === normalizedRunId;
  }) ?? null;
}
