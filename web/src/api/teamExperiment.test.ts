import { describe, beforeEach, expect, it, vi } from "vitest";

import { resetControlTokenForTests } from "./client";
import {
  fetchChallengeCatalogReadiness,
  fetchChallengeCupCatalogOverview,
} from "./teamExperiment";
import apiSource from "./teamExperiment.ts?raw";
import mutationsSource from "../routes/teams/useTeamExperimentLoopMutations.ts?raw";
import resourcesSource from "../routes/teams/useResearchWorkflowResources.ts?raw";
import secondarySource from "../routes/teams/useTeamResearchSecondaryQueries.ts?raw";

describe("team experiment API", () => {
  beforeEach(() => resetControlTokenForTests());

  it("owns experiment status, catalog, candidate, and write transports", () => {
    expect(apiSource).toContain("export function fetchExperimentPlanningStatus");
    expect(apiSource).toContain("export function fetchChallengeSubmissionReadiness");
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

  it("exposes typed Challenge Cup catalog/token transports with canonical URLs and no DEV controls", () => {
    expect(apiSource).toContain("export function fetchChallengeCupCatalogOverview");
    expect(apiSource).toContain("export function fetchChallengeCupTokenUsage");
    expect(apiSource).toContain("workflow-orchestration/challenge-program/catalog-overview");
    expect(apiSource).toContain("workflow-orchestration/challenge-program/token-usage");
    expect(apiSource).toContain("workflow-orchestration/challenge-program/submission-readiness");
    expect(apiSource).toContain("export function fetchChallengeCatalogReadiness");
    expect(apiSource).toContain("workflow-orchestration/challenge-program/catalog-readiness");
    expect(apiSource).not.toContain("dev-controls");
  });

  it("fetches the catalog overview with team segment encoded", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ header: "X-Vibelution-Control-Token", controlToken: "t" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }))
      .mockResolvedValue(new Response(JSON.stringify({ schemaVersion: 1, teamId: "team a/b", questions: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }));
    vi.stubGlobal("fetch", fetchMock);

    await fetchChallengeCupCatalogOverview("team a/b");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/teams/team%20a%2Fb/workflow-orchestration/challenge-program/catalog-overview",
      expect.objectContaining({ signal: undefined }),
    );
    vi.unstubAllGlobals();
  });

  it("fetches formal catalog readiness independently from submission readiness", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ header: "X-Vibelution-Control-Token", controlToken: "t" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }))
      .mockResolvedValue(new Response(JSON.stringify({
        schemaVersion: 1,
        reportKind: "CatalogHypothesisFlowReadinessReport",
        status: "NOT_READY",
        realCampaignAllowed: false,
        evidence: {},
        blockers: ["real_batch_missing"],
        catalogResultSet: { counts: {} },
      }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }));
    vi.stubGlobal("fetch", fetchMock);

    await fetchChallengeCatalogReadiness("team a/b");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/teams/team%20a%2Fb/workflow-orchestration/challenge-program/catalog-readiness",
      expect.objectContaining({ signal: undefined }),
    );
    vi.unstubAllGlobals();
  });
});
