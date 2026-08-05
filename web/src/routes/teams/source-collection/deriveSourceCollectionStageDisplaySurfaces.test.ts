import { describe, expect, it } from "vitest";

import { deriveSourceCollectionStageDisplaySurfaces } from "./deriveSourceCollectionStageDisplaySurfaces";

describe("deriveSourceCollectionStageDisplaySurfaces", () => {
  it("marks finding/extraction pending while data loads", () => {
    const surfaces = deriveSourceCollectionStageDisplaySurfaces({
      lang: "zh",
      loadingText: "加载中",
      dataSyncText: "同步中",
      recordsDataLoading: true,
      assignmentsDataLoading: false,
      primaryDataLoading: true,
      screeningDataLoading: false,
      graphDataLoading: false,
      sourceQualityLoading: false,
      knowledgeIngestionDataLoading: false,
      searchStepState: "done",
      extractionStepState: "done",
      graphStepState: "done",
      memoryStepState: "done",
      projectedCollectedCount: 0,
      displayedCandidateCount: 0,
      projectedCandidateCount: 0,
      projectedAssessedCount: 0,
      projectedApprovedCount: 0,
      currentCandidateCount: 0,
      extractionAgentMaterialCount: 0,
      runPendingScreeningCount: 0,
      projectedFormalKnowledgeCount: 0,
    });
    expect(surfaces.sourceCollectionFindingDisplayState).toBe("pending");
    expect(surfaces.sourceCollectionExtractionDisplayState).toBe("pending");
    expect(surfaces.sourceCollectionRelationsDisplayState).toBe("done");
    expect(surfaces.sourceCollectionIngestionReadyForExperiment).toBe(false);
  });

  it("formats extraction loading metrics when candidates exist", () => {
    const surfaces = deriveSourceCollectionStageDisplaySurfaces({
      lang: "en",
      loadingText: "Loading",
      dataSyncText: "Syncing",
      recordsDataLoading: false,
      assignmentsDataLoading: false,
      primaryDataLoading: false,
      screeningDataLoading: false,
      graphDataLoading: false,
      sourceQualityLoading: false,
      knowledgeIngestionDataLoading: false,
      searchStepState: "done",
      extractionStepState: "done",
      graphStepState: "done",
      memoryStepState: "done",
      projectedCollectedCount: 2,
      displayedCandidateCount: 3,
      projectedCandidateCount: 4,
      projectedAssessedCount: 1,
      projectedApprovedCount: 1,
      currentCandidateCount: 3,
      extractionAgentMaterialCount: 2,
      runPendingScreeningCount: 3,
      projectedFormalKnowledgeCount: 1,
    });
    expect(surfaces.sourceCollectionExtractionLoadingMetric).toContain("1/4 processed");
    expect(surfaces.sourceCollectionExtractionMaterialMetric).toContain("need material");
    expect(surfaces.sourceCollectionIngestionReadyForExperiment).toBe(true);
    expect(surfaces.sourceCollectionSourceSyncStatusText).toBe("Syncing");
  });
});
