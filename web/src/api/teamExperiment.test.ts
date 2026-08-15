import { describe, expect, it } from "vitest";

import apiSource from "./teamExperiment.ts?raw";
import mutationsSource from "../routes/teams/useTeamExperimentLoopMutations.ts?raw";
import resourcesSource from "../routes/teams/useResearchWorkflowResources.ts?raw";
import secondarySource from "../routes/teams/useTeamResearchSecondaryQueries.ts?raw";

describe("team experiment API", () => {
  it("owns experiment status, catalog, candidate, and write transports", () => {
    expect(apiSource).toContain("export function fetchExperimentPlanningStatus");
    expect(apiSource).toContain("export function fetchExperimentMethodCatalog");
    expect(apiSource).toContain("export function fetchTeamWorkflowCandidates");
    expect(apiSource).toContain("export function createTeamExperimentPlan");
    expect(apiSource).toContain("export function freezeTeamExperimentDesign");
    expect(apiSource).toContain("export function registerTeamExperimentBaselineArtifact");
    expect(apiSource).toContain("export function registerTeamExperimentSmokeResult");
    expect(apiSource).toContain("export function registerTeamExperimentFullRunResult");
    expect(apiSource).toContain("export function requestTeamExperimentKnowledgeIngestion");
    expect(apiSource).toContain("/workflow-orchestration/experiments/status");
    expect(apiSource).toContain("/workflow-orchestration/experiments/methods");
    expect(apiSource).toContain("/workflow-orchestration/experiments/plan");
    expect(apiSource).toContain("/baseline-artifact");
    expect(apiSource).toContain("/smoke-result");
    expect(apiSource).toContain("/full-run-result");
    expect(apiSource).toContain("/knowledge-ingestion-request");
    expect(apiSource).toContain("/workflow-orchestration/candidates");
  });

  it("keeps unused typed experiment routes behind named transports", () => {
    expect(apiSource).toContain("export function fetchChallengeQuestionRunStatus");
    expect(apiSource).toContain("export function registerChallengeQuestionRun");
    expect(apiSource).toContain("export function publishChallengeQuestionRun");
    expect(apiSource).toContain("export function reviewChallengeQuestionRun");
    expect(apiSource).toContain("export function prepareTeamExperimentFullRun");
    expect(apiSource).toContain("export function executeTeamExperimentFullRun");
    expect(apiSource).toContain("export function retryStageRoundCoordination");
    expect(apiSource).toContain("export function retryStageRoundMemoryRecord");
    expect(apiSource).toContain("export function fetchTeamWorkflowCandidateValidation");
  });

  it("keeps hooks free of extracted experiment paths", () => {
    expect(secondarySource).toContain("fetchExperimentPlanningStatus<");
    expect(secondarySource).toContain("fetchExperimentMethodCatalog<");
    expect(secondarySource).not.toContain("/workflow-orchestration/experiments/status");
    expect(secondarySource).not.toContain("/workflow-orchestration/experiments/methods");
    expect(mutationsSource).toContain("createTeamExperimentPlan<");
    expect(mutationsSource).toContain("freezeTeamExperimentDesign<");
    expect(mutationsSource).toContain("registerTeamExperimentBaselineArtifact<");
    expect(mutationsSource).toContain("registerTeamExperimentSmokeResult<");
    expect(mutationsSource).toContain("registerTeamExperimentFullRunResult<");
    expect(mutationsSource).toContain("requestTeamExperimentKnowledgeIngestion<");
    expect(mutationsSource).not.toContain("/baseline-artifact");
    expect(mutationsSource).not.toContain("/smoke-result");
    expect(mutationsSource).not.toContain("/full-run-result");
    expect(mutationsSource).not.toContain("/knowledge-ingestion-request");
    expect(resourcesSource).toContain("fetchTeamWorkflowCandidates<");
    expect(resourcesSource).not.toContain("/workflow-orchestration/candidates?");
  });
});
