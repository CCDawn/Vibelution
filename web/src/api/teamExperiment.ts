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
