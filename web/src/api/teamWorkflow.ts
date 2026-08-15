import { fetchJson } from "./client";
import type { TeamWorkflowOrchestration } from "./types";

export function fetchTeamWorkflowOrchestration<T = TeamWorkflowOrchestration>(
  teamId: string,
  options?: { signal?: AbortSignal },
): Promise<T> {
  return fetchJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration`,
    { signal: options?.signal },
  );
}

export function ensureTeamWorkflowOrchestration<T = TeamWorkflowOrchestration>(
  teamId: string,
  body: { workflowKind: string; ownerAgentId: string },
): Promise<T> {
  return fetchJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}
