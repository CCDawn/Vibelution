/**
 * Pure count/label/text derivation for SC presentation.
 * Phase R2-m extract from useSourceCollectionPresentationCore (behavior-conserving).
 */
import { makeSourceCollectionCountText } from "./presentationCountText";
import {
  sourceCollectionBoundCountToCurrentCoverage,
  type SourceCollectionStageCardProjection,
} from "./stageProjection";
import type { SourceCollectionSourceFilter } from "./evidenceModel";

export type DeriveSourceCollectionDisplayLabelsInput = {
  lang: "zh" | "en";
  loadingText: string;
  dataSyncText: string;
  recordsDataLoading: boolean;
  assignmentsDataLoading: boolean;
  primaryDataLoading: boolean;
  screeningDataLoading: boolean;
  collectedCount: number;
  projectedCollectedCount: number;
  searchOpenAssignmentCount: number;
  downstreamOpenAssignmentCount: number;
  queryCount: number;
  assignmentsLength: number;
  searchPlanQueryCount: number | null | undefined;
  startResultSearchPlanQueryCount: number | null | undefined;
  displayedCandidateCount: number;
  projectedCandidateCount: number;
  projectedAssessedCount: number;
  projectedApprovedCount: number;
  runReviewableCandidateCount: number;
  runCandidateCount: number;
  runAssessedCount: number;
  candidateProjection: SourceCollectionStageCardProjection | null | undefined;
  candidateFilterCounts: Record<SourceCollectionSourceFilter, number>;
};

export function deriveSourceCollectionDisplayLabels(input: DeriveSourceCollectionDisplayLabelsInput) {
  const {
    lang,
    loadingText,
    dataSyncText,
    recordsDataLoading,
    assignmentsDataLoading,
    primaryDataLoading,
    screeningDataLoading,
    collectedCount,
    projectedCollectedCount,
    searchOpenAssignmentCount,
    downstreamOpenAssignmentCount,
    queryCount,
    assignmentsLength,
    searchPlanQueryCount,
    startResultSearchPlanQueryCount,
    displayedCandidateCount,
    projectedCandidateCount,
    projectedAssessedCount,
    projectedApprovedCount,
    runReviewableCandidateCount,
    runCandidateCount,
    runAssessedCount,
    candidateProjection,
    candidateFilterCounts,
  } = input;

  const {
    countText: sourceCollectionCountText,
    countWithUnit: sourceCollectionCountWithUnit,
  } = makeSourceCollectionCountText({
    lang,
    loadingText,
    syncingText: dataSyncText,
  });

  const sourceCollectionCollectedCountText = sourceCollectionCountText(recordsDataLoading, collectedCount);
  const sourceCollectionProjectedCollectedCountText = sourceCollectionCountText(recordsDataLoading, projectedCollectedCount);
  const sourceCollectionSearchOpenAssignmentCountText = assignmentsDataLoading
    ? loadingText
    : String(searchOpenAssignmentCount);
  const sourceCollectionDownstreamOpenAssignmentCountText = assignmentsDataLoading
    ? loadingText
    : String(downstreamOpenAssignmentCount);
  const sourceCollectionQueryDataLoading = Boolean(
    assignmentsDataLoading
    && searchPlanQueryCount == null
    && startResultSearchPlanQueryCount == null
    && assignmentsLength <= 0,
  );
  const sourceCollectionQueryCountText = sourceCollectionQueryDataLoading
    ? loadingText
    : String(queryCount);
  const sourceCollectionCollectedCountLabel = sourceCollectionCountWithUnit(recordsDataLoading, collectedCount, "条", "raw records");
  const sourceCollectionProjectedCollectedCountLabel = sourceCollectionCountWithUnit(recordsDataLoading, projectedCollectedCount, "条", "raw records");
  const sourceCollectionSearchOpenAssignmentCountLabel = sourceCollectionCountWithUnit(assignmentsDataLoading, searchOpenAssignmentCount, "项");
  const sourceCollectionDownstreamOpenAssignmentCountLabel = sourceCollectionCountWithUnit(assignmentsDataLoading, downstreamOpenAssignmentCount, "项");
  const sourceCollectionQueryCountLabel = sourceCollectionCountWithUnit(sourceCollectionQueryDataLoading, queryCount, "个");
  const sourceCollectionCollectedRunSummaryText = recordsDataLoading
    ? loadingText
    : lang === "zh"
      ? `${collectedCount} 条资料`
      : `${collectedCount} records`;
  const sourceCollectionAssignmentRunSummaryText = assignmentsDataLoading
    ? loadingText
    : lang === "zh"
      ? `${assignmentsLength} 个任务`
      : `${assignmentsLength} assignments`;
  const sourceCollectionDisplayedCandidateCountText = sourceCollectionCountText(primaryDataLoading, displayedCandidateCount);
  const sourceCollectionProjectedCandidateCountText = sourceCollectionCountText(primaryDataLoading, projectedCandidateCount);
  const sourceCollectionCoverageBoundCandidateCount = sourceCollectionBoundCountToCurrentCoverage(
    candidateProjection,
    projectedCandidateCount,
  );
  const sourceCollectionCurrentCandidateCount = runReviewableCandidateCount > 0
    ? Math.min(sourceCollectionCoverageBoundCandidateCount, runReviewableCandidateCount)
    : sourceCollectionCoverageBoundCandidateCount;
  const sourceCollectionCurrentCandidateCountText = sourceCollectionCountText(
    primaryDataLoading,
    sourceCollectionCurrentCandidateCount,
  );
  const sourceCollectionProjectedCandidateCountLabel = sourceCollectionCountWithUnit(
    primaryDataLoading,
    projectedCandidateCount,
    "条候选资料",
    "candidate sources",
  );
  const sourceCollectionProjectedAssessedCountText = sourceCollectionCountText(screeningDataLoading, projectedAssessedCount);
  const sourceCollectionProjectedApprovedCountText = sourceCollectionCountText(screeningDataLoading, projectedApprovedCount);
  const sourceCollectionDisplayedCandidateFilterCounts =
    displayedCandidateCount <= runCandidateCount
      ? candidateFilterCounts
      : {
          ...candidateFilterCounts,
          all: displayedCandidateCount,
        };
  const sourceCollectionRunPendingScreeningCount = Math.max(
    0,
    runCandidateCount > 0
      ? runReviewableCandidateCount - runAssessedCount
      : projectedCandidateCount - projectedAssessedCount,
  );
  const sourceCollectionRunPendingScreeningCountText = sourceCollectionCountText(
    screeningDataLoading,
    sourceCollectionRunPendingScreeningCount,
  );

  return {
    sourceCollectionCountText,
    sourceCollectionCountWithUnit,
    sourceCollectionCollectedCountText,
    sourceCollectionProjectedCollectedCountText,
    sourceCollectionSearchOpenAssignmentCountText,
    sourceCollectionDownstreamOpenAssignmentCountText,
    sourceCollectionQueryDataLoading,
    sourceCollectionQueryCountText,
    sourceCollectionCollectedCountLabel,
    sourceCollectionProjectedCollectedCountLabel,
    sourceCollectionSearchOpenAssignmentCountLabel,
    sourceCollectionDownstreamOpenAssignmentCountLabel,
    sourceCollectionQueryCountLabel,
    sourceCollectionCollectedRunSummaryText,
    sourceCollectionAssignmentRunSummaryText,
    sourceCollectionDisplayedCandidateCountText,
    sourceCollectionProjectedCandidateCountText,
    sourceCollectionCoverageBoundCandidateCount,
    sourceCollectionCurrentCandidateCount,
    sourceCollectionCurrentCandidateCountText,
    sourceCollectionProjectedCandidateCountLabel,
    sourceCollectionProjectedAssessedCountText,
    sourceCollectionProjectedApprovedCountText,
    sourceCollectionDisplayedCandidateFilterCounts,
    sourceCollectionRunPendingScreeningCount,
    sourceCollectionRunPendingScreeningCountText,
  };
}
