/**
 * Maps formal ResearchWorkflowSnapshot into legacy canvas/run shapes consumed by
 * the pre-T8 workspace shell. UI selection never enters snapshot authority.
 */

import type { WorkflowRunRecord } from "../../../api/researchWorkflow";
import type { ResearchWorkflowSnapshot } from "../../../api/types/research-workflow/core";
import type { WorkflowEventEnvelope } from "../../../api/types/research-workflow/events";
import type {
  ActorKind,
  CompletionKind,
  NodeRunStatus,
  WorkflowCanvasProjection,
  WorkflowDefinition,
  WorkflowNodeRunProjection,
  WorkflowRunStatus,
} from "../../../api/types/researchWorkflow";

/** Canvas projection with the formal v2 read-model fields kept intact. */
export type ResearchWorkflowCanvasProjection = WorkflowCanvasProjection & {
  formalSnapshot: ResearchWorkflowSnapshot;
  currentTask: ResearchWorkflowSnapshot["currentTask"];
  progress: ResearchWorkflowSnapshot["progress"];
  retry: ResearchWorkflowSnapshot["retry"];
  recovery: ResearchWorkflowSnapshot["recovery"];
  artifactSummary: ResearchWorkflowSnapshot["artifactSummary"];
  deliveryStatus: ResearchWorkflowSnapshot["deliveryStatus"];
  launchContext: ResearchWorkflowSnapshot["launchContext"];
  stageOne: ResearchWorkflowSnapshot["stageOne"];
};

function asWorkflowDefinition(raw: Record<string, unknown>): WorkflowDefinition {
  return raw as unknown as WorkflowDefinition;
}

function bindingsByNode(snapshot: ResearchWorkflowSnapshot): Map<string, string> {
  const map = new Map<string, string>();
  for (const binding of snapshot.agentBindingSummary?.bindings ?? []) {
    const nodeId = String(binding.nodeId || "").trim();
    const agentId = String(binding.agentId || "").trim();
    if (nodeId && agentId) map.set(nodeId, agentId);
  }
  return map;
}

function nodeRunsFromAttempts(
  snapshot: ResearchWorkflowSnapshot,
): Record<string, WorkflowNodeRunProjection> {
  const bindings = bindingsByNode(snapshot);
  const nodeRuns: Record<string, WorkflowNodeRunProjection> = {};
  for (const [nodeId, attempts] of Object.entries(snapshot.nodeAttempts ?? {})) {
    const latest = attempts[attempts.length - 1];
    if (!latest) continue;
    nodeRuns[nodeId] = {
      nodeId,
      status: latest.status as NodeRunStatus,
      nodeRunId: latest.nodeRunId,
      attempt: latest.attempt,
      actorKind: latest.actorKind as ActorKind,
      primaryAgentId: bindings.get(nodeId),
    };
  }
  for (const [nodeId, agentId] of bindings) {
    if (nodeRuns[nodeId]) continue;
    nodeRuns[nodeId] = {
      nodeId,
      status: "pending",
      attempt: 0,
      primaryAgentId: agentId,
      actorKind: "agent",
    };
  }
  return nodeRuns;
}

export function snapshotToCanvasProjection(
  snapshot: ResearchWorkflowSnapshot,
): ResearchWorkflowCanvasProjection {
  const run = snapshot.run;
  return {
    formalSnapshot: snapshot,
    currentTask: snapshot.currentTask,
    progress: snapshot.progress,
    retry: snapshot.retry,
    recovery: snapshot.recovery,
    artifactSummary: snapshot.artifactSummary,
    deliveryStatus: snapshot.deliveryStatus,
    launchContext: snapshot.launchContext,
    stageOne: snapshot.stageOne,
    definition: asWorkflowDefinition(snapshot.definition),
    run: {
      runId: run.runId,
      teamId: run.teamId,
      runVersion: run.runVersion,
      status: run.status as WorkflowRunStatus,
      runtimeCurrentNodeIds: [...(snapshot.activeNodeIds ?? [])],
      nodeRuns: nodeRunsFromAttempts(snapshot),
      pendingHumanTasks: (snapshot.pendingHumanTasks ?? []).map((task) => ({
        taskId: task.taskId,
        nodeId: String(task.nodeId ?? ""),
        status: task.status,
      })),
      parentRunId: run.parentRunId,
      completionKind: (run.completionKind ?? "") as CompletionKind,
      blockedReason: run.blockedReason ?? run.terminalReason ?? null,
    },
  };
}

export function snapshotToRunRecord(
  snapshot: ResearchWorkflowSnapshot,
  events: WorkflowEventEnvelope[],
): WorkflowRunRecord {
  const run = snapshot.run;
  return {
    runId: run.runId,
    workflowId: run.workflowId,
    workflowVersionId: run.workflowVersionId,
    teamId: run.teamId,
    projectId: run.projectId,
    questionId: run.questionId,
    runVersion: run.runVersion,
    status: run.status,
    threadId: run.threadId,
    runtimeCurrentNodeIds: [...(snapshot.activeNodeIds ?? [])],
    humanTasks: snapshot.pendingHumanTasks as Array<Record<string, unknown>>,
    events: events as Array<Record<string, unknown>>,
    completionKind: run.completionKind ?? undefined,
    terminalReason: run.terminalReason ?? undefined,
    blockedReason: run.blockedReason ?? run.terminalReason ?? undefined,
    bindingSnapshots: (snapshot.agentBindingSummary?.bindings ?? []).map((binding) => ({
      nodeId: binding.nodeId,
      agentId: binding.agentId,
      roleKey: binding.roleKey,
      resolvedFrom: binding.resolvedFrom,
      snapshotId: binding.snapshotId,
    })),
  };
}
