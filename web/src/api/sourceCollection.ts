import { fetchJson } from "./client";
import type {
  TeamWorkflowSourceCollectionAgentSessionContextPayload,
  TeamWorkflowSourceCollectionRunStartPayload,
  TeamWorkflowSourceCollectionStageSessionTaskPayload,
} from "./types";

function writeJson<T>(url: string, method: string, body?: unknown): Promise<T> {
  return fetchJson<T>(url, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export function fetchSourceCollectionSummary<T = Record<string, unknown>>(
  teamId: string,
  options?: { signal?: AbortSignal; runId?: string },
): Promise<T> {
  const search = new URLSearchParams();
  if (options?.runId) {
    search.set("runId", options.runId);
  }
  const suffix = search.toString();
  const path = `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/source-collection/summary`;
  return fetchJson<T>(suffix ? `${path}?${suffix}` : path, {
    signal: options?.signal,
  });
}

export function startSourceCollectionRun(
  teamId: string,
  body: unknown,
): Promise<TeamWorkflowSourceCollectionRunStartPayload> {
  return writeJson<TeamWorkflowSourceCollectionRunStartPayload>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/source-collection-runs`,
    "POST",
    body,
  );
}

export function seedSourceCollectionAgentSessionContext(
  teamId: string,
  runId: string,
  body: {
    stageId: string;
    agentId: string;
    agentRole: string;
  },
): Promise<TeamWorkflowSourceCollectionAgentSessionContextPayload> {
  return writeJson<TeamWorkflowSourceCollectionAgentSessionContextPayload>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/source-collection-runs/${encodeURIComponent(runId)}/agent-session-context`,
    "POST",
    body,
  );
}

export function startSourceCollectionStageSessionTask(
  teamId: string,
  runId: string,
  body: {
    stageId: string;
    agentId: string;
    agentRole: string;
    returnTo: string;
    returnLabel: string;
    requestedByAgent: string;
    idempotencyKey: string;
    formalRetry: boolean;
  },
): Promise<TeamWorkflowSourceCollectionStageSessionTaskPayload> {
  return writeJson<TeamWorkflowSourceCollectionStageSessionTaskPayload>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/source-collection-runs/${encodeURIComponent(runId)}/stage-session-tasks`,
    "POST",
    body,
  );
}
