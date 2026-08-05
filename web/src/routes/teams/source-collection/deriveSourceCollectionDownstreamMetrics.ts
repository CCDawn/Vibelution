/**
 * Pure graph/memory/ingest downstream metrics for SC presentation.
 * Phase R2-m extract from useSourceCollectionPresentationCore (behavior-conserving).
 */
import {
  sourceCollectionStageProjectionCount,
  type SourceCollectionStageCardProjection,
} from "./stageProjection";

export type DeriveSourceCollectionDownstreamMetricsInput = {
  teamWorkflowSourceQualityStatus: {
    summary?: {
      approvedSourceCandidateCount?: number;
    };
  } | null | undefined;
  sourceCollectionSummaryCounts: Record<string, unknown>;
  teamWorkflowCandidateGraph: {
    summary?: {
      nodeCount?: number;
      edgeCount?: number;
    };
  } | null | undefined;
  teamWorkflowKnowledgeIngestionStatus: {
    summary?: {
      stewardPackCandidateCount?: number;
      pendingKnowledgeReviewCandidateCount?: number;
      formalKnowledgeItemCount?: number;
    };
    knowledgeBases?: Array<{
      scopedKnowledgeBaseId?: string;
      knowledgeBaseId?: string;
    }>;
  } | null | undefined;
  graphProjection: SourceCollectionStageCardProjection | null | undefined;
  memoryProjection: SourceCollectionStageCardProjection | null | undefined;
  runApprovedCount: number;
  displayedCandidateCount: number;
};

export function deriveSourceCollectionDownstreamMetrics(
  input: DeriveSourceCollectionDownstreamMetricsInput,
) {
  const {
    teamWorkflowSourceQualityStatus,
    sourceCollectionSummaryCounts,
    teamWorkflowCandidateGraph,
    teamWorkflowKnowledgeIngestionStatus,
    graphProjection,
    memoryProjection,
    runApprovedCount,
    displayedCandidateCount,
  } = input;

  const sourceCollectionApprovedCount =
    teamWorkflowSourceQualityStatus?.summary?.approvedSourceCandidateCount
    ?? (sourceCollectionSummaryCounts.approvedSourceCandidateCount as number | undefined)
    ?? 0;
  const candidateGraphNodeCount =
    teamWorkflowCandidateGraph?.summary?.nodeCount
    ?? (sourceCollectionSummaryCounts.graphNodeCount as number | undefined)
    ?? 0;
  const candidateGraphEdgeCount = teamWorkflowCandidateGraph?.summary?.edgeCount ?? 0;
  const knowledgeStewardPackCount =
    teamWorkflowKnowledgeIngestionStatus?.summary?.stewardPackCandidateCount
    ?? (sourceCollectionSummaryCounts.stewardPackCount as number | undefined)
    ?? 0;
  const knowledgePendingReviewCount =
    teamWorkflowKnowledgeIngestionStatus?.summary?.pendingKnowledgeReviewCandidateCount ?? 0;
  const formalKnowledgeItemCount =
    teamWorkflowKnowledgeIngestionStatus?.summary?.formalKnowledgeItemCount
    ?? (sourceCollectionSummaryCounts.formalKnowledgeSyncCount as number | undefined)
    ?? 0;
  const sourceCollectionProjectedGraphNodeCount = sourceCollectionStageProjectionCount(
    graphProjection,
    "artifact",
    candidateGraphNodeCount,
  );
  const sourceCollectionProjectedGraphEdgeCount = sourceCollectionStageProjectionCount(
    graphProjection,
    "output",
    candidateGraphEdgeCount,
  );
  const sourceCollectionProjectedStewardPackCount = sourceCollectionStageProjectionCount(
    memoryProjection,
    "artifact",
    knowledgeStewardPackCount,
  );
  const sourceCollectionProjectedFormalKnowledgeCount = sourceCollectionStageProjectionCount(
    memoryProjection,
    "output",
    formalKnowledgeItemCount,
  );
  const sourceCollectionDefaultKnowledgeBaseId =
    teamWorkflowKnowledgeIngestionStatus?.knowledgeBases?.[0]?.scopedKnowledgeBaseId
    ?? teamWorkflowKnowledgeIngestionStatus?.knowledgeBases?.[0]?.knowledgeBaseId
    ?? "";
  const sourceCollectionPrecheckCandidateCount = Math.max(sourceCollectionApprovedCount, runApprovedCount);
  const sourceCollectionIngestCandidateCount = Math.max(
    sourceCollectionPrecheckCandidateCount,
    displayedCandidateCount,
  );
  const sourceCollectionCanBuildGraph = runApprovedCount > 0 || displayedCandidateCount > 0;

  return {
    sourceCollectionApprovedCount,
    candidateGraphNodeCount,
    candidateGraphEdgeCount,
    knowledgeStewardPackCount,
    knowledgePendingReviewCount,
    formalKnowledgeItemCount,
    sourceCollectionProjectedGraphNodeCount,
    sourceCollectionProjectedGraphEdgeCount,
    sourceCollectionProjectedStewardPackCount,
    sourceCollectionProjectedFormalKnowledgeCount,
    sourceCollectionDefaultKnowledgeBaseId,
    sourceCollectionPrecheckCandidateCount,
    sourceCollectionIngestCandidateCount,
    sourceCollectionCanBuildGraph,
  };
}
