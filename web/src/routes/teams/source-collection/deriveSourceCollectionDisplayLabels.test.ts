import { describe, expect, it } from "vitest";

import { deriveSourceCollectionDisplayLabels } from "./deriveSourceCollectionDisplayLabels";

describe("deriveSourceCollectionDisplayLabels", () => {
  it("formats zh count labels when data is ready", () => {
    const labels = deriveSourceCollectionDisplayLabels({
      lang: "zh",
      loadingText: "加载中",
      dataSyncText: "同步中",
      recordsDataLoading: false,
      assignmentsDataLoading: false,
      primaryDataLoading: false,
      screeningDataLoading: false,
      collectedCount: 3,
      projectedCollectedCount: 3,
      searchOpenAssignmentCount: 1,
      downstreamOpenAssignmentCount: 0,
      queryCount: 2,
      assignmentsLength: 1,
      searchPlanQueryCount: 2,
      startResultSearchPlanQueryCount: null,
      displayedCandidateCount: 4,
      projectedCandidateCount: 4,
      projectedAssessedCount: 1,
      projectedApprovedCount: 1,
      runReviewableCandidateCount: 4,
      runCandidateCount: 4,
      runAssessedCount: 1,
      candidateProjection: null,
      candidateFilterCounts: {
        all: 4,
        pdf: 0,
        paper_web: 0,
        dataset: 0,
        local_file: 0,
        missing: 0,
      },
    });
    expect(labels.sourceCollectionCollectedCountText).toBe("3");
    expect(labels.sourceCollectionCollectedRunSummaryText).toBe("3 条资料");
    expect(labels.sourceCollectionRunPendingScreeningCount).toBe(3);
    expect(labels.sourceCollectionQueryDataLoading).toBe(false);
  });

  it("shows loading text while records are pending", () => {
    const labels = deriveSourceCollectionDisplayLabels({
      lang: "en",
      loadingText: "Loading",
      dataSyncText: "Syncing",
      recordsDataLoading: true,
      assignmentsDataLoading: true,
      primaryDataLoading: true,
      screeningDataLoading: true,
      collectedCount: 0,
      projectedCollectedCount: 0,
      searchOpenAssignmentCount: 0,
      downstreamOpenAssignmentCount: 0,
      queryCount: 0,
      assignmentsLength: 0,
      searchPlanQueryCount: null,
      startResultSearchPlanQueryCount: null,
      displayedCandidateCount: 0,
      projectedCandidateCount: 0,
      projectedAssessedCount: 0,
      projectedApprovedCount: 0,
      runReviewableCandidateCount: 0,
      runCandidateCount: 0,
      runAssessedCount: 0,
      candidateProjection: null,
      candidateFilterCounts: {
        all: 0,
        pdf: 0,
        paper_web: 0,
        dataset: 0,
        local_file: 0,
        missing: 0,
      },
    });
    expect(labels.sourceCollectionCollectedCountText).toBe("Loading");
    expect(labels.sourceCollectionQueryDataLoading).toBe(true);
    expect(labels.sourceCollectionQueryCountText).toBe("Loading");
  });
});
