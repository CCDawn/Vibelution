/**
 * R2-b: Source-collection overview summary/stats/plan bags for research surfaces.
 */
import type {
  DataProcessingCollectionOutputPayload,
  TeamWorkflowSourceCollectionRunStartPayload,
} from "../../api/types";
import type {
  TeamSourceCollectionOverviewPlan,
  TeamSourceCollectionOverviewResult,
  TeamSourceCollectionOverviewStat,
} from "../TeamSourceCollectionOverviewPanel";
import {
  sourceCollectionPromptCacheStatusLabel,
} from "./source-collection/presentationModel";
import { sourceCollectionRunLabel } from "./source-collection/runModel";

export type BuildSourceCollectionOverviewBagArgs = {
  lang: "zh" | "en";
  selectedSourceCollectionRun: { runId?: string; status?: string } | null | undefined;
  sourceCollectionRunsQueryPending: boolean;
  sourceCollectionCollectedRunSummaryText: string;
  sourceCollectionAssignmentRunSummaryText: string;
  sourceCollectionRunStatus: { runStatus?: string } | null | undefined;
  sourceCollectionCollectedCountText: string;
  sourceCollectionSearchOpenAssignmentCountText: string;
  sourceCollectionDownstreamOpenAssignmentCountText: string;
  sourceCollectionQueryCountText: string;
  sourceCollectionPromptCacheStatus: string;
  sourceCollectionPromptCacheMode: string | null | undefined;
  selectedTeamStartSourceCollectionResult: TeamWorkflowSourceCollectionRunStartPayload | null | undefined;
  sourceCollectionAssignmentsQueryPending: boolean;
  selectedTeamStartSourceCollectionError: { message?: string } | null | undefined;
  selectedTeamRecordSourceCollectionOutputError: { message?: string } | null | undefined;
  selectedTeamRecordSourceCollectionOutputResult: {
    output: DataProcessingCollectionOutputPayload;
    imported: unknown[];
  } | null | undefined;
};

export function buildSourceCollectionOverviewBag(args: BuildSourceCollectionOverviewBagArgs) {
  const lang = args.lang;
  const sourceCollectionOverviewSummary = args.selectedSourceCollectionRun
    ? `${sourceCollectionRunLabel(String(args.selectedSourceCollectionRun.runId || ""))} · ${args.sourceCollectionCollectedRunSummaryText} / ${args.sourceCollectionAssignmentRunSummaryText}`
    : args.sourceCollectionRunsQueryPending
      ? (lang === "zh" ? "读取批次中" : "loading runs")
      : (lang === "zh" ? "等待启动批次" : "waiting for run");
  const sourceCollectionOverviewStatus =
    args.sourceCollectionRunStatus?.runStatus || args.selectedSourceCollectionRun?.status || "";
  const sourceCollectionOverviewStats: TeamSourceCollectionOverviewStat[] = [
    { key: "records", label: lang === "zh" ? "资料" : "records", value: args.sourceCollectionCollectedCountText },
    { key: "search", label: lang === "zh" ? "可搜索" : "search", value: args.sourceCollectionSearchOpenAssignmentCountText },
    { key: "next", label: lang === "zh" ? "后续" : "next work", value: args.sourceCollectionDownstreamOpenAssignmentCountText },
    { key: "queries", label: lang === "zh" ? "搜索问题" : "queries", value: args.sourceCollectionQueryCountText },
    {
      key: "prompt-cache",
      label: "KV",
      value: `${sourceCollectionPromptCacheStatusLabel(args.sourceCollectionPromptCacheStatus, lang)}${args.sourceCollectionPromptCacheMode ? ` · ${args.sourceCollectionPromptCacheMode}` : ""}`,
    },
  ];
  const sourceCollectionStartResult = args.selectedTeamStartSourceCollectionResult;
  const sourceCollectionOverviewPlan: TeamSourceCollectionOverviewPlan | null = sourceCollectionStartResult ? {
    planId: sourceCollectionStartResult.searchPlan.planId,
    seeds: sourceCollectionStartResult.searchPlan.querySeeds.join(" / "),
    promptCache: `${sourceCollectionPromptCacheStatusLabel(sourceCollectionStartResult.promptCachePolicy.gate.status, lang)} · ${sourceCollectionStartResult.promptCachePolicy.promptCacheMode}`,
    boundary: lang === "zh" ? "不触发外部搜索，不写正式知识/RAG/图谱" : "No external search, formal Knowledge/RAG/Graph writes off",
  } : null;
  const sourceCollectionOverviewAssignmentEmptyMessage = args.sourceCollectionAssignmentsQueryPending
    ? (lang === "zh" ? "正在读取功能 Agent assignment..." : "Loading functional Agent assignments...")
    : (lang === "zh" ? "启动批次后会生成资料寻找、资料提炼、资料关系整理和资料入库任务。" : "Starting a run will create source finding, extraction, relation mapping, and ingestion assignments.");
  const sourceCollectionOverviewBoundaryItems = [
    lang === "zh" ? "执行器：手动/Agent 均可提交 CollectionOutput" : "Executor: manual or Agent CollectionOutput",
    lang === "zh" ? "正式知识写入关闭" : "formal knowledge write off",
    lang === "zh" ? "进入候选仓库后再筛选" : "screen after candidate import",
  ];
  const sourceCollectionOverviewErrors = [
    args.selectedTeamStartSourceCollectionError?.message,
    args.selectedTeamRecordSourceCollectionOutputError?.message,
  ].filter((message): message is string => Boolean(message));
  const sourceCollectionOutputResult = args.selectedTeamRecordSourceCollectionOutputResult;
  const sourceCollectionOverviewResult: TeamSourceCollectionOverviewResult | null = sourceCollectionOutputResult ? {
    title: lang === "zh" ? "已回写" : "Written",
    detail: `${sourceCollectionOutputResult.output.createdRecords.length} DataRecord / ${sourceCollectionOutputResult.imported.length} candidate`,
  } : null;

  return {
    sourceCollectionOverviewSummary,
    sourceCollectionOverviewStatus,
    sourceCollectionOverviewStats,
    sourceCollectionOverviewPlan,
    sourceCollectionOverviewAssignmentEmptyMessage,
    sourceCollectionOverviewBoundaryItems,
    sourceCollectionOverviewErrors,
    sourceCollectionOverviewResult,
  };
}
