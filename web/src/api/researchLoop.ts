import { fetchJson } from "./client";

function writeJson<T>(url: string, body?: unknown): Promise<T> {
  return fetchJson<T>(url, {
    method: "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export function fetchResearchLoopTemplates<T>(
  teamId: string,
  options?: { signal?: AbortSignal },
): Promise<T> {
  return fetchJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/research-loop/templates`,
    { signal: options?.signal },
  );
}

export function fetchResearchLoopStatus<T>(
  teamId: string,
  options?: { signal?: AbortSignal },
): Promise<T> {
  return fetchJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/research-loop/status`,
    { signal: options?.signal },
  );
}

export function createResearchLoop<T>(teamId: string, body: unknown): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/research-loop/loops`,
    body,
  );
}

export function recordResearchLoopEvidence<T>(
  teamId: string,
  loopId: string,
  body: unknown,
): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/research-loop/loops/${encodeURIComponent(loopId)}/evidence`,
    body,
  );
}

export function recordResearchLoopDecision<T>(
  teamId: string,
  loopId: string,
  body: unknown,
): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/research-loop/loops/${encodeURIComponent(loopId)}/decision`,
    body,
  );
}

export function materializeResearchLoopIterationDesign<T>(
  teamId: string,
  loopId: string,
  proposalId: string,
  body: unknown,
): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/research-loop/loops/${encodeURIComponent(loopId)}/proposals/${encodeURIComponent(proposalId)}/design-draft`,
    body,
  );
}
