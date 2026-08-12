import { CHALLENGE_CUP_WORKFLOW_ID } from "../types/researchWorkflow";
import type { WorkflowDefinition } from "../types/researchWorkflow";
import { fetchJson } from "./client";

export type WorkflowDefinitionResponse = {
  workflowId: string;
  workflowVersionId: string;
  definition: WorkflowDefinition;
};

export async function fetchResearchWorkflowDefinition(
  workflowId: string = CHALLENGE_CUP_WORKFLOW_ID,
): Promise<WorkflowDefinitionResponse> {
  return fetchJson(`/api/research/workflows/${encodeURIComponent(workflowId)}/definition`);
}
