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

export type TeamScientificHypothesisCompletionRequest = Record<string, unknown> & {
  createdByAgent: string;
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

export function completeTeamScientificHypothesisFromDesign(
  teamId: string,
  planId: string,
  candidateId: string,
  request: TeamScientificHypothesisCompletionRequest,
) {
  return fetchJson<TeamExperimentMutationPayload>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/experiments/plans/${encodeURIComponent(planId)}/hypotheses/${encodeURIComponent(candidateId)}/complete-design`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
}

function writeJson<T>(url: string, method: string, body?: unknown): Promise<T> {
  return fetchJson<T>(url, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export function fetchExperimentPlanningStatus<T>(
  teamId: string,
  options?: { signal?: AbortSignal },
): Promise<T> {
  return fetchJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/experiments/status`,
    { signal: options?.signal },
  );
}

export function fetchExperimentMethodCatalog<T>(
  teamId: string,
  options?: { signal?: AbortSignal },
): Promise<T> {
  return fetchJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/experiments/methods`,
    { signal: options?.signal },
  );
}

export function fetchTeamWorkflowCandidates<T>(
  teamId: string,
  options?: {
    limit?: number;
    candidateType?: string;
    includeValidation?: boolean;
    includeStore?: boolean;
    signal?: AbortSignal;
  },
): Promise<T> {
  const search = new URLSearchParams();
  if (options?.limit != null) {
    search.set("limit", String(options.limit));
  }
  if (options?.candidateType) {
    search.set("candidateType", options.candidateType);
  }
  if (options?.includeValidation != null) {
    search.set("includeValidation", String(options.includeValidation));
  }
  if (options?.includeStore != null) {
    search.set("includeStore", String(options.includeStore));
  }
  const suffix = search.toString();
  const path = `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/candidates`;
  return fetchJson<T>(suffix ? `${path}?${suffix}` : path, { signal: options?.signal });
}

export function createTeamExperimentPlan<T>(teamId: string, body: unknown): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/experiments/plan`,
    "POST",
    body,
  );
}

export function freezeTeamExperimentDesign<T>(teamId: string, planId: string, body: unknown): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/experiments/plans/${encodeURIComponent(planId)}/freeze`,
    "POST",
    body,
  );
}

export function registerTeamExperimentBaselineArtifact<T>(teamId: string, planId: string, body: unknown): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/experiments/plans/${encodeURIComponent(planId)}/baseline-artifact`,
    "POST",
    body,
  );
}

export function registerTeamExperimentSmokeResult<T>(teamId: string, planId: string, body: unknown): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/experiments/plans/${encodeURIComponent(planId)}/smoke-result`,
    "POST",
    body,
  );
}

export function registerTeamExperimentFullRunResult<T>(teamId: string, planId: string, body: unknown): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/experiments/plans/${encodeURIComponent(planId)}/full-run-result`,
    "POST",
    body,
  );
}

export function requestTeamExperimentKnowledgeIngestion<T>(teamId: string, planId: string, body: unknown): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/experiments/plans/${encodeURIComponent(planId)}/knowledge-ingestion-request`,
    "POST",
    body,
  );
}

export function fetchChallengeQuestionRunStatus<T>(
  teamId: string,
  options?: { signal?: AbortSignal },
): Promise<T> {
  return fetchJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/challenge-program/question-runs/status`,
    { signal: options?.signal },
  );
}

export function registerChallengeQuestionRun<T>(teamId: string, body: unknown): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/challenge-program/question-runs`,
    "POST",
    body,
  );
}

export function publishChallengeQuestionRun<T>(teamId: string, body: unknown): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/challenge-program/question-runs/publish`,
    "POST",
    body,
  );
}

export function reviewChallengeQuestionRun<T>(
  teamId: string,
  questionId: string,
  runId: string,
  body: unknown,
): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/challenge-program/questions/${encodeURIComponent(questionId)}/runs/${encodeURIComponent(runId)}/review`,
    "POST",
    body,
  );
}

export function prepareTeamExperimentFullRun<T>(teamId: string, planId: string, body: unknown): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/experiments/plans/${encodeURIComponent(planId)}/full-run/prepare`,
    "POST",
    body,
  );
}

export function executeTeamExperimentFullRun<T>(teamId: string, planId: string, body: unknown): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/experiments/plans/${encodeURIComponent(planId)}/full-run/execute`,
    "POST",
    body,
  );
}

export function retryStageRoundCoordination<T>(teamId: string, stageRoundId: string): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/stage-rounds/${encodeURIComponent(stageRoundId)}/coordination/retry`,
    "POST",
  );
}

export function retryStageRoundMemoryRecord<T>(teamId: string, stageRoundId: string): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/stage-rounds/${encodeURIComponent(stageRoundId)}/memory-record/retry`,
    "POST",
  );
}

export function fetchTeamWorkflowCandidateValidation<T>(
  teamId: string,
  options?: { signal?: AbortSignal },
): Promise<T> {
  return fetchJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/candidates/validation`,
    { signal: options?.signal },
  );
}
