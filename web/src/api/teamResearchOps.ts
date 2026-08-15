import { fetchJson } from "./client";

function writeJson<T>(url: string, method: string, body?: unknown): Promise<T> {
  return fetchJson<T>(url, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export function fetchPaperNoteChunkStatus<T>(
  teamId: string,
  options?: { signal?: AbortSignal },
): Promise<T> {
  return fetchJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/paper-note-chunks/status`,
    { signal: options?.signal },
  );
}

export function fetchSourceQualityStatus<T>(
  teamId: string,
  options?: { signal?: AbortSignal },
): Promise<T> {
  return fetchJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/source-quality/status`,
    { signal: options?.signal },
  );
}

export function fetchOfficialModelEvidenceStatus<T>(
  teamId: string,
  options?: { signal?: AbortSignal },
): Promise<T> {
  return fetchJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/official-model-evidence/status`,
    { signal: options?.signal },
  );
}

export function assessCandidateSourceQuality<T>(
  teamId: string,
  candidateId: string,
  body: unknown,
): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/candidates/${encodeURIComponent(candidateId)}/source-quality/assess`,
    "POST",
    body,
  );
}

export function assessSourceQualityBatch<T>(teamId: string, body: unknown): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/source-quality/assess-batch`,
    "POST",
    body,
  );
}

export function planPaperNoteChunks<T>(
  teamId: string,
  candidateId: string,
  body: unknown,
): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/candidates/${encodeURIComponent(candidateId)}/paper-note-chunks/plan`,
    "POST",
    body,
  );
}

export function extractResearchMechanisms<T>(teamId: string, body: unknown): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/research/mechanisms/extract`,
    "POST",
    body,
  );
}

export function mapResearchMechanisms<T>(teamId: string, body: unknown): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/research/mechanisms/map`,
    "POST",
    body,
  );
}

export function generateResearchHypotheses<T>(teamId: string, body: unknown): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/research/hypotheses/generate`,
    "POST",
    body,
  );
}

export function proposeResearchIteration<T>(teamId: string, body: unknown): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/iterations/propose`,
    "POST",
    body,
  );
}

export function exportResearchDeliverables<T>(teamId: string, body: unknown): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/deliverables/export`,
    "POST",
    body,
  );
}

export function validateResearchPrd<T>(teamId: string, body: unknown): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/prd/validate`,
    "POST",
    body,
  );
}

export function syncOfficialKnowledgeGraph<T>(teamId: string, body: unknown): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/knowledge-graph/sync`,
    "POST",
    body,
  );
}

export function rollbackOfficialKnowledgeGraph<T>(
  teamId: string,
  syncId: string,
  body: unknown,
): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/knowledge-graph/${encodeURIComponent(syncId)}/rollback`,
    "POST",
    body,
  );
}

export function submitStewardPackKnowledgeIngestion<T>(
  teamId: string,
  candidateId: string,
  body: unknown,
): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/steward-packs/${encodeURIComponent(candidateId)}/knowledge-ingestion`,
    "POST",
    body,
  );
}

export function reviewStewardPackKnowledgeIngestion<T>(
  teamId: string,
  candidateId: string,
  body: unknown,
): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/steward-packs/${encodeURIComponent(candidateId)}/knowledge-ingestion/review`,
    "POST",
    body,
  );
}

export function createWorkflowTransfer<T>(teamId: string, body: unknown): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/transfers`,
    "POST",
    body,
  );
}

export function decideWorkflowTransfer<T>(
  teamId: string,
  transferId: string,
  body: unknown,
): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/transfers/${encodeURIComponent(transferId)}/decide`,
    "POST",
    body,
  );
}

export function createLocalResearchModelTask<T>(teamId: string, body: unknown): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/local-research-model/tasks`,
    "POST",
    body,
  );
}

export function recordLocalResearchModelOutput<T>(teamId: string, body: unknown): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/local-research-model/outputs`,
    "POST",
    body,
  );
}

export function invokeLocalResearchModel<T>(teamId: string, body: unknown): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/local-research-model/invoke`,
    "POST",
    body,
  );
}

export function registerOfficialModelEvidence<T>(teamId: string, body: unknown): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/official-model-evidence`,
    "POST",
    body,
  );
}
