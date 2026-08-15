import { fetchJson } from "./client";
import type {
  TeamWorkflowCandidateGraphBuildPayload,
  TeamWorkflowCoordinationStatus,
  TeamWorkflowKnowledgeCollectionIngestionPayload,
  TeamWorkflowKnowledgeIngestionStatus,
  TeamWorkflowSourceCollectionExtractionPayload,
} from "./types";

function writeJson<T>(url: string, method: string, body?: unknown): Promise<T> {
  return fetchJson<T>(url, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export function fetchKnowledgeIngestionStatus<T = TeamWorkflowKnowledgeIngestionStatus>(
  teamId: string,
  options?: { signal?: AbortSignal },
): Promise<T> {
  return fetchJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/knowledge-ingestion/status`,
    { signal: options?.signal },
  );
}

export function fetchTeamWorkflowCoordinationStatus<T = TeamWorkflowCoordinationStatus>(
  teamId: string,
  options?: { signal?: AbortSignal },
): Promise<T> {
  return fetchJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/coordination/status`,
    { signal: options?.signal },
  );
}

export function runKnowledgeIngestionPrecheck<T>(
  teamId: string,
  body: unknown,
): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/knowledge-ingestion/precheck`,
    "POST",
    body,
  );
}

export function extractSourceCollectionCandidates(
  teamId: string,
  body: unknown,
): Promise<TeamWorkflowSourceCollectionExtractionPayload> {
  return writeJson<TeamWorkflowSourceCollectionExtractionPayload>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/knowledge-collection/extract`,
    "POST",
    body,
  );
}

export function ingestKnowledgeCollection<T = TeamWorkflowKnowledgeCollectionIngestionPayload>(
  teamId: string,
  body: unknown,
): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/knowledge-collection/ingest`,
    "POST",
    body,
  );
}

export function completeKnowledgeCollection<T = TeamWorkflowKnowledgeCollectionIngestionPayload>(
  teamId: string,
  body: unknown,
): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/knowledge-collection/complete`,
    "POST",
    body,
  );
}

export function buildCandidateGraph(
  teamId: string,
  body: unknown,
): Promise<TeamWorkflowCandidateGraphBuildPayload> {
  return writeJson<TeamWorkflowCandidateGraphBuildPayload>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/candidate-graph`,
    "POST",
    body,
  );
}

export function extractCandidateSourcePages<T = Record<string, unknown>>(
  teamId: string,
  candidateId: string,
  body: unknown,
): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/candidates/${encodeURIComponent(candidateId)}/source-extraction`,
    "POST",
    body,
  );
}

export function draftPaperNoteFromSourceCandidate<T = Record<string, unknown>>(
  teamId: string,
  candidateId: string,
  body: unknown,
): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/candidates/${encodeURIComponent(candidateId)}/paper-note-draft`,
    "POST",
    body,
  );
}
