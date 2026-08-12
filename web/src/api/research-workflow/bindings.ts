import { CHALLENGE_CUP_WORKFLOW_ID } from "../types/researchWorkflow";
import type { AgentBindingConfigPayload, EffectiveAgentBindingsResponse } from "../types/researchWorkflow";
import { fetchJson, JSON_HEADERS, requireTeamId, teamQuery } from "./client";

export async function fetchEffectiveAgentBindings(
  workflowId: string = CHALLENGE_CUP_WORKFLOW_ID,
  options: { teamId: string },
): Promise<EffectiveAgentBindingsResponse> {
  return fetchJson(
    `/api/research/workflows/${encodeURIComponent(workflowId)}/agent-bindings/effective${teamQuery(options.teamId)}`,
  );
}

export async function putResearchWorkflowAgentBindings(
  workflowId: string,
  payload: AgentBindingConfigPayload,
): Promise<EffectiveAgentBindingsResponse> {
  return fetchJson(`/api/research/workflows/${encodeURIComponent(workflowId)}/agent-bindings`, {
    method: "PUT",
    headers: JSON_HEADERS,
    body: JSON.stringify({ ...payload, teamId: requireTeamId(payload.teamId) }),
  });
}
