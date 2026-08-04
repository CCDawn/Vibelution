import { describe, expect, it, vi } from "vitest";

import { buildSourceCollectionExtractionRecoveryBag } from "./extractionRecoveryBag";

describe("buildSourceCollectionExtractionRecoveryBag", () => {
  it("normalizes counters and boolean flags while preserving actions", () => {
    const extract = vi.fn();
    const screen = vi.fn();
    const advance = vi.fn();
    const bag = buildSourceCollectionExtractionRecoveryBag({
      candidateProjection: null,
      sourceCollectionRawRecordCount: -3 as unknown as number,
      sourceCollectionRunApprovedCount: Number.NaN as unknown as number,
      sourceCollectionDisplayedCandidateCount: 4,
      sourceCollectionPrimaryDataLoading: false,
      sourceCollectionLoadingText: "loading",
      sourceCollectionCandidateStepState: "active",
      sourceCollectionExtractionExcludedRecoveryState: {},
      runSourceCollectionCandidateExtractionAction: extract,
      sourceCollectionCandidateExtractionActionReadiness: { disabled: false },
      runSourceCollectionScreeningAction: screen,
      sourceCollectionScreeningActionReadiness: { disabled: true },
      sourceCollectionScreeningButtonText: "Review",
      sourceCollectionRunPendingScreeningCountText: "2",
      needsAgentMaterial: 1 as unknown as boolean,
      pendingScreeningCount: -2 as unknown as number,
      pendingImportCount: 5,
      canProceedAfterExclusions: 0 as unknown as boolean,
      qualityReviewPending: true,
      advanceToRelations: advance,
      unverifiableCandidateCount: -1 as unknown as number,
    });

    expect(bag.sourceCollectionRawRecordCount).toBe(0);
    expect(bag.sourceCollectionRunApprovedCount).toBe(0);
    expect(bag.sourceCollectionDisplayedCandidateCount).toBe(4);
    expect(bag.pendingScreeningCount).toBe(0);
    expect(bag.pendingImportCount).toBe(5);
    expect(bag.unverifiableCandidateCount).toBe(0);
    expect(bag.needsAgentMaterial).toBe(true);
    expect(bag.canProceedAfterExclusions).toBe(false);
    expect(bag.qualityReviewPending).toBe(true);
    expect(bag.runSourceCollectionCandidateExtractionAction).toBe(extract);
    expect(bag.runSourceCollectionScreeningAction).toBe(screen);
    expect(bag.advanceToRelations).toBe(advance);
  });
});
