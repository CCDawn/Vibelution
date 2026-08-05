/**
 * Pure list/count/loading metrics for SC presentation.
 * Phase R2-l extract from useSourceCollectionPresentationCore (behavior-conserving).
 */
import type {
  DataProcessingCollectionAssignment,
  DataProcessingRecord,
  DataProcessingStatus,
  TeamWorkflowCandidate,
} from "../../../api/types";
import {
  sourceCollectionCandidateSourceCategory,
  sourceCollectionCandidateTrace,
  sourceCollectionEvidenceLedgerSummary,
  sourceCollectionFilterCounts,
  sourceCollectionFilterMatches,
  sourceCollectionRecordProvenance,
  sourceCollectionRecordSourceCategory,
  type SourceCollectionEvidenceLedgerSummary,
  type SourceCollectionSourceFilter,
} from "./evidenceModel";
import {
  SOURCE_COLLECTION_SEARCH_EXECUTION_ROLES,
  sourceCollectionCandidateQualityState,
} from "./presentationModel";
import {
  sourceCollectionNonNegativeCount,
  sourceCollectionStageProjectionCount,
  type SourceCollectionStageCardProjection,
} from "./stageProjection";

export type DeriveSourceCollectionListMetricsInput = {
  lang: "zh" | "en";
  researchWorkflowTeamSelected: boolean;
  selectedSourceCollectionRunEffectiveId: string;
  sourceCollectionSourceFilter: SourceCollectionSourceFilter;
  sourceCollectionRecords: DataProcessingRecord[];
  sourceCollectionAssignments: DataProcessingCollectionAssignment[];
  sourceCollectionRunStatus: DataProcessingStatus | null | undefined;
  sourceCollectionSummaryCounts: Record<string, unknown>;
  sourceCollectionRecordsQuery: {
    data?: unknown;
    isPending?: boolean;
    error?: unknown;
  };
  sourceCollectionAssignmentsQuery: {
    data?: unknown;
    isPending?: boolean;
    error?: unknown;
  };
  sourceCollectionRunStatusQuery: { isPending?: boolean };
  sourceCollectionSummaryQuery: {
    data?: unknown;
    isPending?: boolean;
    error?: unknown;
  };
  sourceCollectionRunsQuery: { data?: unknown; isPending?: boolean };
  teamWorkflowCandidatesQuery: {
    data?: unknown;
    isPending?: boolean;
    isFetching?: boolean;
    error?: unknown;
  };
  teamWorkflowSourceQualityStatusQuery: {
    data?: unknown;
    isPending?: boolean;
    isFetching?: boolean;
    error?: unknown;
  };
  teamWorkflowCandidateGraphQuery: {
    data?: unknown;
    isPending?: boolean;
    error?: unknown;
  };
  teamWorkflowKnowledgeIngestionStatusQuery: {
    data?: unknown;
    isPending?: boolean;
    error?: unknown;
  };
  teamWorkflowSourceQualityStatus: unknown;
  teamWorkflowCandidateListEnabled: boolean;
  sourceCollectionNeedsCandidateList: boolean;
  sourceCollectionFindingDetailsVisible: boolean;
  sourceCollectionWorkspaceSelected: boolean;
  teamWorkflowSourceQualityEnabled: boolean;
  teamWorkflowGraphEnabled: boolean;
  teamWorkflowKnowledgeIngestionEnabled: boolean;
  sourceCollectionRunCandidates: TeamWorkflowCandidate[];
  sourceCollectionStageCardById: Map<string, SourceCollectionStageCardProjection | null | undefined>;
  sourceCollectionStageRound: {
    sourceCollectionStageCardSummary?: {
      excludedSourceCount?: number;
      sourceCandidateCount?: number;
    };
  } | null | undefined;
  sourceCollectionSearchPlanRef: { queryCount?: number } | null | undefined;
  selectedTeamStartSourceCollectionResult: { searchPlan?: { queryCount?: number } } | null | undefined;
};

export function deriveSourceCollectionListMetrics(input: DeriveSourceCollectionListMetricsInput) {
  const {
    lang,
    researchWorkflowTeamSelected,
    selectedSourceCollectionRunEffectiveId,
    sourceCollectionSourceFilter,
    sourceCollectionRecords,
    sourceCollectionAssignments,
    sourceCollectionRunStatus,
    sourceCollectionSummaryCounts,
    sourceCollectionRecordsQuery,
    sourceCollectionAssignmentsQuery,
    sourceCollectionRunStatusQuery,
    sourceCollectionSummaryQuery,
    sourceCollectionRunsQuery,
    teamWorkflowCandidatesQuery,
    teamWorkflowSourceQualityStatusQuery,
    teamWorkflowCandidateGraphQuery,
    teamWorkflowKnowledgeIngestionStatusQuery,
    teamWorkflowSourceQualityStatus,
    teamWorkflowCandidateListEnabled,
    sourceCollectionNeedsCandidateList,
    sourceCollectionFindingDetailsVisible,
    sourceCollectionWorkspaceSelected,
    teamWorkflowSourceQualityEnabled,
    teamWorkflowGraphEnabled,
    teamWorkflowKnowledgeIngestionEnabled,
    sourceCollectionRunCandidates,
    sourceCollectionStageCardById,
    sourceCollectionStageRound,
    sourceCollectionSearchPlanRef,
    selectedTeamStartSourceCollectionResult,
  } = input;

  const sourceCollectionRunSummary = sourceCollectionRunStatus?.summary as (DataProcessingStatus["summary"] & {
    searchOpenAssignmentCount?: number;
    collectionOpenAssignmentCount?: number;
    downstreamOpenAssignmentCount?: number;
  }) | undefined;

  const sourceCollectionOpenAssignments = sourceCollectionAssignments.filter((assignment) =>
    ["open", "in_progress", "returned"].includes(assignment.status),
  );
  const sourceCollectionOpenAssignmentCount =
    sourceCollectionRunSummary?.openAssignmentCount
    ?? sourceCollectionOpenAssignments.length;
  const sourceCollectionSearchOpenAssignmentCount =
    sourceCollectionRunSummary?.searchOpenAssignmentCount
    ?? sourceCollectionOpenAssignments.filter((assignment) =>
      SOURCE_COLLECTION_SEARCH_EXECUTION_ROLES.has(assignment.agentRole),
    ).length;
  const sourceCollectionDownstreamOpenAssignmentCount =
    sourceCollectionRunSummary?.downstreamOpenAssignmentCount
    ?? Math.max(0, sourceCollectionOpenAssignmentCount - sourceCollectionSearchOpenAssignmentCount);

  const sourceCollectionCandidatesByRecordId = (() => {
    const mapping = new Map<string, TeamWorkflowCandidate>();
    sourceCollectionRunCandidates.forEach((candidate) => {
      const trace = sourceCollectionCandidateTrace(candidate);
      if (trace.recordId && !mapping.has(trace.recordId)) {
        mapping.set(trace.recordId, candidate);
      }
    });
    return mapping;
  })();

  const sourceCollectionRecordProvenances = sourceCollectionRecords.map((record) =>
    sourceCollectionRecordProvenance(record, lang),
  );
  const sourceCollectionRecordSourceCategories = sourceCollectionRecords.map((record) =>
    sourceCollectionRecordSourceCategory(record, lang),
  );
  const sourceCollectionFilteredRecords = sourceCollectionRecords.filter((record) =>
    sourceCollectionFilterMatches(sourceCollectionSourceFilter, sourceCollectionRecordSourceCategory(record, lang)),
  );
  const sourceCollectionRunCandidateSourceCategories = sourceCollectionRunCandidates.map((candidate) =>
    sourceCollectionCandidateSourceCategory(candidate, lang),
  );
  const sourceCollectionFilteredRunCandidates = sourceCollectionRunCandidates.filter((candidate) =>
    sourceCollectionFilterMatches(sourceCollectionSourceFilter, sourceCollectionCandidateSourceCategory(candidate, lang)),
  );

  const sourceCollectionRawRecordCount =
    Number(
      (sourceCollectionRecordsQuery.data as { summary?: { recordCount?: number } } | undefined)?.summary?.recordCount
      ?? sourceCollectionSummaryCounts.recordCount
      ?? sourceCollectionRunSummary?.recordCount
      ?? sourceCollectionRecords.length,
    ) || 0;
  const sourceCollectionRecordClickableSourceCount = sourceCollectionRecordProvenances.filter((item) => item.href).length;
  const sourceCollectionRecordLocalFileCount = sourceCollectionRecordProvenances.filter((item) => item.kind === "file").length;
  const sourceCollectionRecordMissingSourceCount = sourceCollectionRecordProvenances.filter((item) => item.kind === "missing").length;
  const sourceCollectionRunCandidateCount = sourceCollectionRunCandidates.length;
  const sourceCollectionRecordFilterCounts = sourceCollectionFilterCounts(sourceCollectionRecordSourceCategories);
  const sourceCollectionCandidateFilterCounts = sourceCollectionFilterCounts(sourceCollectionRunCandidateSourceCategories);

  const sourceCollectionReviewableRunCandidates = sourceCollectionRunCandidates.filter(
    (candidate) => candidate.sourceVersionFamily?.state !== "superseded",
  );
  const sourceCollectionRunReviewableCandidateCount = sourceCollectionReviewableRunCandidates.length;
  const sourceCollectionRunAssessedCount = sourceCollectionReviewableRunCandidates.filter(
    (candidate) => sourceCollectionCandidateQualityState(candidate).assessed,
  ).length;
  const sourceCollectionRunApprovedCount = sourceCollectionReviewableRunCandidates.filter(
    (candidate) => sourceCollectionCandidateQualityState(candidate).approved,
  ).length;
  const sourceCollectionRunNeedsRevisionCount = sourceCollectionReviewableRunCandidates.filter(
    (candidate) => sourceCollectionCandidateQualityState(candidate).needsRevision,
  ).length;

  const sourceCollectionEvidenceLedgerSummaries = sourceCollectionRunCandidates
    .map((candidate) => sourceCollectionEvidenceLedgerSummary(candidate))
    .filter((summary): summary is SourceCollectionEvidenceLedgerSummary => Boolean(summary));
  const sourceCollectionEvidenceReadyCandidateCount = sourceCollectionEvidenceLedgerSummaries.filter(
    (summary) => !summary.missingAnchor,
  ).length;
  const sourceCollectionMissingEvidenceAnchorCount = sourceCollectionEvidenceLedgerSummaries.filter(
    (summary) => summary.missingAnchor,
  ).length;
  const sourceCollectionCollectedCount = sourceCollectionRawRecordCount;
  const sourceCollectionRunSummaryHasRecordCount = typeof sourceCollectionRunSummary?.recordCount === "number";
  const sourceCollectionSummaryHasRecordCount = typeof sourceCollectionSummaryCounts.recordCount === "number";
  const sourceCollectionRunSummaryHasAssignmentCounts = [
    sourceCollectionRunSummary?.openAssignmentCount,
    sourceCollectionRunSummary?.searchOpenAssignmentCount,
    sourceCollectionRunSummary?.downstreamOpenAssignmentCount,
  ].some((value) => typeof value === "number");

  const sourceCollectionCandidateListDataLoading = Boolean(
    researchWorkflowTeamSelected
    && selectedSourceCollectionRunEffectiveId
    && teamWorkflowCandidateListEnabled
    && sourceCollectionNeedsCandidateList
    && !teamWorkflowCandidatesQuery.data
    && (teamWorkflowCandidatesQuery.isPending || teamWorkflowCandidatesQuery.isFetching),
  );
  const sourceCollectionRecordsDataLoading = Boolean(
    sourceCollectionFindingDetailsVisible
    && !sourceCollectionRecordsQuery.data
    && !sourceCollectionSummaryHasRecordCount
    && !sourceCollectionRunSummaryHasRecordCount
    && (
      sourceCollectionRecordsQuery.isPending
      || sourceCollectionRunStatusQuery.isPending
    ),
  );
  const sourceCollectionAssignmentsDataLoading = Boolean(
    sourceCollectionFindingDetailsVisible
    && !sourceCollectionAssignmentsQuery.data
    && !sourceCollectionRunSummaryHasAssignmentCounts
    && (sourceCollectionAssignmentsQuery.isPending || sourceCollectionRunStatusQuery.isPending),
  );

  const sourceCollectionCollectionProjection = sourceCollectionStageCardById.get("finding") ?? null;
  const sourceCollectionExtractionProjection = sourceCollectionStageCardById.get("extraction") ?? null;
  const sourceCollectionCandidateProjection = sourceCollectionExtractionProjection;
  const sourceCollectionScreeningProjection = sourceCollectionExtractionProjection;
  const sourceCollectionGraphProjection = sourceCollectionStageCardById.get("relations") ?? null;
  const sourceCollectionMemoryProjection = sourceCollectionStageCardById.get("ingestion") ?? null;

  const sourceCollectionExcludedSourceCount = Math.max(
    sourceCollectionNonNegativeCount(sourceCollectionStageRound?.sourceCollectionStageCardSummary?.excludedSourceCount),
    sourceCollectionNonNegativeCount(sourceCollectionSummaryCounts.excludedSourceCount as number | undefined),
    sourceCollectionStageProjectionCount(sourceCollectionCandidateProjection, "excluded", 0),
    sourceCollectionNonNegativeCount(
      sourceCollectionCandidateProjection?.latestTask?.closureSummary?.excludedSourceCount,
    ),
  );
  const sourceCollectionStageSummaryCandidateCount = Number(
    sourceCollectionStageRound?.sourceCollectionStageCardSummary?.sourceCandidateCount
    ?? sourceCollectionSummaryCounts.sourceCandidateCount,
  );
  const sourceCollectionCandidateProjectionFallbackCount = Number.isFinite(sourceCollectionStageSummaryCandidateCount)
    ? Math.max(sourceCollectionRunCandidateCount, Math.max(0, sourceCollectionStageSummaryCandidateCount))
    : sourceCollectionRunCandidateCount;
  const sourceCollectionProjectedCollectedCount = Math.max(
    sourceCollectionCollectedCount,
    sourceCollectionStageProjectionCount(
      sourceCollectionCollectionProjection,
      "artifact",
      sourceCollectionCollectedCount,
    ),
  );
  const sourceCollectionProjectedCandidateCount = sourceCollectionStageProjectionCount(
    sourceCollectionCandidateProjection,
    "artifact",
    sourceCollectionCandidateProjectionFallbackCount,
  );
  const sourceCollectionProjectedAssessedCount = sourceCollectionRunCandidateCount > 0
    ? sourceCollectionRunAssessedCount
    : sourceCollectionStageProjectionCount(
      sourceCollectionScreeningProjection,
      "artifact",
      sourceCollectionRunAssessedCount,
    );
  const sourceCollectionProjectedApprovedCount = sourceCollectionRunCandidateCount > 0
    ? sourceCollectionRunApprovedCount
    : sourceCollectionStageProjectionCount(
      sourceCollectionScreeningProjection,
      "output",
      sourceCollectionRunApprovedCount,
    );
  const sourceCollectionDisplayedCandidateCount = Math.max(
    sourceCollectionRunCandidateCount,
    sourceCollectionProjectedCandidateCount,
  );
  const sourceCollectionQueryCount =
    sourceCollectionSearchPlanRef?.queryCount
    ?? selectedTeamStartSourceCollectionResult?.searchPlan?.queryCount
    ?? sourceCollectionAssignments.reduce(
      (total: number, assignment: DataProcessingCollectionAssignment) =>
        total + (assignment.scope.queryCount ?? assignment.scope.assignedQueries?.length ?? 0),
      0,
    );

  const sourceCollectionPrimaryDataLoading = Boolean(
    researchWorkflowTeamSelected
    && (
      sourceCollectionCandidateListDataLoading
      || (
        sourceCollectionDisplayedCandidateCount <= 0
        && (
          sourceCollectionRecordsDataLoading
          || sourceCollectionAssignmentsDataLoading
          || (sourceCollectionRunsQuery.isPending && !sourceCollectionRunsQuery.data)
          || (
            selectedSourceCollectionRunEffectiveId
            && sourceCollectionSummaryQuery.isPending
            && sourceCollectionWorkspaceSelected
            && !sourceCollectionSummaryQuery.data
          )
        )
      )
    ),
  );
  const sourceCollectionSourceQualityLoading = Boolean(
    researchWorkflowTeamSelected
    && teamWorkflowSourceQualityEnabled
    && !teamWorkflowSourceQualityStatus
    && (teamWorkflowSourceQualityStatusQuery.isPending || teamWorkflowSourceQualityStatusQuery.isFetching),
  );
  const sourceCollectionGraphDataLoading = Boolean(
    researchWorkflowTeamSelected
    && selectedSourceCollectionRunEffectiveId
    && teamWorkflowGraphEnabled
    && teamWorkflowCandidateGraphQuery.isPending && !teamWorkflowCandidateGraphQuery.data,
  );
  const sourceCollectionKnowledgeIngestionDataLoading = Boolean(
    researchWorkflowTeamSelected
    && selectedSourceCollectionRunEffectiveId
    && teamWorkflowKnowledgeIngestionEnabled
    && teamWorkflowKnowledgeIngestionStatusQuery.isPending && !teamWorkflowKnowledgeIngestionStatusQuery.data,
  );
  const sourceCollectionActionInitialDataPending = Boolean(
    researchWorkflowTeamSelected
    && selectedSourceCollectionRunEffectiveId
    && (
      sourceCollectionRecordsDataLoading
      || sourceCollectionAssignmentsDataLoading
      || sourceCollectionPrimaryDataLoading
      || sourceCollectionSourceQualityLoading
      || sourceCollectionGraphDataLoading
      || sourceCollectionKnowledgeIngestionDataLoading
    ),
  );
  const sourceCollectionActionDataError = Boolean(
    researchWorkflowTeamSelected
    && selectedSourceCollectionRunEffectiveId
    && (
      (sourceCollectionRecordsQuery.error && !sourceCollectionRecordsQuery.data && !sourceCollectionSummaryHasRecordCount && !sourceCollectionRunSummaryHasRecordCount)
      || (sourceCollectionAssignmentsQuery.error && !sourceCollectionAssignmentsQuery.data && !sourceCollectionRunSummaryHasAssignmentCounts)
      || (sourceCollectionSummaryQuery.error && sourceCollectionWorkspaceSelected && !sourceCollectionSummaryQuery.data)
    ),
  );
  const sourceCollectionSourceQualityDataError = Boolean(
    researchWorkflowTeamSelected
    && selectedSourceCollectionRunEffectiveId
    && teamWorkflowSourceQualityStatusQuery.error
    && !teamWorkflowSourceQualityStatusQuery.data,
  );
  const sourceCollectionGraphDataError = Boolean(
    researchWorkflowTeamSelected
    && selectedSourceCollectionRunEffectiveId
    && teamWorkflowCandidateGraphQuery.error
    && !teamWorkflowCandidateGraphQuery.data,
  );
  const sourceCollectionKnowledgeIngestionDataError = Boolean(
    researchWorkflowTeamSelected
    && selectedSourceCollectionRunEffectiveId
    && teamWorkflowKnowledgeIngestionStatusQuery.error
    && !teamWorkflowKnowledgeIngestionStatusQuery.data,
  );
  const sourceCollectionScreeningDataLoading = sourceCollectionPrimaryDataLoading || sourceCollectionSourceQualityLoading;

  return {
    sourceCollectionRunSummary,
    sourceCollectionOpenAssignments,
    sourceCollectionOpenAssignmentCount,
    sourceCollectionSearchOpenAssignmentCount,
    sourceCollectionDownstreamOpenAssignmentCount,
    sourceCollectionCandidatesByRecordId,
    sourceCollectionRecordProvenances,
    sourceCollectionRecordSourceCategories,
    sourceCollectionFilteredRecords,
    sourceCollectionRunCandidateSourceCategories,
    sourceCollectionFilteredRunCandidates,
    sourceCollectionRawRecordCount,
    sourceCollectionRecordClickableSourceCount,
    sourceCollectionRecordLocalFileCount,
    sourceCollectionRecordMissingSourceCount,
    sourceCollectionRunCandidateCount,
    sourceCollectionRecordFilterCounts,
    sourceCollectionCandidateFilterCounts,
    sourceCollectionReviewableRunCandidates,
    sourceCollectionRunReviewableCandidateCount,
    sourceCollectionRunAssessedCount,
    sourceCollectionRunApprovedCount,
    sourceCollectionRunNeedsRevisionCount,
    sourceCollectionEvidenceLedgerSummaries,
    sourceCollectionEvidenceReadyCandidateCount,
    sourceCollectionMissingEvidenceAnchorCount,
    sourceCollectionCollectedCount,
    sourceCollectionRunSummaryHasRecordCount,
    sourceCollectionSummaryHasRecordCount,
    sourceCollectionRunSummaryHasAssignmentCounts,
    sourceCollectionCandidateListDataLoading,
    sourceCollectionRecordsDataLoading,
    sourceCollectionAssignmentsDataLoading,
    sourceCollectionCollectionProjection,
    sourceCollectionExtractionProjection,
    sourceCollectionCandidateProjection,
    sourceCollectionScreeningProjection,
    sourceCollectionGraphProjection,
    sourceCollectionMemoryProjection,
    sourceCollectionExcludedSourceCount,
    sourceCollectionStageSummaryCandidateCount,
    sourceCollectionCandidateProjectionFallbackCount,
    sourceCollectionProjectedCollectedCount,
    sourceCollectionProjectedCandidateCount,
    sourceCollectionProjectedAssessedCount,
    sourceCollectionProjectedApprovedCount,
    sourceCollectionDisplayedCandidateCount,
    sourceCollectionQueryCount,
    sourceCollectionPrimaryDataLoading,
    sourceCollectionSourceQualityLoading,
    sourceCollectionGraphDataLoading,
    sourceCollectionKnowledgeIngestionDataLoading,
    sourceCollectionActionInitialDataPending,
    sourceCollectionActionDataError,
    sourceCollectionSourceQualityDataError,
    sourceCollectionGraphDataError,
    sourceCollectionKnowledgeIngestionDataError,
    sourceCollectionScreeningDataLoading,
  };
}
