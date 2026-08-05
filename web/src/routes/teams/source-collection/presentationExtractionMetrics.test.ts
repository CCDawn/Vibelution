import { describe, expect, it } from "vitest";

import {
  deriveSourceCollectionExtractionRecoveryMetrics,
  sourceCollectionStageFocusLabel,
} from "./presentationExtractionMetrics";

describe("presentationExtractionMetrics (F3)", () => {
  it("stage focus labels follow priority", () => {
    expect(sourceCollectionStageFocusLabel({
      lang: "zh",
      hasRun: false,
      searchOpenAssignmentCount: 1,
      downstreamOpenAssignmentCount: 1,
      runPendingScreeningCount: 1,
      displayedCandidateCount: 1,
    })).toBe("尚未启动");
    expect(sourceCollectionStageFocusLabel({
      lang: "en",
      hasRun: true,
      searchOpenAssignmentCount: 2,
      downstreamOpenAssignmentCount: 0,
      runPendingScreeningCount: 0,
      displayedCandidateCount: 0,
    })).toBe("continue search");
    expect(sourceCollectionStageFocusLabel({
      lang: "zh",
      hasRun: true,
      searchOpenAssignmentCount: 0,
      downstreamOpenAssignmentCount: 0,
      runPendingScreeningCount: 0,
      displayedCandidateCount: 3,
    })).toBe("准备实验");
  });

  it("derives pending import and empty recovery defaults", () => {
    const metrics = deriveSourceCollectionExtractionRecoveryMetrics({
      lang: "zh",
      candidateProjection: null,
      reviewableRunCandidates: [],
      rawRecordCount: 10,
      displayedCandidateCount: 4,
      runNeedsRevisionCount: 0,
      projectedApprovedCount: 0,
      runPendingScreeningCount: 0,
      excludedSourceCount: 0,
      hasCurrentCandidates: false,
    });
    expect(metrics.pendingCandidateImportCount).toBe(6);
    expect(metrics.sourceVerificationCount).toBe(0);
    expect(metrics.unverifiableCandidateIds).toEqual([]);
    expect(metrics.needsAgentMaterial).toBe(false);
  });
});
