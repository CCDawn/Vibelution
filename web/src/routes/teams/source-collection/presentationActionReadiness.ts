/**
 * F3 — pure stage action readiness + button labels for SC presentation.
 * Edit copy / disable rules here; keep the hook as wiring only.
 */
import { RESEARCH_STAGE_TERMS } from "../research-workflow/researchTerminology";
import { sourceCollectionActionReadinessOf } from "./actionChrome";
import type { SourceCollectionActionReadiness } from "./stageProjection";

export type SourceCollectionActionChromeReasons = {
  actionLoadingReason: string;
  actionErrorReason: string;
  actionNoRunReason: string;
  actionNoInputReason: string;
  actionBusyReason: string;
};

export type SourceCollectionActionReadinessInput = {
  lang: "zh" | "en";
  reasons: SourceCollectionActionChromeReasons;
  loadingText: string;
  hasTeam: boolean;
  hasRun: boolean;
  actionRunId: string;
  canExecuteSearch: boolean;
  canStart: boolean;
  canBuildGraph: boolean;
  assignmentsDataLoading: boolean;
  recordsDataLoading: boolean;
  primaryDataLoading: boolean;
  sourceQualityLoading: boolean;
  graphDataLoading: boolean;
  knowledgeIngestionDataLoading: boolean;
  actionInitialDataPending: boolean;
  actionDataError: boolean;
  sourceQualityDataError: boolean;
  graphDataError: boolean;
  knowledgeIngestionDataError: boolean;
  rawRecordCount: number;
  displayedCandidateCount: number;
  runPendingScreeningCount: number;
  runPendingScreeningCountText: string;
  pendingCandidateImportCount: number;
  searchOpenAssignmentCount: number;
  ingestCandidateCount: number;
  precheckCandidateCount: number;
  runApprovedCount: number;
  acceptedBackgroundActive: boolean;
  operationFailed: boolean;
  extractionNeedsAgentMaterial: boolean;
  searchPending: boolean;
  extractPending: boolean;
  sourceQualityPending: boolean;
  graphPending: boolean;
  knowledgeIngestPending: boolean;
  startRunPending: boolean;
  knowledgeCompletedForSelectedRun: boolean;
};

export type SourceCollectionActionReadinessBag = {
  searchActionReadiness: SourceCollectionActionReadiness;
  candidateExtractionActionReadiness: SourceCollectionActionReadiness;
  screeningActionReadiness: SourceCollectionActionReadiness;
  graphActionReadiness: SourceCollectionActionReadiness;
  memoryActionReadiness: SourceCollectionActionReadiness;
  completionActionReadiness: SourceCollectionActionReadiness;
  loopStartReadiness: SourceCollectionActionReadiness;
  loopActionReadiness: SourceCollectionActionReadiness;
  loopStartsNewRun: boolean;
  memoryActionDisabled: boolean;
  memoryActionLabel: string;
  completionActionDisabled: boolean;
  completionActionLabel: string;
  loopActionDisabled: boolean;
  loopActionLabel: string;
  graphActionDisabled: boolean;
  graphActionLabel: string;
  screeningDisabled: boolean;
  screeningForceRescreen: boolean;
  screeningButtonText: string;
  screeningButtonTitle: string;
  screeningStatusText: string;
  candidateExtractionButtonText: string;
};

const ready = sourceCollectionActionReadinessOf;

export function buildSourceCollectionActionReadinessBag(
  input: SourceCollectionActionReadinessInput,
): SourceCollectionActionReadinessBag {
  const {
    lang,
    reasons,
    loadingText,
    hasTeam,
    hasRun,
    actionRunId,
    canExecuteSearch,
    canStart,
    canBuildGraph,
    assignmentsDataLoading,
    recordsDataLoading,
    primaryDataLoading,
    sourceQualityLoading,
    graphDataLoading,
    knowledgeIngestionDataLoading,
    actionInitialDataPending,
    actionDataError,
    sourceQualityDataError,
    graphDataError,
    knowledgeIngestionDataError,
    rawRecordCount,
    displayedCandidateCount,
    runPendingScreeningCount,
    runPendingScreeningCountText,
    pendingCandidateImportCount,
    searchOpenAssignmentCount,
    ingestCandidateCount,
    precheckCandidateCount,
    runApprovedCount,
    acceptedBackgroundActive,
    operationFailed,
    extractionNeedsAgentMaterial,
    searchPending,
    extractPending,
    sourceQualityPending,
    graphPending,
    knowledgeIngestPending,
    startRunPending,
    knowledgeCompletedForSelectedRun,
  } = input;

  const {
    actionLoadingReason,
    actionErrorReason,
    actionNoRunReason,
    actionNoInputReason,
    actionBusyReason,
  } = reasons;

  const searchActionReadiness = ready(
    !canExecuteSearch,
    !hasTeam || !hasRun
      ? actionNoRunReason
      : assignmentsDataLoading
        ? actionLoadingReason
        : actionDataError
          ? actionErrorReason
          : searchPending || acceptedBackgroundActive
            ? actionBusyReason
            : actionNoInputReason,
    assignmentsDataLoading,
  );
  const candidateExtractionActionReadiness = ready(
    !hasTeam
      || !hasRun
      || recordsDataLoading
      || actionDataError
      || rawRecordCount <= 0
      || extractPending,
    !hasTeam || !hasRun
      ? actionNoRunReason
      : recordsDataLoading
        ? actionLoadingReason
        : actionDataError
          ? actionErrorReason
          : extractPending
            ? actionBusyReason
            : actionNoInputReason,
    recordsDataLoading,
  );
  const screeningActionReadiness = ready(
    !hasTeam
      || primaryDataLoading
      || sourceQualityLoading
      || actionDataError
      || sourceQualityDataError
      || displayedCandidateCount <= 0
      || sourceQualityPending,
    !hasTeam
      ? actionNoRunReason
      : primaryDataLoading || sourceQualityLoading
        ? actionLoadingReason
        : actionDataError || sourceQualityDataError
          ? actionErrorReason
          : sourceQualityPending
            ? actionBusyReason
            : actionNoInputReason,
    primaryDataLoading || sourceQualityLoading,
  );
  const graphActionReadiness = ready(
    !hasTeam
      || primaryDataLoading
      || graphDataLoading
      || actionDataError
      || graphDataError
      || !canBuildGraph
      || graphPending,
    !hasTeam
      ? actionNoRunReason
      : primaryDataLoading || graphDataLoading
        ? actionLoadingReason
        : actionDataError || graphDataError
          ? actionErrorReason
          : graphPending
            ? actionBusyReason
            : actionNoInputReason,
    primaryDataLoading || graphDataLoading,
  );
  const memoryActionReadiness = ready(
    !hasTeam
      || primaryDataLoading
      || sourceQualityLoading
      || knowledgeIngestionDataLoading
      || actionDataError
      || sourceQualityDataError
      || knowledgeIngestionDataError
      || ingestCandidateCount <= 0
      || knowledgeIngestPending,
    !hasTeam
      ? actionNoRunReason
      : primaryDataLoading || sourceQualityLoading || knowledgeIngestionDataLoading
        ? actionLoadingReason
        : actionDataError || sourceQualityDataError || knowledgeIngestionDataError
          ? actionErrorReason
          : knowledgeIngestPending
            ? actionBusyReason
            : actionNoInputReason,
    primaryDataLoading || sourceQualityLoading || knowledgeIngestionDataLoading,
  );
  const completionActionReadiness = ready(
    !hasTeam
      || !actionRunId
      || actionInitialDataPending
      || actionDataError
      || sourceQualityDataError
      || graphDataError
      || knowledgeIngestionDataError
      || (ingestCandidateCount <= 0 && rawRecordCount <= 0 && searchOpenAssignmentCount <= 0)
      || knowledgeIngestPending,
    !hasTeam || !actionRunId
      ? actionNoRunReason
      : actionInitialDataPending
        ? actionLoadingReason
        : actionDataError || sourceQualityDataError || graphDataError || knowledgeIngestionDataError
          ? actionErrorReason
          : knowledgeIngestPending
            ? actionBusyReason
            : actionNoInputReason,
    actionInitialDataPending,
  );
  const loopStartsNewRun = !hasRun || knowledgeCompletedForSelectedRun;
  const loopStartReadiness = ready(
    !hasTeam
      || startRunPending
      || knowledgeIngestPending
      || !canStart,
    !hasTeam
      ? actionNoRunReason
      : startRunPending || knowledgeIngestPending
        ? actionBusyReason
        : actionNoInputReason,
  );
  const loopActionReadiness = loopStartsNewRun
    ? loopStartReadiness
    : completionActionReadiness;

  const memoryActionDisabled = memoryActionReadiness.disabled;
  const memoryActionLabel = memoryActionDisabled && memoryActionReadiness.loading
    ? (lang === "zh" ? "读取中" : "Loading")
    : knowledgeIngestPending
      ? (lang === "zh" ? "通知入库 Agent 中" : "Notifying ingestion Agent")
      : precheckCandidateCount > 0
        ? (lang === "zh" ? "通知资料入库 Agent" : "Notify source ingestion Agent")
        : displayedCandidateCount > 0
          ? (lang === "zh" ? "提炼后通知入库 Agent" : "Extract and notify ingestion Agent")
          : (lang === "zh" ? "通知资料入库 Agent" : "Notify source ingestion Agent");
  const completionActionDisabled = completionActionReadiness.disabled;
  const completionActionLabel = knowledgeIngestPending
    ? (lang === "zh" ? "一键完成中" : "Completing")
    : (lang === "zh" ? `一键完成${RESEARCH_STAGE_TERMS.knowledge_collection.zh}` : "Complete knowledge collection");
  const loopActionDisabled = loopActionReadiness.disabled;
  const loopActionLabel = startRunPending || knowledgeIngestPending
    ? (lang === "zh" ? "闭环执行中" : "Loop running")
    : loopStartsNewRun
      ? knowledgeCompletedForSelectedRun && hasRun
        ? (lang === "zh" ? "开始下一轮闭环" : "Start next loop")
        : (lang === "zh" ? "开始第一轮闭环" : "Start first loop")
      : operationFailed
        ? (lang === "zh" ? "重试本轮闭环" : "Retry this loop")
        : (lang === "zh" ? "继续本轮闭环" : "Continue this loop");
  const graphActionDisabled = graphActionReadiness.disabled;
  const graphActionLabel = graphPending
    ? (lang === "zh" ? "Agent 生成中" : "Agent building")
    : runApprovedCount > 0
      ? (lang === "zh" ? "Agent 生成关系图" : "Agent build map")
      : displayedCandidateCount > 0
        ? (lang === "zh" ? "审查并生成关系图" : "Review and build map")
        : (lang === "zh" ? "Agent 生成关系图" : "Agent build map");
  const screeningDisabled = screeningActionReadiness.disabled;
  const screeningForceRescreen = runPendingScreeningCount <= 0 && displayedCandidateCount > 0;
  const screeningButtonText = sourceQualityPending
    ? (lang === "zh" ? "质量审查中" : "Reviewing quality")
    : runPendingScreeningCount > 0
      ? (lang === "zh" ? "Agent 质量审查" : "Agent quality review")
      : screeningForceRescreen
        ? (lang === "zh" ? "重新质量审查" : "Re-run quality review")
        : (lang === "zh" ? "Agent 质量审查" : "Agent quality review");
  const screeningButtonTitle = sourceQualityPending
    ? (lang === "zh" ? "资料提炼 Agent 正在按现有材料重新打分" : "Source Extractor is re-scoring with current materials")
    : screeningForceRescreen
      ? (lang === "zh"
        ? "仅重新质量打分，不会自动补全文/DOI/证据锚点。列表「待补资料」需先补充材料再审查，否则结果仍可能是待补。"
        : "Re-scores only; does not auto-fill full text/DOI/anchors. Repair needs-revision sources first or they stay blocked.")
      : (lang === "zh"
        ? "对尚未审查的候选做来源质量打分（通过 / 待补 / 排除）。"
        : "Score pending candidates (approved / needs revision / rejected).");
  const screeningStatusText = sourceQualityPending
    ? (lang === "zh" ? "进行中" : "running")
    : primaryDataLoading
      ? loadingText
      : runPendingScreeningCount > 0
        ? `${runPendingScreeningCountText} ${lang === "zh" ? "待质量审查" : "pending quality review"}`
        : extractionNeedsAgentMaterial
          ? (lang === "zh" ? "有待补资料：先补材料再审查" : "needs material first")
          : displayedCandidateCount > 0
            ? (lang === "zh" ? "已审查" : "done")
            : (lang === "zh" ? "暂无候选" : "no candidates");
  const candidateExtractionButtonText = extractPending
    ? (lang === "zh" ? "Agent 提炼中" : "Agent extracting")
    : pendingCandidateImportCount > 0
      ? (lang === "zh" ? "Agent 提炼资料" : "Agent extract")
      : displayedCandidateCount > 0
        ? (lang === "zh" ? "Agent 重新提炼" : "Agent re-extract")
        : (lang === "zh" ? "Agent 提炼资料" : "Agent extract");

  return {
    searchActionReadiness,
    candidateExtractionActionReadiness,
    screeningActionReadiness,
    graphActionReadiness,
    memoryActionReadiness,
    completionActionReadiness,
    loopStartReadiness,
    loopActionReadiness,
    loopStartsNewRun,
    memoryActionDisabled,
    memoryActionLabel,
    completionActionDisabled,
    completionActionLabel,
    loopActionDisabled,
    loopActionLabel,
    graphActionDisabled,
    graphActionLabel,
    screeningDisabled,
    screeningForceRescreen,
    screeningButtonText,
    screeningButtonTitle,
    screeningStatusText,
    candidateExtractionButtonText,
  };
}
