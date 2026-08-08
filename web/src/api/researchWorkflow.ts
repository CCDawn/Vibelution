/**
 * Research workflow HTTP client (Task 3).
 * Routes stay thin; all fetch goes through shared client helpers.
 */
import { fetchJson } from "./client";
import type {
  AgentBindingConfigPayload,
  EffectiveAgentBindingsResponse,
  NodeAgentSessionBinding,
  ResearchWorkflowNodeDetail,
  WorkflowCanvasProjection,
  WorkflowDefinition,
} from "./types/researchWorkflow";
import { CHALLENGE_CUP_WORKFLOW_ID } from "./types/researchWorkflow";

export type WorkflowDefinitionResponse = {
  workflowId: string;
  workflowVersionId: string;
  definition: WorkflowDefinition;
};

export type WorkflowRunRecord = {
  runId: string;
  workflowId: string;
  workflowVersionId: string;
  status: string;
  threadId?: string;
  runtimeCurrentNodeIds?: string[];
  humanTasks?: Array<Record<string, unknown>>;
  handoffs?: Array<Record<string, unknown>>;
  bindingSnapshots?: Array<Record<string, unknown>>;
  events?: Array<Record<string, unknown>>;
  langGraph?: Record<string, unknown>;
};

export type RequiredTeamScope = {
  teamId: string;
};

function requiredTeamId(teamId: string): string {
  const normalized = teamId.trim();
  if (!normalized) {
    throw new Error("teamId is required for research workflow requests");
  }
  return normalized;
}

export async function fetchResearchWorkflowDefinition(
  workflowId: string = CHALLENGE_CUP_WORKFLOW_ID,
): Promise<WorkflowDefinitionResponse> {
  return fetchJson(`/api/research/workflows/${encodeURIComponent(workflowId)}/definition`);
}

export async function listResearchWorkflowRuns(
  workflowId: string = CHALLENGE_CUP_WORKFLOW_ID,
  options: RequiredTeamScope,
): Promise<{ workflowId: string; runs: WorkflowRunRecord[] }> {
  const qs = `?teamId=${encodeURIComponent(requiredTeamId(options.teamId))}`;
  return fetchJson(`/api/research/workflows/${encodeURIComponent(workflowId)}/runs${qs}`);
}

export async function fetchEffectiveAgentBindings(
  workflowId: string = CHALLENGE_CUP_WORKFLOW_ID,
  options: RequiredTeamScope,
): Promise<EffectiveAgentBindingsResponse> {
  const qs = `?teamId=${encodeURIComponent(requiredTeamId(options.teamId))}`;
  return fetchJson(
    `/api/research/workflows/${encodeURIComponent(workflowId)}/agent-bindings/effective${qs}`,
  );
}

export async function putResearchWorkflowAgentBindings(
  workflowId: string,
  payload: AgentBindingConfigPayload,
): Promise<EffectiveAgentBindingsResponse> {
  const teamId = requiredTeamId(payload.teamId);
  return fetchJson(`/api/research/workflows/${encodeURIComponent(workflowId)}/agent-bindings`, {
    method: "PUT",
    body: JSON.stringify({ ...payload, teamId }),
  });
}

export async function postResearchWorkflowNodeCommand(
  runId: string,
  nodeId: string,
  command: string,
  payload: Record<string, unknown> = {},
): Promise<Record<string, unknown>> {
  return fetchJson(
    `/api/research/workflow-runs/${encodeURIComponent(runId)}/nodes/${encodeURIComponent(nodeId)}/commands`,
    {
      method: "POST",
      body: JSON.stringify({ command, payload }),
    },
  );
}

export async function createResearchWorkflowRun(options: {
  workflowId?: string;
  teamId: string;
  projectId?: string;
  idempotencyKey?: string;
}): Promise<WorkflowRunRecord> {
  const workflowId = options?.workflowId ?? CHALLENGE_CUP_WORKFLOW_ID;
  const teamId = requiredTeamId(options.teamId);
  return fetchJson(`/api/research/workflows/${encodeURIComponent(workflowId)}/runs`, {
    method: "POST",
    body: JSON.stringify({
      teamId,
      projectId: options?.projectId ?? "",
      idempotencyKey: options?.idempotencyKey ?? "",
    }),
  });
}

export async function fetchResearchWorkflowRun(runId: string): Promise<WorkflowRunRecord> {
  return fetchJson(`/api/research/workflow-runs/${encodeURIComponent(runId)}`);
}

export async function fetchResearchWorkflowCanvas(runId: string): Promise<WorkflowCanvasProjection> {
  return fetchJson(`/api/research/workflow-runs/${encodeURIComponent(runId)}/canvas`);
}

export async function fetchResearchWorkflowNodeDetail(
  runId: string,
  nodeId: string,
): Promise<ResearchWorkflowNodeDetail> {
  return fetchJson(
    `/api/research/workflow-runs/${encodeURIComponent(runId)}/nodes/${encodeURIComponent(nodeId)}`,
  );
}

export async function resolveResearchWorkflowHumanTask(
  runId: string,
  taskId: string,
  body: { accept: boolean; resolvedBy?: string },
): Promise<WorkflowRunRecord> {
  return fetchJson(
    `/api/research/workflow-runs/${encodeURIComponent(runId)}/human-tasks/${encodeURIComponent(taskId)}/resolve`,
    {
      method: "POST",
      body: JSON.stringify(body),
    },
  );
}

export async function postResearchWorkflowCommand(
  runId: string,
  body: { command: string; idempotencyKey?: string; payload?: Record<string, unknown> },
): Promise<WorkflowRunRecord> {
  return fetchJson(`/api/research/workflow-runs/${encodeURIComponent(runId)}/commands`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function putResearchWorkflowSessionBinding(
  runId: string,
  nodeId: string,
  binding: Partial<NodeAgentSessionBinding>,
): Promise<NodeAgentSessionBinding> {
  return fetchJson(
    `/api/research/workflow-runs/${encodeURIComponent(runId)}/nodes/${encodeURIComponent(nodeId)}/session-binding`,
    {
      method: "PUT",
      body: JSON.stringify(binding),
    },
  );
}

export async function fetchResearchWorkflowEvents(
  runId: string,
  afterSequence = 0,
): Promise<{ runId: string; events: Array<Record<string, unknown>>; snapshot: Record<string, unknown> }> {
  const qs = afterSequence > 0 ? `?afterSequence=${afterSequence}` : "";
  return fetchJson(`/api/research/workflow-runs/${encodeURIComponent(runId)}/events${qs}`);
}
