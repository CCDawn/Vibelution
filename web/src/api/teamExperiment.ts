import { fetchJson } from "./client";

export type TeamExperimentSmokeRunRequest = {
  adapter: string;
  seed: number;
  recordedByAgent: string;
};

export type TeamExperimentSmokeRunPayload = {
  schemaVersion: number;
  teamId: string;
  planId: string;
  adapter: string;
  seed: number;
  status: string;
  decisionHint: string;
  runnerResult: Record<string, unknown>;
  smokeRun: Record<string, unknown>;
  experimentStatus: string;
  workflowId: string;
};

export type TeamEngineeringProxyHypothesisRequest = {
  title: string;
  hypothesis: string;
  claimBoundary: string;
  expectedBenefit: string;
  expectedComputeCost: string;
  createdByAgent: string;
  idempotencyKey: string;
};

export type TeamExperimentHypothesisReviewRequest = {
  reviewedByAgent: string;
  decision: "approve";
  comments: string;
  requiredChanges: string[];
};

export type TeamExperimentHypothesisRevisionRequest = {
  createdByAgent: string;
  idempotencyKey: string;
};

export type TeamExperimentMutationPayload = {
  status?: string;
  decision?: string;
  candidate?: Record<string, unknown>;
  hypothesisSummary?: Record<string, unknown>;
  plan?: Record<string, unknown>;
  experimentStatus?: Record<string, unknown>;
  stageRoundStatus?: Record<string, unknown>;
  workflow?: Record<string, unknown>;
};

export function runTeamExperimentSmoke(
  teamId: string,
  planId: string,
  request: TeamExperimentSmokeRunRequest,
) {
  return fetchJson<TeamExperimentSmokeRunPayload>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/experiments/plans/${encodeURIComponent(planId)}/smoke-run`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
}

export function materializeTeamEngineeringProxyHypothesis(
  teamId: string,
  planId: string,
  request: TeamEngineeringProxyHypothesisRequest,
) {
  return fetchJson<TeamExperimentMutationPayload>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/experiments/plans/${encodeURIComponent(planId)}/hypotheses/engineering-proxy`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
}

export function reviewTeamExperimentHypothesis(
  teamId: string,
  candidateId: string,
  request: TeamExperimentHypothesisReviewRequest,
) {
  return fetchJson<TeamExperimentMutationPayload>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/research/review/decide`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        candidateIds: [candidateId],
        ...request,
      }),
    },
  );
}

export function createTeamExperimentHypothesisRevision(
  teamId: string,
  planId: string,
  candidateId: string,
  request: TeamExperimentHypothesisRevisionRequest,
) {
  return fetchJson<TeamExperimentMutationPayload>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/experiments/plans/${encodeURIComponent(planId)}/hypotheses/${encodeURIComponent(candidateId)}/revision`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
}
