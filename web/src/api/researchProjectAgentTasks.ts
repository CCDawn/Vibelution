import { fetchJson } from "./client";
import type {
  ResearchProjectAgentTaskKind,
  TeamResearchProjectAgentTaskStartPayload,
  TeamResearchProjectAgentTaskStatusPayload,
  TeamResearchProjectListPayload,
  TeamResearchProjectProgressPayload,
  TeamResearchProjectSourceCollectionResetPayload,
} from "./types";

export function listTeamResearchProjects(teamId: string) {
  return fetchJson<TeamResearchProjectListPayload>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/research-projects`,
  );
}

export function getResearchProjectAgentTaskStatus(teamId: string, projectId: string) {
  return fetchJson<TeamResearchProjectAgentTaskStatusPayload>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/research-projects/${encodeURIComponent(projectId)}/agent-tasks/status`,
  );
}

export function getTeamResearchProjectProgress(teamId: string, projectId: string) {
  return fetchJson<TeamResearchProjectProgressPayload>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/research-projects/${encodeURIComponent(projectId)}/progress`,
  );
}

export function resetTeamResearchProjectSourceCollection(teamId: string, projectId: string) {
  return fetchJson<TeamResearchProjectSourceCollectionResetPayload>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/research-projects/${encodeURIComponent(projectId)}/source-collection/reset`,
    { method: "POST" },
  );
}

/** Explicit cascade: clear this project's sources + experiment/iteration plans. */
export function resetTeamResearchProjectProgress(teamId: string, projectId: string) {
  return fetchJson<TeamResearchProjectSourceCollectionResetPayload>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/research-projects/${encodeURIComponent(projectId)}/progress/reset`,
    { method: "POST" },
  );
}

export function startResearchProjectAgentTask(
  teamId: string,
  projectId: string,
  payload: {
    taskKind: ResearchProjectAgentTaskKind;
    targetRef: string;
    idempotencyKey: string;
    formalRetry: boolean;
    retryTaskId: string;
    returnTo: string;
    returnLabel: string;
  },
) {
  return fetchJson<TeamResearchProjectAgentTaskStartPayload>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/research-projects/${encodeURIComponent(projectId)}/agent-tasks/start`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}
