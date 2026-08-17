import { fetchJson } from "./client";

function writeJson<T>(url: string, method: string, body?: unknown): Promise<T> {
  return fetchJson<T>(url, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export function fetchResearchStageRoundStatus<T>(
  teamId: string,
  options?: { signal?: AbortSignal },
): Promise<T> {
  return fetchJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/stage-rounds/status`,
    { signal: options?.signal },
  );
}

export function startResearchStageRound<T>(
  teamId: string,
  body: unknown,
): Promise<T> {
  return writeJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/stage-rounds/start`,
    "POST",
    body,
  );
}
