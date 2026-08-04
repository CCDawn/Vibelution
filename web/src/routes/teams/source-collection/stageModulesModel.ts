/**
 * Source-collection stage module descriptors (board / standalone / completion flow).
 * Pure presentation factory; action handlers are injected from TeamsRoute.
 */
import type { TeamSourceCollectionStandaloneStageModule } from "../../TeamSourceCollectionStandaloneStagePanel";
import type { TeamWorkflowKnowledgeIngestionWorkRun } from "../../../api/types";
import { SOURCE_COLLECTION_STAGE_AGENT_KEYS } from "../teamSourceCollectionShellModel";
import type { SourceCollectionStepState } from "./runModel";
import type {
  SourceCollectionActionReadiness,
  SourceCollectionStageCardProjection,
  SourceCollectionStageModuleId,
} from "./stageProjection";

export type SourceCollectionStageModule = {
  id: SourceCollectionStageModuleId;
  label: string;
  metric: string;
  summary: string;
  inputLabel: string;
  outputLabel: string;
  nextLabel: string;
  state: SourceCollectionStepState;
  status: string;
  detailLabel: string;
  actionLabel: string;
  actionDisabled: boolean;
  actionTone: "primary" | "secondary";
  actionIcon: "play" | "search" | "check" | "archive" | "refresh";
  projection?: SourceCollectionStageCardProjection | null;
  onAction: () => void;
  onDetail: () => void;
};

export type SourceCollectionCompletionFlowNode = NonNullable<
  TeamWorkflowKnowledgeIngestionWorkRun["flowVisualization"]
>["nodes"][number];

export type BuildSourceCollectionStageModulesInput = {
  lang: "zh" | "en";
  selectedSourceCollectionRun: { runId?: string } | null | undefined;
  selectedSourceCollectionStageId: SourceCollectionStageModuleId;
  sourceCollectionProjectedCollectedCountLabel: string;
  sourceCollectionProjectedCollectedCountText: string;
  sourceCollectionProjectedAssessedCountText: string;
  sourceCollectionProjectedApprovedCountText: string;
  sourceCollectionProjectedCandidateCountLabel: string;
  sourceCollectionProjectedCandidateCountText: string;
  sourceCollectionCurrentCandidateCountText: string;
  sourceCollectionQueryCountLabel: string;
  sourceCollectionQueryCountText: string;
  sourceCollectionSearchOpenAssignmentCount: number;
  sourceCollectionPrimaryDataLoading: boolean;
  sourceCollectionFindingDisplayLoading: boolean;
  sourceCollectionExtractionDisplayLoading: boolean;
  sourceCollectionRelationsDisplayLoading: boolean;
  sourceCollectionIngestionDisplayLoading: boolean;
  sourceCollectionScreeningDataLoading: boolean;
  sourceCollectionLoadingSummary: string;
  sourceCollectionDataSyncText: string;
  sourceCollectionSourceSyncStatusText: string;
  sourceCollectionCandidateSyncStatusText: string;
  sourceCollectionCollectionProjection: SourceCollectionStageCardProjection | null;
  sourceCollectionExtractionProjection: SourceCollectionStageCardProjection | null;
  sourceCollectionGraphProjection: SourceCollectionStageCardProjection | null;
  sourceCollectionMemoryProjection: SourceCollectionStageCardProjection | null;
  sourceCollectionFindingDisplayState: SourceCollectionStepState;
  sourceCollectionExtractionDisplayState: SourceCollectionStepState;
  sourceCollectionRelationsDisplayState: SourceCollectionStepState;
  sourceCollectionIngestionDisplayState: SourceCollectionStepState;
  sourceCollectionSearchStepState: SourceCollectionStepState;
  sourceCollectionExtractionStepState: SourceCollectionStepState;
  sourceCollectionGraphStepState: SourceCollectionStepState;
  sourceCollectionMemoryStepState: SourceCollectionStepState;
  sourceCollectionExtractionNeedsAgentMaterial: boolean;
  sourceCollectionExtractionAgentMaterialCount: number;
  sourceCollectionExtractionCanProceedAfterExclusions: boolean;
  sourceCollectionExtractionProceedableSummary: string;
  sourceCollectionExtractionExcludedRecoveryState: {
    excludedCount: number;
    statusLabel: string;
    primaryActionText: string;
  };
  sourceCollectionExtractionLoadingMetric: string;
  sourceCollectionExtractionMaterialMetric: string;
  sourceCollectionExtractionLoadingOutputLabel: string;
  sourceCollectionDisplayedCandidateCount: number;
  sourceCollectionRunPendingScreeningCount: number;
  sourceCollectionRunPendingScreeningCountText: string;
  sourceCollectionProjectedGraphNodeCount: number | string;
  sourceCollectionProjectedGraphEdgeCount: number | string;
  sourceCollectionProjectedFormalKnowledgeCount: number | string;
  sourceCollectionProjectedStewardPackCount: number;
  sourceCollectionPrecheckCandidateCount: number;
  knowledgePendingReviewCount: number;
  sourceCollectionIngestionReadyForExperiment: boolean;
  sourceCollectionCollectionActionLabel: string;
  sourceCollectionCandidateExtractionButtonText: string;
  sourceCollectionGraphActionLabel: string;
  sourceCollectionMemoryActionLabel: string;
  selectedTeamExtractSourceCollectionCandidatesPending: boolean;
  selectedTeamSourceQualityPending: boolean;
  sourceCollectionExperimentPlanningRoute: string;
  sourceCollectionStageFocusLabel: string;
  selectedTeamKnowledgeCollectionWorkRun: TeamWorkflowKnowledgeIngestionWorkRun | null | undefined;
  sourceCollectionStageLaunchActive: (stageId: SourceCollectionStageModuleId) => boolean;
  sourceCollectionStageLaunchSummary: (stageId: SourceCollectionStageModuleId) => string;
  sourceCollectionStageUserSummary: (
    projection: SourceCollectionStageCardProjection | null | undefined,
    lang: "zh" | "en",
  ) => string;
  sourceCollectionStageDisplayState: (
    stageId: SourceCollectionStageModuleId,
    fallback: SourceCollectionStepState,
  ) => SourceCollectionStepState;
  sourceCollectionStageDisplayStatus: (stageId: SourceCollectionStageModuleId, fallback: string) => string;
  sourceCollectionStepStatusText: (state: SourceCollectionStepState) => string;
  sourceCollectionStageActionLabelFor: (stageId: SourceCollectionStageModuleId, fallback: string) => string;
  sourceCollectionStageActionReadinessFor: (stageId: SourceCollectionStageModuleId) => SourceCollectionActionReadiness;
  sourceCollectionActionDisabledTitle: (readiness: SourceCollectionActionReadiness, fallback: string) => string;
  startSourceCollectionStageSessionTask: (stageId: SourceCollectionStageModuleId) => void | Promise<void>;
  openSourceCollectionStage: (stageId: SourceCollectionStageModuleId) => void;
  openSourceCollectionStageAgentChat: (stageId: SourceCollectionStageModuleId) => void | Promise<void>;
  navigate: (to: string) => void;
};

export function buildSourceCollectionStageModules(
  input: BuildSourceCollectionStageModulesInput,
): SourceCollectionStageModule[] {
  const {
    lang,
    selectedSourceCollectionRun,
    sourceCollectionProjectedCollectedCountLabel,
    sourceCollectionProjectedCollectedCountText,
    sourceCollectionProjectedAssessedCountText,
    sourceCollectionProjectedApprovedCountText,
    sourceCollectionProjectedCandidateCountLabel,
    sourceCollectionProjectedCandidateCountText,
    sourceCollectionCurrentCandidateCountText,
    sourceCollectionQueryCountLabel,
    sourceCollectionQueryCountText,
    sourceCollectionSearchOpenAssignmentCount,
    sourceCollectionPrimaryDataLoading,
    sourceCollectionFindingDisplayLoading,
    sourceCollectionExtractionDisplayLoading,
    sourceCollectionRelationsDisplayLoading,
    sourceCollectionIngestionDisplayLoading,
    sourceCollectionScreeningDataLoading,
    sourceCollectionLoadingSummary,
    sourceCollectionDataSyncText,
    sourceCollectionSourceSyncStatusText,
    sourceCollectionCandidateSyncStatusText,
    sourceCollectionCollectionProjection,
    sourceCollectionExtractionProjection,
    sourceCollectionGraphProjection,
    sourceCollectionMemoryProjection,
    sourceCollectionFindingDisplayState,
    sourceCollectionExtractionDisplayState,
    sourceCollectionRelationsDisplayState,
    sourceCollectionIngestionDisplayState,
    sourceCollectionSearchStepState,
    sourceCollectionExtractionStepState,
    sourceCollectionGraphStepState,
    sourceCollectionMemoryStepState,
    sourceCollectionExtractionNeedsAgentMaterial,
    sourceCollectionExtractionAgentMaterialCount,
    sourceCollectionExtractionCanProceedAfterExclusions,
    sourceCollectionExtractionProceedableSummary,
    sourceCollectionExtractionExcludedRecoveryState,
    sourceCollectionExtractionLoadingMetric,
    sourceCollectionExtractionMaterialMetric,
    sourceCollectionExtractionLoadingOutputLabel,
    sourceCollectionDisplayedCandidateCount,
    sourceCollectionRunPendingScreeningCount,
    sourceCollectionRunPendingScreeningCountText,
    sourceCollectionProjectedGraphNodeCount,
    sourceCollectionProjectedGraphEdgeCount,
    sourceCollectionProjectedFormalKnowledgeCount,
    sourceCollectionProjectedStewardPackCount,
    sourceCollectionPrecheckCandidateCount,
    knowledgePendingReviewCount,
    sourceCollectionIngestionReadyForExperiment,
    sourceCollectionCollectionActionLabel,
    sourceCollectionCandidateExtractionButtonText,
    sourceCollectionGraphActionLabel,
    sourceCollectionMemoryActionLabel,
    selectedTeamExtractSourceCollectionCandidatesPending,
    selectedTeamSourceQualityPending,
    sourceCollectionExperimentPlanningRoute,
    sourceCollectionStageLaunchActive,
    sourceCollectionStageLaunchSummary,
    sourceCollectionStageUserSummary,
    sourceCollectionStageDisplayState,
    sourceCollectionStageDisplayStatus,
    sourceCollectionStepStatusText,
    sourceCollectionStageActionLabelFor,
    sourceCollectionStageActionReadinessFor,
    startSourceCollectionStageSessionTask,
    openSourceCollectionStage,
    openSourceCollectionStageAgentChat,
    navigate,
  } = input;

const sourceCollectionStageModules: SourceCollectionStageModule[] = [
  {
    id: "finding",
    label: lang === "zh" ? "找资料" : "Find",
    metric: lang === "zh" ? `原始资料 ${sourceCollectionProjectedCollectedCountLabel}` : sourceCollectionProjectedCollectedCountLabel,
    summary: sourceCollectionStageLaunchActive("finding")
      ? sourceCollectionStageLaunchSummary("finding")
      : sourceCollectionFindingDisplayLoading
      ? (lang === "zh" ? "正在读取资料结果" : "Loading source results")
      : sourceCollectionStageUserSummary(sourceCollectionCollectionProjection, lang) || (!selectedSourceCollectionRun
      ? (lang === "zh" ? "点击开始生成本轮任务" : "Start to create this run")
      : sourceCollectionSearchOpenAssignmentCount > 0
        ? (lang === "zh" ? `${sourceCollectionSearchOpenAssignmentCount} 个搜索任务待执行` : `${sourceCollectionSearchOpenAssignmentCount} search tasks remain`)
        : sourceCollectionPrimaryDataLoading
          ? (lang === "zh" ? "正在读取资料结果" : "Loading source results")
          : (lang === "zh" ? `已找到 ${sourceCollectionProjectedCollectedCountText} 条资料` : `${sourceCollectionProjectedCollectedCountText} sources found`)),
    inputLabel: lang === "zh" ? `${sourceCollectionQueryCountLabel} 搜索问题` : `${sourceCollectionQueryCountText} queries`,
    outputLabel: lang === "zh" ? `${sourceCollectionProjectedCollectedCountLabel} 原始资料` : sourceCollectionProjectedCollectedCountLabel,
    nextLabel: sourceCollectionSearchOpenAssignmentCount > 0
      ? (lang === "zh" ? "继续寻找资料" : "Continue finding")
      : (lang === "zh" ? "进入资料提炼" : "Move to extraction"),
    state: sourceCollectionStageDisplayState("finding", sourceCollectionFindingDisplayState),
    status: sourceCollectionStageDisplayStatus("finding", sourceCollectionFindingDisplayLoading ? sourceCollectionSourceSyncStatusText : sourceCollectionStepStatusText(sourceCollectionSearchStepState)),
    detailLabel: lang === "zh" ? "查看资料记录" : "View source records",
    actionLabel: sourceCollectionStageActionLabelFor("finding", sourceCollectionCollectionActionLabel),
    actionDisabled: sourceCollectionStageActionReadinessFor("finding").disabled,
    actionTone: "primary",
    actionIcon: selectedSourceCollectionRun && sourceCollectionSearchOpenAssignmentCount > 0 ? "search" : "play",
    projection: sourceCollectionCollectionProjection,
    onAction: () => void startSourceCollectionStageSessionTask("finding"),
    onDetail: () => openSourceCollectionStage("finding"),
  },
  {
    id: "extraction",
    label: lang === "zh" ? "提炼" : "Extract",
    metric: sourceCollectionScreeningDataLoading || sourceCollectionPrimaryDataLoading
      ? sourceCollectionExtractionLoadingMetric
      : sourceCollectionExtractionNeedsAgentMaterial
        ? sourceCollectionExtractionMaterialMetric
      : (lang === "zh" ? `已处理 ${sourceCollectionProjectedAssessedCountText}/${sourceCollectionCurrentCandidateCountText}` : `${sourceCollectionProjectedAssessedCountText}/${sourceCollectionCurrentCandidateCountText} processed`),
    summary: sourceCollectionStageLaunchActive("extraction")
      ? sourceCollectionStageLaunchSummary("extraction")
      : sourceCollectionExtractionDisplayLoading
      ? sourceCollectionLoadingSummary
      : sourceCollectionExtractionCanProceedAfterExclusions
      ? sourceCollectionExtractionProceedableSummary
      : sourceCollectionExtractionNeedsAgentMaterial
      ? (lang === "zh"
        ? `${sourceCollectionExtractionAgentMaterialCount} 条待补：现在只点右侧主按钮补材料，完成后流程会自动切到质量审查。`
        : `${sourceCollectionExtractionAgentMaterialCount} need material: use the right-stage primary button only; review becomes the next recommended step after repair.`)
      : sourceCollectionStageUserSummary(sourceCollectionExtractionProjection, lang) || (sourceCollectionPrimaryDataLoading
      ? sourceCollectionLoadingSummary
      : sourceCollectionDisplayedCandidateCount <= 0
        ? (lang === "zh" ? "等待资料寻找结果" : "Waiting for found sources")
        : sourceCollectionRunPendingScreeningCount > 0
          ? (lang === "zh" ? `${sourceCollectionRunPendingScreeningCountText} 条待继续提炼或审查` : `${sourceCollectionRunPendingScreeningCountText} need extraction or review`)
          : (lang === "zh" ? `${sourceCollectionProjectedApprovedCountText} 条可进入关系整理` : `${sourceCollectionProjectedApprovedCountText} ready for relation mapping`)),
    inputLabel: lang === "zh" ? `${sourceCollectionProjectedCollectedCountLabel} 原始资料` : sourceCollectionProjectedCollectedCountLabel,
    outputLabel: sourceCollectionPrimaryDataLoading || sourceCollectionScreeningDataLoading
      ? sourceCollectionExtractionLoadingOutputLabel
      : sourceCollectionExtractionCanProceedAfterExclusions
        ? (lang === "zh" ? `${sourceCollectionProjectedApprovedCountText} 条保留 / ${sourceCollectionExtractionExcludedRecoveryState.excludedCount} 条已排除` : `${sourceCollectionProjectedApprovedCountText} kept / ${sourceCollectionExtractionExcludedRecoveryState.excludedCount} excluded`)
        : sourceCollectionExtractionNeedsAgentMaterial
          ? (lang === "zh" ? `${sourceCollectionCurrentCandidateCountText} 条已提炼 / ${sourceCollectionExtractionAgentMaterialCount} 条待补材料` : `${sourceCollectionCurrentCandidateCountText} extracted / ${sourceCollectionExtractionAgentMaterialCount} need material`)
        : (lang === "zh" ? `${sourceCollectionProjectedApprovedCountText} 条保留 / ${sourceCollectionRunPendingScreeningCountText} 条待处理` : `${sourceCollectionProjectedApprovedCountText} kept / ${sourceCollectionRunPendingScreeningCountText} pending`),
    nextLabel: sourceCollectionExtractionNeedsAgentMaterial
      ? (lang === "zh" ? "要求 Agent 补充材料" : "Request Agent material supplement")
      : sourceCollectionRunPendingScreeningCount > 0
      ? (lang === "zh" ? "Agent 继续提炼" : "Agent continues extraction")
      : (lang === "zh" ? "进入资料关系整理" : "Move to relation mapping"),
    state: sourceCollectionStageDisplayState("extraction", sourceCollectionExtractionCanProceedAfterExclusions ? "done" : sourceCollectionExtractionDisplayState),
    status: sourceCollectionStageDisplayStatus(
      "extraction",
      sourceCollectionExtractionDisplayLoading
        ? sourceCollectionCandidateSyncStatusText
      : sourceCollectionExtractionCanProceedAfterExclusions
          ? sourceCollectionExtractionExcludedRecoveryState.statusLabel
          : sourceCollectionExtractionNeedsAgentMaterial
            ? (lang === "zh" ? "待补材料" : "material needed")
          : sourceCollectionStepStatusText(sourceCollectionExtractionStepState),
    ),
    detailLabel: lang === "zh" ? "查看提炼结果" : "View extraction details",
    actionLabel: sourceCollectionExtractionCanProceedAfterExclusions
      ? sourceCollectionExtractionExcludedRecoveryState.primaryActionText
      : sourceCollectionExtractionNeedsAgentMaterial
        ? (lang === "zh" ? "要求 Agent 补充材料" : "Request Agent material supplement")
      : sourceCollectionStageActionLabelFor(
        "extraction",
        sourceCollectionDisplayedCandidateCount > 0
          ? (lang === "zh" ? "Agent 提炼资料" : "Agent extract sources")
          : sourceCollectionCandidateExtractionButtonText,
      ),
    actionDisabled: sourceCollectionExtractionCanProceedAfterExclusions ? false : sourceCollectionStageActionReadinessFor("extraction").disabled,
    actionTone: "primary",
    actionIcon: selectedTeamExtractSourceCollectionCandidatesPending || selectedTeamSourceQualityPending ? "refresh" : "archive",
    projection: sourceCollectionExtractionProjection,
    onAction: sourceCollectionExtractionCanProceedAfterExclusions
      ? () => void openSourceCollectionStageAgentChat("extraction")
      : () => void startSourceCollectionStageSessionTask("extraction"),
    onDetail: () => openSourceCollectionStage("extraction"),
  },
  {
    id: "relations",
    label: lang === "zh" ? "整理关系" : "Map",
    metric: lang === "zh" ? `节点 ${sourceCollectionProjectedGraphNodeCount} / 关系 ${sourceCollectionProjectedGraphEdgeCount}` : `${sourceCollectionProjectedGraphNodeCount} nodes / ${sourceCollectionProjectedGraphEdgeCount} edges`,
    summary: sourceCollectionStageLaunchActive("relations")
      ? sourceCollectionStageLaunchSummary("relations")
      : sourceCollectionRelationsDisplayLoading
      ? (lang === "zh" ? "正在读取候选和关系数据" : "Loading candidates and relations")
      : sourceCollectionStageUserSummary(sourceCollectionGraphProjection, lang) || (sourceCollectionProjectedGraphNodeCount > 0
      ? (lang === "zh" ? "资料关系已整理" : "Source relations are ready")
      : sourceCollectionDisplayedCandidateCount > 0
        ? (lang === "zh" ? "可由 Agent 整理资料关系" : "Agent can map source relationships")
        : (lang === "zh" ? "等资料提炼后整理关系" : "Map after extraction")),
    inputLabel: sourceCollectionPrimaryDataLoading
      ? sourceCollectionProjectedCandidateCountLabel
      : (lang === "zh" ? `${sourceCollectionProjectedCandidateCountText} 条候选资料` : `${sourceCollectionProjectedCandidateCountText} candidate sources`),
    outputLabel: lang === "zh" ? `${sourceCollectionProjectedGraphNodeCount} 个节点 / ${sourceCollectionProjectedGraphEdgeCount} 条关系` : `${sourceCollectionProjectedGraphNodeCount} nodes / ${sourceCollectionProjectedGraphEdgeCount} edges`,
    nextLabel: sourceCollectionProjectedGraphNodeCount > 0
      ? (lang === "zh" ? "进入资料入库" : "Move to ingestion")
      : (lang === "zh" ? "生成资料关系" : "Build source relations"),
    state: sourceCollectionStageDisplayState("relations", sourceCollectionRelationsDisplayState),
    status: sourceCollectionStageDisplayStatus("relations", sourceCollectionRelationsDisplayLoading ? sourceCollectionDataSyncText : sourceCollectionStepStatusText(sourceCollectionGraphStepState)),
    detailLabel: lang === "zh" ? "查看资料关系" : "View relations",
    actionLabel: sourceCollectionStageActionLabelFor("relations", sourceCollectionGraphActionLabel),
    actionDisabled: sourceCollectionStageActionReadinessFor("relations").disabled,
    actionTone: "primary",
    actionIcon: "refresh",
    projection: sourceCollectionGraphProjection,
    onAction: () => void startSourceCollectionStageSessionTask("relations"),
    onDetail: () => openSourceCollectionStage("relations"),
  },
  {
    id: "ingestion",
    label: lang === "zh" ? "入库" : "Ingest",
    metric: lang === "zh" ? `正式知识 ${sourceCollectionProjectedFormalKnowledgeCount}` : `${sourceCollectionProjectedFormalKnowledgeCount} formal items`,
    summary: sourceCollectionStageLaunchActive("ingestion")
      ? sourceCollectionStageLaunchSummary("ingestion")
      : sourceCollectionIngestionDisplayLoading
      ? (lang === "zh" ? "正在读取候选和入库数据" : "Loading candidates and ingestion data")
      : sourceCollectionStageUserSummary(sourceCollectionMemoryProjection, lang) || (sourceCollectionProjectedFormalKnowledgeCount > 0
      ? (lang === "zh" ? "已进入团队知识库" : "Synced into Team Knowledge")
      : sourceCollectionProjectedStewardPackCount > 0
        ? (lang === "zh" ? "已生成入库待审包" : "Ingestion review pack ready")
      : knowledgePendingReviewCount > 0
        ? (lang === "zh" ? "有待入库对象" : "Ingestion items pending")
      : sourceCollectionPrecheckCandidateCount > 0
        ? (lang === "zh" ? "可通知资料入库 Agent" : "Can notify ingestion Agent")
        : sourceCollectionDisplayedCandidateCount > 0
          ? (lang === "zh" ? "可先提炼再入库" : "Extract before ingestion")
          : (lang === "zh" ? "等资料提炼后入库" : "Ingest after extraction")),
    inputLabel: sourceCollectionPrecheckCandidateCount > 0
      ? (lang === "zh" ? `${sourceCollectionPrecheckCandidateCount} 条通过资料` : `${sourceCollectionPrecheckCandidateCount} approved sources`)
      : sourceCollectionPrimaryDataLoading
        ? sourceCollectionProjectedCandidateCountLabel
        : (lang === "zh" ? `${sourceCollectionProjectedCandidateCountText} 条候选资料` : `${sourceCollectionProjectedCandidateCountText} candidate sources`),
    outputLabel: lang === "zh" ? `${sourceCollectionProjectedFormalKnowledgeCount} 条正式知识 / ${sourceCollectionProjectedGraphNodeCount} 个关系节点` : `${sourceCollectionProjectedFormalKnowledgeCount} formal / ${sourceCollectionProjectedGraphNodeCount} graph nodes`,
    nextLabel: sourceCollectionIngestionReadyForExperiment
      ? (lang === "zh" ? "进入实验规划" : "Move to experiment planning")
      : sourceCollectionProjectedStewardPackCount > 0
        ? (lang === "zh" ? "等待入库完成" : "Wait for ingestion")
        : (lang === "zh" ? "Agent 入库资料" : "Agent ingest sources"),
    state: sourceCollectionStageDisplayState("ingestion", sourceCollectionIngestionDisplayState),
    status: sourceCollectionStageDisplayStatus("ingestion", sourceCollectionIngestionDisplayLoading ? sourceCollectionDataSyncText : sourceCollectionStepStatusText(sourceCollectionMemoryStepState)),
    detailLabel: lang === "zh" ? "查看入库详情" : "View ingestion details",
    actionLabel: sourceCollectionIngestionReadyForExperiment
      ? (lang === "zh" ? "进入实验规划" : "Plan experiments")
      : sourceCollectionStageActionLabelFor("ingestion", sourceCollectionMemoryActionLabel),
    actionDisabled: sourceCollectionIngestionReadyForExperiment
      ? false
      : sourceCollectionStageActionReadinessFor("ingestion").disabled,
    actionTone: "primary",
    actionIcon: "check",
    projection: sourceCollectionMemoryProjection,
    onAction: sourceCollectionIngestionReadyForExperiment
      ? () => navigate(sourceCollectionExperimentPlanningRoute)
      : () => void startSourceCollectionStageSessionTask("ingestion"),
    onDetail: () => openSourceCollectionStage("ingestion"),
  },
];

  return sourceCollectionStageModules;
}

export function buildSourceCollectionBoardChrome(input: {
  lang: "zh" | "en";
  sourceCollectionStageModules: SourceCollectionStageModule[];
  sourceCollectionStageFocusLabel: string;
}) {
  const { lang, sourceCollectionStageModules, sourceCollectionStageFocusLabel } = input;
  const sourceCollectionBoardCurrentModule =
    sourceCollectionStageModules.find((module) => module.state === "active")
    ?? sourceCollectionStageModules.find((module) => module.state === "failed")
    ?? sourceCollectionStageModules.find((module) => module.state === "pending")
    ?? sourceCollectionStageModules.find((module) => module.state === "idle")
    ?? sourceCollectionStageModules[sourceCollectionStageModules.length - 1];
  const sourceCollectionBoardNextStepLabel = sourceCollectionBoardCurrentModule?.state === "done"
    ? (lang === "zh" ? "进入实验规划" : "Plan experiments")
    : sourceCollectionBoardCurrentModule?.label ?? sourceCollectionStageFocusLabel;
  return { sourceCollectionBoardCurrentModule, sourceCollectionBoardNextStepLabel };
}

export function buildSourceCollectionCompletionFlowNodes(input: {
  selectedTeamKnowledgeCollectionWorkRun: TeamWorkflowKnowledgeIngestionWorkRun | null | undefined;
  sourceCollectionStageModules: SourceCollectionStageModule[];
}): SourceCollectionCompletionFlowNode[] {
  const flow = input.selectedTeamKnowledgeCollectionWorkRun?.flowVisualization ?? null;
  if (flow?.nodes?.length) {
    return flow.nodes;
  }
  return input.sourceCollectionStageModules.map((module) => ({
    stageId: module.id,
    label: module.label,
    agentRole: SOURCE_COLLECTION_STAGE_AGENT_KEYS[module.id][0] || module.id,
    status:
      module.state === "active"
        ? "running"
        : module.state === "done"
          ? "completed"
          : module.state === "failed"
            ? "failed"
            : module.state === "pending"
              ? "pending"
              : "queued",
    inputCount: 0,
    outputCount: 0,
    artifactIds: [],
    detail: module.summary,
  }));
}

export function buildSourceCollectionStandaloneStageModules(input: {
  lang: "zh" | "en";
  sourceCollectionStageModules: SourceCollectionStageModule[];
  selectedSourceCollectionStageId: SourceCollectionStageModuleId;
  sourceCollectionStageActionReadinessFor: (stageId: SourceCollectionStageModuleId) => SourceCollectionActionReadiness;
  sourceCollectionActionDisabledTitle: (readiness: SourceCollectionActionReadiness, fallback: string) => string;
}): TeamSourceCollectionStandaloneStageModule[] {
  const {
    lang,
    sourceCollectionStageModules,
    selectedSourceCollectionStageId,
    sourceCollectionStageActionReadinessFor,
    sourceCollectionActionDisabledTitle,
  } = input;
  return sourceCollectionStageModules.map((module) => {
    const cardActionReadiness = sourceCollectionStageActionReadinessFor(module.id);
    return {
      id: module.id,
      tone: module.state,
      selected: module.id === selectedSourceCollectionStageId,
      title: module.detailLabel,
      status: module.status,
      label: module.label,
      metric: module.metric,
      nextLabel: `${lang === "zh" ? "下一步：" : "Next: "}${module.nextLabel}`,
      actionLabel: module.actionLabel,
      actionDisabled: module.actionDisabled,
      actionTitle: sourceCollectionActionDisabledTitle(cardActionReadiness, module.actionLabel),
      actionIcon: module.actionIcon,
      onAction: module.onAction,
      onDetail: module.onDetail,
    };
  });
}
