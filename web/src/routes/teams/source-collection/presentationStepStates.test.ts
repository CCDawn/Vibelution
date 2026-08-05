import { describe, expect, it } from "vitest";

import {
  buildSourceCollectionPipelineStepStates,
  sourceCollectionStepStatusText,
} from "./presentationStepStates";

describe("presentationStepStates (F3)", () => {
  it("maps step status labels", () => {
    expect(sourceCollectionStepStatusText("zh", "active")).toBe("进行中");
    expect(sourceCollectionStepStatusText("en", "failed")).toBe("failed");
  });

  it("marks screening done when exclusions allow proceed", () => {
    const bag = buildSourceCollectionPipelineStepStates({
      searchFallback: "idle",
      collectionProjection: null,
      screeningProjection: null,
      candidateProjection: null,
      graphProjection: null,
      memoryProjection: null,
      extractionCanProceedAfterExclusions: true,
      sourceQualityError: false,
      sourceQualityPending: false,
      runAssessedCount: 0,
      displayedCandidateCount: 2,
      searchOpenAssignmentCount: 0,
      recordOutputError: false,
      extractError: false,
      recordOutputPending: false,
      extractPending: false,
      hasRun: true,
      graphError: false,
      graphQueryError: false,
      graphPending: false,
      graphNodeCount: 0,
      runApprovedCount: 1,
      knowledgeQueryError: false,
      knowledgePrecheckError: false,
      knowledgeIngestError: false,
      knowledgePrecheckPending: false,
      knowledgeIngestPending: false,
      formalKnowledgeItemCount: 0,
      knowledgePendingReviewCount: 0,
      knowledgeStewardPackCount: 0,
      ingestCandidateCount: 0,
    });
    expect(bag.screeningStepState).toBe("done");
    expect(bag.candidateStepState).toBe("done");
    expect(bag.graphFallbackStepState).toBe("pending");
  });
});
