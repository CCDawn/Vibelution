import { describe, beforeEach, expect, it, vi } from "vitest";

import { resetControlTokenForTests } from "./client";
import {
  fetchChallengeCupCatalogOverview,
  fetchChallengeCupDevControlSnapshot,
  runChallengeCupDevBatch,
  runChallengeCupDevReadiness,
} from "./teamExperiment";
import apiSource from "./teamExperiment.ts?raw";
import challengeCupTypesSource from "./types/challengeCup.ts?raw";
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

  it("exposes typed Challenge Cup DEV control transports with canonical URLs", () => {
    expect(apiSource).toContain("export function fetchChallengeCupDevControlSnapshot");
    expect(apiSource).toContain("export function fetchChallengeCupCatalogOverview");
    expect(apiSource).toContain("export function fetchChallengeCupTokenUsage");
    expect(apiSource).toContain("export function runChallengeCupDevReadiness");
    expect(apiSource).toContain("export function runChallengeCupDevBatch");
    expect(apiSource).toContain("workflow-orchestration/challenge-program/dev-controls");
    expect(apiSource).toContain("workflow-orchestration/challenge-program/catalog-overview");
    expect(apiSource).toContain("workflow-orchestration/challenge-program/token-usage");
    expect(apiSource).toContain("workflow-orchestration/challenge-program/submission-readiness");
    expect(apiSource).toContain("workflow-orchestration/challenge-program/dev-controls/readiness");
    expect(apiSource).toContain("workflow-orchestration/challenge-program/dev-controls/batches/");
    expect(apiSource).toContain("dev-controls/batches/${encodeURIComponent(planId)}");
    expect(apiSource).toContain("encodeURIComponent(teamId)");
  });

  it("requires an explicit retryFailed flag on every batch run request", () => {
    expect(challengeCupTypesSource).toContain("retryFailed: boolean");
  });

  it("fetches the DEV control snapshot with team segment encoded", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ schemaVersion: 1, teamId: "team a/b" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);

    await fetchChallengeCupDevControlSnapshot("team a/b");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/teams/team%20a%2Fb/workflow-orchestration/challenge-program/dev-controls",
      expect.objectContaining({ signal: undefined }),
    );
    vi.unstubAllGlobals();
  });

  it("fetches the catalog overview with team segment encoded", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ schemaVersion: 1, teamId: "team a/b", questions: [] }), {
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

  it("posts DEV readiness with a dev-mode payload", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ header: "X-Vibelution-Control-Token", controlToken: "test-token" }),
      })
      .mockResolvedValueOnce(new Response(JSON.stringify({ schemaVersion: 1, cleanedUp: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }));
    vi.stubGlobal("fetch", fetchMock);

    await runChallengeCupDevReadiness("team-1", { mode: "dev" });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1]).toEqual([
      "/api/teams/team-1/workflow-orchestration/challenge-program/dev-controls/readiness",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ mode: "dev" }),
      }),
    ]);
    vi.unstubAllGlobals();
  });

  it("posts dev-1 / dev-5 batches with bounded maxItems and explicit retryFailed=false", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ header: "X-Vibelution-Control-Token", controlToken: "test-token" }),
      })
      .mockResolvedValueOnce(new Response(JSON.stringify({ schemaVersion: 1, planId: "dev-5" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }));
    vi.stubGlobal("fetch", fetchMock);

    await runChallengeCupDevBatch("team 1/2", "dev 5/next", { maxItems: 2, retryFailed: false });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1]).toEqual([
      "/api/teams/team%201%2F2/workflow-orchestration/challenge-program/dev-controls/batches/dev%205%2Fnext",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ maxItems: 2, retryFailed: false }),
      }),
    ]);
    vi.unstubAllGlobals();
  });

  it("resumes a dev-5 batch with a null maxItems payload and explicit retryFailed=false", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ header: "X-Vibelution-Control-Token", controlToken: "test-token" }),
      })
      .mockResolvedValueOnce(new Response(JSON.stringify({ schemaVersion: 1, planId: "dev-5" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }));
    vi.stubGlobal("fetch", fetchMock);

    await runChallengeCupDevBatch("team-1", "dev-5", { maxItems: null, retryFailed: false });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1]).toEqual([
      "/api/teams/team-1/workflow-orchestration/challenge-program/dev-controls/batches/dev-5",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ maxItems: null, retryFailed: false }),
      }),
    ]);
    vi.unstubAllGlobals();
  });

  it("posts a repair batch with explicit retryFailed=true", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ header: "X-Vibelution-Control-Token", controlToken: "test-token" }),
      })
      .mockResolvedValueOnce(new Response(JSON.stringify({ schemaVersion: 1, planId: "dev-1" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }));
    vi.stubGlobal("fetch", fetchMock);

    await runChallengeCupDevBatch("team-1", "dev-1", { maxItems: null, retryFailed: true });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1]).toEqual([
      "/api/teams/team-1/workflow-orchestration/challenge-program/dev-controls/batches/dev-1",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ maxItems: null, retryFailed: true }),
      }),
    ]);
    vi.unstubAllGlobals();
  });
});
