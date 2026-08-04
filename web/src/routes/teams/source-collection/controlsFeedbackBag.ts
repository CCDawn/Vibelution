/**
 * Controls rail metrics + mutation feedback bags for SC side panel.
 */
export type SourceCollectionControlsMetricsBag = {
  sourceCollectionDisplayedCandidateCountText: string;
  sourceCollectionProjectedAssessedCountText: string;
  sourceCollectionProjectedApprovedCountText: string;
  sourceCollectionRunPendingScreeningCountText: string;
  candidateGraphNodeCount: number | string;
  candidateGraphEdgeCount: number | string;
  sourceCollectionPrecheckCandidateCount: number | string;
  knowledgePendingReviewCount: number | string;
  formalKnowledgeItemCount: number | string;
};

export type SourceCollectionControlsFeedbackBag = {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedTeamKnowledgeCollectionIngestResult: any;
  selectedTeamKnowledgeCollectionIngestError: Error | null;
  selectedTeamStartSourceCollectionError: Error | null;
  selectedTeamRecordSourceCollectionOutputError: Error | null;
  selectedTeamExecuteSourceCollectionSearchError: Error | null;
  selectedTeamStartSourceCollectionStageTaskError: Error | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedTeamExecuteSourceCollectionSearchResult: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedTeamRecordSourceCollectionOutputResult: any;
};

export function buildSourceCollectionControlsMetricsBag(
  input: SourceCollectionControlsMetricsBag,
): SourceCollectionControlsMetricsBag {
  return { ...input };
}

export function buildSourceCollectionControlsFeedbackBag(
  input: SourceCollectionControlsFeedbackBag,
): SourceCollectionControlsFeedbackBag {
  return { ...input };
}
