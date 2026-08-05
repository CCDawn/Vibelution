import { describe, expect, it } from "vitest";

import { deriveSourceCollectionSelectionPresentation } from "./deriveSourceCollectionSelectionPresentation";

describe("deriveSourceCollectionSelectionPresentation", () => {
  it("builds empty finding options and launch gates from draft topic", () => {
    const selection = deriveSourceCollectionSelectionPresentation({
      lang: "zh",
      teamId: "team-1",
      effectiveTeamId: "team-1",
      sourceCollectionRuns: [{ runId: "run-1", title: "t" }],
      sourceCollectionAssignments: [],
      sourceCollectionOutputDraft: {
        assignmentId: "",
        sourceType: "",
        title: "",
        sourceRef: "",
        rawLocation: "",
        summary: "",
        notes: "",
      },
      sourceCollectionDraft: {
        title: "",
        topic: "topic",
        goal: "",
        querySeeds: "",
        inputRefs: "",
        searchLanguages: "",
        sourceTypes: "",
        maxResultsPerQuery: 10,
        collectionMode: "mixed",
        localScanRoots: "",
      },
      activeSourceCollectionResearchProjectId: "proj-1",
      selectedSourceCollectionRun: null,
      sourceCollectionSearchPlanRef: null,
      selectedTeamStartSourceCollectionResult: null,
      selectedTeamStartResearchStageResult: null,
      selectedTeamExecuteSourceCollectionSearchResult: null,
      runtimeSummaryData: undefined,
      selectedSourceCollectionRunEffectiveId: "run-1",
      sourceCollectionSummary: null,
      teamWorkflowCandidates: [],
      selectedSourceCollectionCandidateId: "",
    });
    expect(selection.sourceCollectionCanStart).toBe(true);
    expect(selection.researchStageCanLaunch).toBe(true);
    expect(selection.sourceCollectionResetAvailable).toBe(true);
    expect(selection.sourceCollectionFindingRunOptions).toHaveLength(1);
    expect(selection.selectedSourceCollectionSearchAccepted).toBe(false);
    expect(selection.sourceManifestCandidates).toEqual([]);
  });
});
