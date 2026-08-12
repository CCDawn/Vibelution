import type { TeamResearchProjectListPayload } from "../types/teams";
import { CHALLENGE_CUP_WORKFLOW_ID } from "../types/researchWorkflow";
import { fetchJson, JSON_HEADERS, requireTeamId, requireText, teamQuery } from "./client";

export type WorkflowRunRecord = {
  runId: string;
  workflowId: string;
  workflowVersionId: string;
  teamId: string;
  projectId: string;
  questionId: string;
  runVersion: number;
  status: string;
  threadId?: string;
  runtimeCurrentNodeIds?: string[];
  humanTasks?: Array<Record<string, unknown>>;
  handoffs?: Array<Record<string, unknown>>;
  bindingSnapshots?: Array<Record<string, unknown>>;
  events?: Array<Record<string, unknown>>;
  langGraph?: Record<string, unknown>;
  completionKind?: string;
  terminalReason?: string;
  blockedReason?: string;
  officialCandidateRef?: string;
  resultPackage?: Record<string, unknown>;
  createdAt?: string;
  updatedAt?: string;
};

export type ResearchWorkflowSafetyLimits = {
  stageTokens: Record<"knowledge_collection" | "experiment_design" | "execution_iteration", number>;
  toolCalls: number;
  wallClockSeconds: number;
  maxRetries: number;
};

export type CreateResearchWorkflowRunInput = {
  teamId: string;
  questionId: string;
  safetyLimits: ResearchWorkflowSafetyLimits;
  idempotencyKey: string;
};

export type ResearchWorkflowLaunchOption = {
  questionId: string;
  title: string;
  scope: string;
  catalogId: string;
  reviewRunId: string;
  artifactSha256: string;
};

export type ResearchWorkflowLaunchOptionsResponse = {
  workflowId: string;
  teamId: string;
  questions: ResearchWorkflowLaunchOption[];
};

export async function listResearchWorkflowRuns(
  workflowId: string = CHALLENGE_CUP_WORKFLOW_ID,
  options: { teamId: string },
): Promise<{ workflowId: string; runs: WorkflowRunRecord[] }> {
  return fetchJson(
    `/api/research/workflows/${encodeURIComponent(workflowId)}/runs${teamQuery(options.teamId)}`,
  );
}

export async function fetchResearchWorkflowLaunchOptions(
  workflowId: string = CHALLENGE_CUP_WORKFLOW_ID,
  options: { teamId: string },
): Promise<ResearchWorkflowLaunchOptionsResponse> {
  return fetchJson(
    `/api/research/workflows/${encodeURIComponent(workflowId)}/launch-options${teamQuery(options.teamId)}`,
  );
}

export async function createResearchWorkflowRun(
  input: CreateResearchWorkflowRunInput,
  workflowId: string = CHALLENGE_CUP_WORKFLOW_ID,
): Promise<WorkflowRunRecord> {
  return fetchJson(`/api/research/workflows/${encodeURIComponent(workflowId)}/runs`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({
      teamId: requireTeamId(input.teamId),
      questionId: requireText(input.questionId, "questionId"),
      safetyLimits: input.safetyLimits,
      idempotencyKey: requireText(input.idempotencyKey, "idempotencyKey"),
    }),
  });
}

export async function fetchTeamWorkflowResearchProjects(
  teamId: string,
): Promise<TeamResearchProjectListPayload> {
  return fetchJson(
    `/api/teams/${encodeURIComponent(requireTeamId(teamId))}/workflow-orchestration/research-projects`,
  );
}
