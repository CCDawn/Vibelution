import { describe, expect, it } from "vitest";

import { deriveSourceCollectionSummaryProjection } from "./deriveSourceCollectionSummaryProjection";

describe("deriveSourceCollectionSummaryProjection", () => {
  it("projects empty queries into baseline SC summary bag", () => {
    const projection = deriveSourceCollectionSummaryProjection({
      teamWorkflowCandidateGraphQueryData: { candidates: [] },
      sourceCollectionSummaryQueryData: null,
      sourceCollectionRecordsQueryData: { records: [] },
      sourceCollectionAssignmentsQueryData: { assignments: [] },
      sourceCollectionRunStatusQueryData: null,
      selectedSourceCollectionRun: null,
      selectedSourceCollectionRunEffectiveId: "run-1",
      researchStagePhases: [],
      researchStageRoundStatus: null,
      aiSearchRunsQueryData: { runs: [] },
      researchLoopTemplatesQueryData: null,
      researchLoopStatusQueryData: null,
      experimentPlanningStatusQueryData: null,
    });
    expect(projection.sourceCollectionActionRunId).toBe("run-1");
    expect(projection.sourceCollectionRecords).toEqual([]);
    expect(projection.sourceCollectionAssignments).toEqual([]);
    expect(projection.aiSearchRuns).toEqual([]);
  });
});
