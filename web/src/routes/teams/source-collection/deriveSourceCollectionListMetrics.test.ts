import { describe, expect, it } from "vitest";

import { deriveSourceCollectionListMetrics } from "./deriveSourceCollectionListMetrics";

describe("deriveSourceCollectionListMetrics", () => {
  it("computes empty-run baseline metrics without throwing", () => {
    const metrics = deriveSourceCollectionListMetrics({
      lang: "zh",
      researchWorkflowTeamSelected: true,
      selectedSourceCollectionRunEffectiveId: "run-1",
      sourceCollectionSourceFilter: "all",
      sourceCollectionRecords: [],
      sourceCollectionAssignments: [],
      sourceCollectionRunStatus: null,
      sourceCollectionSummaryCounts: {},
      sourceCollectionRecordsQuery: {},
      sourceCollectionAssignmentsQuery: {},
      sourceCollectionRunStatusQuery: {},
      sourceCollectionSummaryQuery: {},
      sourceCollectionRunsQuery: {},
      teamWorkflowCandidatesQuery: {},
      teamWorkflowSourceQualityStatusQuery: {},
      teamWorkflowCandidateGraphQuery: {},
      teamWorkflowKnowledgeIngestionStatusQuery: {},
      teamWorkflowSourceQualityStatus: null,
      teamWorkflowCandidateListEnabled: true,
      sourceCollectionNeedsCandidateList: true,
      sourceCollectionFindingDetailsVisible: true,
      sourceCollectionWorkspaceSelected: true,
      teamWorkflowSourceQualityEnabled: false,
      teamWorkflowGraphEnabled: false,
      teamWorkflowKnowledgeIngestionEnabled: false,
      sourceCollectionRunCandidates: [],
      sourceCollectionStageCardById: new Map(),
      sourceCollectionStageRound: null,
      sourceCollectionSearchPlanRef: null,
      selectedTeamStartSourceCollectionResult: null,
    });
    expect(metrics.sourceCollectionCollectedCount).toBe(0);
    expect(metrics.sourceCollectionDisplayedCandidateCount).toBe(0);
    expect(metrics.sourceCollectionScreeningDataLoading).toBeTypeOf("boolean");
  });
});
