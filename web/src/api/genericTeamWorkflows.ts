import { fetchJson } from "./client";
import type {
  TeamFlow,
  TeamFlowArtifact,
  TeamFlowCommand,
  TeamFlowLocalIntegrationRequest,
  TeamFlowRecoveryBindingRequest,
  TeamFlowRecoveryBindingRevokeRequest,
  TeamFlowRecoveryBindingStatus,
  TeamFlowRun,
} from "./types/genericTeamWorkflow";

const JSON_HEADERS = { "Content-Type": "application/json" };

export const teamFlowKeys = {
  flows: (teamId: string) => ["teams", teamId, "user-workflows"] as const,
  runs: (teamId: string) => ["teams", teamId, "user-workflow-runs"] as const,
  artifacts: (teamId: string, runId: string) => ["teams", teamId, "user-workflow-runs", runId, "artifacts"] as const,
};

function teamPath(teamId: string) {
  if (!teamId.trim()) throw new Error("请先选择团队。");
  return `/api/teams/${encodeURIComponent(teamId)}`;
}

export function listTeamFlows(teamId: string, signal?: AbortSignal) {
  return fetchJson<{ schemaVersion: number; teamId: string; flows: TeamFlow[] }>(`${teamPath(teamId)}/workflows`, { signal });
}

export function saveTeamFlow(teamId: string, flow: TeamFlow) {
  return fetchJson<TeamFlow>(`${teamPath(teamId)}/workflows/${encodeURIComponent(flow.id)}`, {
    method: "PUT", headers: JSON_HEADERS, body: JSON.stringify({ flow, expectedRevision: flow.revision }),
  });
}

export function listTeamFlowRuns(teamId: string, signal?: AbortSignal) {
  return fetchJson<{ teamId: string; runs: TeamFlowRun[] }>(`${teamPath(teamId)}/workflow-runs`, { signal });
}

export function startTeamFlowRun(
  teamId: string,
  flow: TeamFlow,
  values: Record<string, string>,
  idempotencyKey: string,
  localIntegration?: TeamFlowLocalIntegrationRequest,
) {
  return fetchJson<TeamFlowRun>(`${teamPath(teamId)}/workflows/${encodeURIComponent(flow.id)}/runs`, {
    method: "POST", headers: JSON_HEADERS,
    body: JSON.stringify({ values, expectedRevision: flow.revision, idempotencyKey, ...(localIntegration === undefined ? {} : { localIntegration }) }),
  });
}

export function commandTeamFlowRun(teamId: string, run: TeamFlowRun, action: TeamFlowCommand, evidenceRef?: string) {
  return fetchJson<TeamFlowRun>(`${teamPath(teamId)}/workflow-runs/${encodeURIComponent(run.id)}/commands`, {
    method: "POST", headers: JSON_HEADERS,
    body: JSON.stringify({ action, expectedRevision: run.revision, ...(evidenceRef === undefined ? {} : { evidenceRef }) }),
  });
}

export function listTeamFlowArtifacts(teamId: string, runId: string, signal?: AbortSignal) {
  return fetchJson<{ artifacts: TeamFlowArtifact[] }>(`${teamPath(teamId)}/workflow-runs/${encodeURIComponent(runId)}/artifacts`, { signal });
}

export function getTeamFlowRecoveryBinding(teamId: string, flowId: string, signal?: AbortSignal) {
  return fetchJson<TeamFlowRecoveryBindingStatus>(
    `${teamPath(teamId)}/workflows/${encodeURIComponent(flowId)}/recovery-binding`,
    { signal },
  );
}

export function saveTeamFlowRecoveryBinding(teamId: string, flowId: string, request: TeamFlowRecoveryBindingRequest) {
  return fetchJson<TeamFlowRecoveryBindingStatus>(
    `${teamPath(teamId)}/workflows/${encodeURIComponent(flowId)}/recovery-binding`,
    { method: "PUT", headers: JSON_HEADERS, body: JSON.stringify(request) },
  );
}

export function revokeTeamFlowRecoveryBinding(teamId: string, flowId: string, request: TeamFlowRecoveryBindingRevokeRequest) {
  return fetchJson<TeamFlowRecoveryBindingStatus>(
    `${teamPath(teamId)}/workflows/${encodeURIComponent(flowId)}/recovery-binding/revoke`,
    { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(request) },
  );
}
