import { describe, expect, it } from "vitest";

import {
  buildSourceCollectionQualityBatchFeedback,
  buildSourceCollectionWriteMutationSurface,
  buildTeamsRouteMutationSurface,
  teamScopedMutationCandidateId,
  teamScopedMutationSurface,
} from "./teamMutationSurface";

describe("teamMutationSurface", () => {
  it("scopes pending/error/result to the active team", () => {
    const mutation = {
      isPending: true,
      error: new Error("boom"),
      data: { ok: true },
      variables: { teamId: "team-a" },
    };
    expect(teamScopedMutationSurface(mutation, "team-a")).toEqual({
      forTeam: true,
      pending: true,
      error: mutation.error,
      result: { ok: true },
    });
    expect(teamScopedMutationSurface(mutation, "team-b")).toEqual({
      forTeam: false,
      pending: false,
      error: null,
      result: undefined,
    });
  });

  it("returns candidate id only while pending for the active team", () => {
    const mutation = {
      isPending: true,
      error: null,
      data: undefined,
      variables: { teamId: "team-a", candidateId: "cand-1" },
    };
    expect(teamScopedMutationCandidateId(mutation, "team-a")).toBe("cand-1");
    expect(teamScopedMutationCandidateId(mutation, "team-b")).toBe("");
  });

  it("builds the historical TeamsRoute mutation surface bag", () => {
    const idle = { isPending: false, error: null, data: undefined, variables: undefined };
    const surface = buildTeamsRouteMutationSurface({
      teamId: "team-a",
      resetResearchProjectSourceCollection: idle,
      startResearchStageRound: {
        isPending: true,
        error: null,
        data: { stage: 1 },
        variables: { teamId: "team-a" },
      },
      createExperimentPlan: idle,
      materializeEngineeringProxyHypothesis: idle,
      completeScientificHypothesisFromDesign: idle,
      reviewExperimentHypothesis: idle,
      createExperimentHypothesisRevision: idle,
      freezeExperimentDesign: idle,
      registerExperimentBaselineArtifact: idle,
      runExperimentSmoke: idle,
      registerExperimentSmokeResult: idle,
      registerExperimentFullRunResult: idle,
      requestExperimentKnowledgeIngestion: idle,
      createResearchLoop: idle,
      recordResearchLoopEvidence: idle,
      recordResearchLoopDecision: idle,
      startSourceCollectionRun: idle,
      startSourceCollectionStageSessionTask: {
        isPending: true,
        error: null,
        data: undefined,
        variables: { teamId: "team-a", stageId: "finding" },
      },
      recordSourceCollectionOutput: idle,
      executeSourceCollectionSearch: idle,
      extractSourceCollectionCandidates: {
        isPending: false,
        error: null,
        data: { runId: "run-1" },
        variables: { teamId: "team-a" },
      },
      openSourceCollectionStorage: idle,
      startAiSearchRun: idle,
      researchStageProjectAgentStarting: true,
      selectedSourceCollectionRunEffectiveId: "run-1",
    });

    expect(surface.selectedTeamStartResearchStagePending).toBe(true);
    expect(surface.selectedTeamStartResearchStageResult).toEqual({ stage: 1 });
    expect(surface.sourceCollectionStageSessionTaskPendingStageId).toBe("finding");
    expect(surface.selectedTeamExtractSourceCollectionCandidatesResult).toEqual({ runId: "run-1" });
  });

  it("builds SC write mutation surface with knowledge work-run and quality feedback", () => {
    const idle = { isPending: false, error: null, data: undefined, variables: undefined };
    const write = buildSourceCollectionWriteMutationSurface({
      teamId: "team-a",
      selectedSourceCollectionRunEffectiveId: "run-1",
      buildCandidateGraph: {
        isPending: true,
        error: null,
        data: undefined,
        variables: { teamId: "team-a" },
      },
      runKnowledgeIngestionPrecheck: idle,
      runKnowledgeCollectionCompletion: idle,
      planPaperNoteChunks: idle,
      assessSourceQuality: idle,
      assessSourceQualityBatch: {
        isPending: false,
        isSuccess: true,
        error: null,
        data: {
          summary: {
            approvedCandidateCount: 2,
            needsRevisionCandidateCount: 1,
            rejectedCandidateCount: 0,
            assessedCandidateCount: 3,
            skippedCandidateCount: 0,
          },
        },
        variables: { teamId: "team-a" },
      },
      knowledgeIngestionActiveWorkRun: { sourceRunId: "run-1", status: "running" },
      knowledgeIngestionLatestWorkRun: null,
      lang: "zh",
    });
    expect(write.selectedTeamBuildCandidateGraphPending).toBe(true);
    expect(write.selectedTeamKnowledgeCollectionIngestPending).toBe(true);
    expect(write.selectedTeamSourceQualityBatchResult).toBeTruthy();
    expect(write.sourceCollectionQualityBatchFeedback).toContain("质量审查完成");
    expect(buildSourceCollectionQualityBatchFeedback(null, "en")).toBeNull();
  });
});
