/** Canonical Challenge Cup workflow HTTP client. */
import { fetchJson } from "./client";
import type {
  AgentBindingConfigPayload,
  EffectiveAgentBindingsResponse,
  NodeAgentSessionBinding,
  ResearchBudgetProjection,
  ResearchEvaluationProjection,
  ResearchExperimentCampaignsProjection,
  ResearchHandoffsProjection,
  ResearchHypothesesProjection,
  ResearchLedgerProjection,
  ResearchWorkflowNodeDetail,
  WorkflowCanvasProjection,
  WorkflowDefinition,
} from "./types/researchWorkflow";
import type { TeamResearchProjectListPayload } from "./types/teams";
import { CHALLENGE_CUP_WORKFLOW_ID } from "./types/researchWorkflow";

const JSON_HEADERS = { "Content-Type": "application/json" } as const;

export type WorkflowDefinitionResponse = {
  workflowId: string;
  workflowVersionId: string;
  definition: WorkflowDefinition;
};

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

export type RequiredTeamScope = {
  teamId: string;
};

export type VersionedWorkflowCommand = RequiredTeamScope & {
  idempotencyKey: string;
  expectedRunVersion: number;
};

export type CreateResearchWorkflowRunInput = RequiredTeamScope & {
  projectId: string;
  questionId: string;
  researchBriefHash: string;
  datasetRefs: string[];
  metricContract: Record<string, unknown>;
  constraintSnapshot: Record<string, unknown>;
  competitionRuleRef: string;
  competitionRuleVersion: string;
  trackAndRubricSnapshot: Record<string, unknown>;
  researchObjectiveContract: Record<string, unknown>;
  sourcePolicy: Record<string, unknown>;
  budgetPolicy: Record<string, unknown>;
  stopPolicy: Record<string, unknown>;
  environmentSnapshotRef: string;
  modelRoutingPolicy: Record<string, unknown>;
  evaluationContract: Record<string, unknown>;
  idempotencyKey: string;
};

export type WorkflowEventsResponse = {
  runId: string;
  teamId: string;
  runVersion: number;
  events: Array<Record<string, unknown>>;
  snapshot: Record<string, unknown>;
};

function requiredText(value: string, field: string): string {
  const normalized = value.trim();
  if (!normalized) throw new Error(`${field} is required for research workflow requests`);
  return normalized;
}

function teamQuery(teamId: string, extra?: URLSearchParams): string {
  const query = new URLSearchParams();
  query.set("teamId", requiredText(teamId, "teamId"));
  extra?.forEach((value, key) => query.append(key, value));
  return `?${query.toString()}`;
}

function versionedCommandBody<T extends Record<string, unknown>>(
  command: VersionedWorkflowCommand,
  payload: T,
): VersionedWorkflowCommand & T {
  if (!Number.isInteger(command.expectedRunVersion) || command.expectedRunVersion < 1) {
    throw new Error("expectedRunVersion must be a positive integer");
  }
  return {
    ...payload,
    teamId: requiredText(command.teamId, "teamId"),
    idempotencyKey: requiredText(command.idempotencyKey, "idempotencyKey"),
    expectedRunVersion: command.expectedRunVersion,
  };
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
  return fetchJson(
    `/api/research/workflows/${encodeURIComponent(workflowId)}/runs${teamQuery(options.teamId)}`,
  );
}

export async function fetchEffectiveAgentBindings(
  workflowId: string = CHALLENGE_CUP_WORKFLOW_ID,
  options: RequiredTeamScope,
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
    body: JSON.stringify({ ...payload, teamId: requiredText(payload.teamId, "teamId") }),
  });
}

export async function createResearchWorkflowRun(
  input: CreateResearchWorkflowRunInput,
  workflowId: string = CHALLENGE_CUP_WORKFLOW_ID,
): Promise<WorkflowRunRecord> {
  return fetchJson(`/api/research/workflows/${encodeURIComponent(workflowId)}/runs`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({
      ...input,
      teamId: requiredText(input.teamId, "teamId"),
      idempotencyKey: requiredText(input.idempotencyKey, "idempotencyKey"),
    }),
  });
}

export async function fetchResearchWorkflowRun(
  runId: string,
  options: RequiredTeamScope,
): Promise<WorkflowRunRecord> {
  return fetchJson(
    `/api/research/workflow-runs/${encodeURIComponent(runId)}${teamQuery(options.teamId)}`,
  );
}

export async function fetchResearchWorkflowCanvas(
  runId: string,
  options: RequiredTeamScope,
): Promise<WorkflowCanvasProjection> {
  return fetchJson(
    `/api/research/workflow-runs/${encodeURIComponent(runId)}/canvas${teamQuery(options.teamId)}`,
  );
}

export async function fetchResearchWorkflowNodeDetail(
  runId: string,
  nodeId: string,
  options: RequiredTeamScope,
): Promise<ResearchWorkflowNodeDetail> {
  return fetchJson(
    `/api/research/workflow-runs/${encodeURIComponent(runId)}/nodes/${encodeURIComponent(nodeId)}${teamQuery(options.teamId)}`,
  );
}

export async function resolveResearchWorkflowHumanTask(
  runId: string,
  taskId: string,
  body: VersionedWorkflowCommand & { decision: "accept" | "reject" | "revise" },
): Promise<WorkflowRunRecord> {
  return fetchJson(
    `/api/research/workflow-runs/${encodeURIComponent(runId)}/human-tasks/${encodeURIComponent(taskId)}/resolve`,
    {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(versionedCommandBody(body, { decision: body.decision })),
    },
  );
}

export async function postResearchWorkflowCommand(
  runId: string,
  body: VersionedWorkflowCommand & {
    command: string;
    payload?: Record<string, unknown>;
  },
): Promise<WorkflowRunRecord> {
  return fetchJson(`/api/research/workflow-runs/${encodeURIComponent(runId)}/commands`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(
      versionedCommandBody(body, { command: body.command, payload: body.payload ?? {} }),
    ),
  });
}

export async function postResearchWorkflowNodeCommand(
  runId: string,
  nodeId: string,
  body: VersionedWorkflowCommand & {
    command: string;
    payload?: Record<string, unknown>;
  },
): Promise<Record<string, unknown>> {
  return fetchJson(
    `/api/research/workflow-runs/${encodeURIComponent(runId)}/nodes/${encodeURIComponent(nodeId)}/commands`,
    {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(
        versionedCommandBody(body, { command: body.command, payload: body.payload ?? {} }),
      ),
    },
  );
}

export async function putResearchWorkflowSessionBinding(
  runId: string,
  nodeId: string,
  body: VersionedWorkflowCommand & Partial<NodeAgentSessionBinding>,
): Promise<NodeAgentSessionBinding> {
  const { teamId, idempotencyKey, expectedRunVersion, ...binding } = body;
  return fetchJson(
    `/api/research/workflow-runs/${encodeURIComponent(runId)}/nodes/${encodeURIComponent(nodeId)}/session-binding`,
    {
      method: "PUT",
      headers: JSON_HEADERS,
      body: JSON.stringify(
        versionedCommandBody(
          { teamId, idempotencyKey, expectedRunVersion },
          binding,
        ),
      ),
    },
  );
}

export async function fetchResearchWorkflowEvents(
  runId: string,
  options: RequiredTeamScope & { afterSequence?: number },
): Promise<WorkflowEventsResponse> {
  const params = new URLSearchParams();
  if ((options.afterSequence ?? 0) > 0) {
    params.set("afterSequence", String(options.afterSequence));
  }
  return fetchJson(
    `/api/research/workflow-runs/${encodeURIComponent(runId)}/events${teamQuery(options.teamId, params)}`,
  );
}

export async function fetchResearchWorkflowHandoffs(
  runId: string,
  options: RequiredTeamScope,
): Promise<ResearchHandoffsProjection> {
  return fetchJson(
    `/api/research/workflow-runs/${encodeURIComponent(runId)}/handoffs${teamQuery(options.teamId)}`,
  );
}

export async function fetchResearchWorkflowResearchLedger(
  runId: string,
  options: RequiredTeamScope,
): Promise<ResearchLedgerProjection> {
  return fetchJson(
    `/api/research/workflow-runs/${encodeURIComponent(runId)}/research-ledger${teamQuery(options.teamId)}`,
  );
}

export async function fetchResearchWorkflowBudget(
  runId: string,
  options: RequiredTeamScope,
): Promise<ResearchBudgetProjection> {
  return fetchJson(
    `/api/research/workflow-runs/${encodeURIComponent(runId)}/budget${teamQuery(options.teamId)}`,
  );
}

export async function fetchResearchWorkflowHypotheses(
  runId: string,
  options: RequiredTeamScope,
): Promise<ResearchHypothesesProjection> {
  return fetchJson(
    `/api/research/workflow-runs/${encodeURIComponent(runId)}/hypotheses${teamQuery(options.teamId)}`,
  );
}

export async function fetchResearchWorkflowExperimentCampaigns(
  runId: string,
  options: RequiredTeamScope,
): Promise<ResearchExperimentCampaignsProjection> {
  return fetchJson(
    `/api/research/workflow-runs/${encodeURIComponent(runId)}/experiment-campaigns${teamQuery(options.teamId)}`,
  );
}

export async function fetchResearchWorkflowEvaluation(
  runId: string,
  options: RequiredTeamScope,
): Promise<ResearchEvaluationProjection> {
  return fetchJson(
    `/api/research/workflow-runs/${encodeURIComponent(runId)}/evaluation${teamQuery(options.teamId)}`,
  );
}

export function researchWorkflowStreamUrl(runId: string, options: RequiredTeamScope): string {
  return `/api/research/workflow-runs/${encodeURIComponent(runId)}/stream${teamQuery(options.teamId)}`;
}

export async function fetchTeamWorkflowResearchProjects(
  teamId: string,
): Promise<TeamResearchProjectListPayload> {
  return fetchJson(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/research-projects`,
  );
}
