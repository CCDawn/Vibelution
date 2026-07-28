import { fetchJson } from "./client";
import type {
  ResearchProjectAgentTaskKind,
  TeamResearchProjectAgentTaskStartPayload,
  TeamResearchProjectAgentTaskStatusPayload,
  TeamResearchProjectListPayload,
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
