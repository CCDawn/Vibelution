/**
 * Pure stage display loading/state/sync metric labels for SC presentation.
 * Phase R2-m extract from useSourceCollectionPresentationCore (behavior-conserving).
 */
import type { SourceCollectionStepState } from "./runModel";

export type DeriveSourceCollectionStageDisplaySurfacesInput = {
  lang: "zh" | "en";
  loadingText: string;
  dataSyncText: string;
  recordsDataLoading: boolean;
  assignmentsDataLoading: boolean;
  primaryDataLoading: boolean;
  screeningDataLoading: boolean;
  graphDataLoading: boolean;
  sourceQualityLoading: boolean;
  knowledgeIngestionDataLoading: boolean;
  searchStepState: SourceCollectionStepState;
  extractionStepState: SourceCollectionStepState;
  graphStepState: SourceCollectionStepState;
  memoryStepState: SourceCollectionStepState;
  projectedCollectedCount: number;
  displayedCandidateCount: number;
  projectedCandidateCount: number;
  projectedAssessedCount: number;
  projectedApprovedCount: number;
  currentCandidateCount: number;
  extractionAgentMaterialCount: number;
  runPendingScreeningCount: number;
  projectedFormalKnowledgeCount: number;
};

export function deriveSourceCollectionStageDisplaySurfaces(
  input: DeriveSourceCollectionStageDisplaySurfacesInput,
) {
  const {
    lang,
    loadingText,
    dataSyncText,
    recordsDataLoading,
    assignmentsDataLoading,
    primaryDataLoading,
    screeningDataLoading,
    graphDataLoading,
    sourceQualityLoading,
    knowledgeIngestionDataLoading,
    searchStepState,
    extractionStepState,
    graphStepState,
    memoryStepState,
    projectedCollectedCount,
    displayedCandidateCount,
    projectedCandidateCount,
    projectedAssessedCount,
    projectedApprovedCount,
    currentCandidateCount,
    extractionAgentMaterialCount,
    runPendingScreeningCount,
    projectedFormalKnowledgeCount,
  } = input;

  const sourceCollectionFindingDisplayLoading = recordsDataLoading || assignmentsDataLoading;
  const sourceCollectionFindingDisplayState: SourceCollectionStepState = sourceCollectionFindingDisplayLoading
    ? "pending"
    : searchStepState;
  const sourceCollectionExtractionDisplayLoading = primaryDataLoading || screeningDataLoading;
  const sourceCollectionExtractionDisplayState: SourceCollectionStepState = sourceCollectionExtractionDisplayLoading
    ? "pending"
    : extractionStepState;
  const sourceCollectionRelationsDisplayLoading = graphDataLoading;
  const sourceCollectionRelationsDisplayState: SourceCollectionStepState = sourceCollectionRelationsDisplayLoading
    ? "pending"
    : graphStepState;
  const sourceCollectionIngestionDisplayLoading = sourceQualityLoading || knowledgeIngestionDataLoading;
  const sourceCollectionIngestionDisplayState: SourceCollectionStepState = sourceCollectionIngestionDisplayLoading
    ? "pending"
    : memoryStepState;
  const sourceCollectionSourceSyncStatusText = projectedCollectedCount > 0
    ? dataSyncText
    : loadingText;
  const sourceCollectionCandidateSyncStatusText = displayedCandidateCount > 0 || projectedCollectedCount > 0
    ? dataSyncText
    : loadingText;
  const sourceCollectionExtractionLoadingMetric = projectedCandidateCount > 0
    ? (lang === "zh"
      ? `已处理 ${projectedAssessedCount}/${projectedCandidateCount} · ${dataSyncText}`
      : `${projectedAssessedCount}/${projectedCandidateCount} processed · ${dataSyncText}`)
    : (lang === "zh" ? "提炼进度 加载中" : "extraction loading");
  const sourceCollectionExtractionMaterialMetric = lang === "zh"
    ? `已提炼 ${currentCandidateCount}/${currentCandidateCount} · ${extractionAgentMaterialCount} 条待补材料`
    : `${currentCandidateCount}/${currentCandidateCount} extracted · ${extractionAgentMaterialCount} need material`;
  const sourceCollectionExtractionLoadingOutputLabel = projectedCandidateCount > 0 || projectedApprovedCount > 0
    ? (lang === "zh"
      ? `${projectedApprovedCount} 条保留 / ${runPendingScreeningCount} 条待处理 · ${dataSyncText}`
      : `${projectedApprovedCount} kept / ${runPendingScreeningCount} pending · ${dataSyncText}`)
    : (lang === "zh" ? "提炼结果加载中" : "extraction result loading");
  const sourceCollectionIngestionReadyForExperiment = projectedFormalKnowledgeCount > 0;

  return {
    sourceCollectionFindingDisplayLoading,
    sourceCollectionFindingDisplayState,
    sourceCollectionExtractionDisplayLoading,
    sourceCollectionExtractionDisplayState,
    sourceCollectionRelationsDisplayLoading,
    sourceCollectionRelationsDisplayState,
    sourceCollectionIngestionDisplayLoading,
    sourceCollectionIngestionDisplayState,
    sourceCollectionSourceSyncStatusText,
    sourceCollectionCandidateSyncStatusText,
    sourceCollectionExtractionLoadingMetric,
    sourceCollectionExtractionMaterialMetric,
    sourceCollectionExtractionLoadingOutputLabel,
    sourceCollectionIngestionReadyForExperiment,
  };
}
