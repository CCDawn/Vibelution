/**
 * Project workflow definition / run projection into VWorkflowCanvas graph input.
 * Runtime fields come only from projection.run — never from UI selection.
 */

import type {
  ActorKind,
  NodeRunStatus,
  WorkflowCanvasProjection,
  WorkflowDefinition,
} from "../../../api/types/researchWorkflow";
import type {
  WorkflowCanvasEdgeInput,
  WorkflowCanvasNodeInput,
  WorkflowLayoutInput,
  WorkflowNodeRunStatus,
  WorkflowNodeVisualKind,
} from "../../../components/vui";
import {
  buildEdgePathStates,
  decisionSourceHandle,
  edgeLabelAlwaysVisible,
  resolveEdgeSemanticKind,
  resolveNodeVisualKind,
  stageToneFromNodes,
} from "../../../components/vui/product/workflow/workflowCanvasModel";

function asActorKind(value: string | undefined | null): ActorKind {
  if (value === "human" || value === "system" || value === "agent") return value;
  return "agent";
}

function asStatus(value: string | undefined | null): WorkflowNodeRunStatus {
  const allowed: WorkflowNodeRunStatus[] = [
    "pending",
    "ready",
    "running",
    "waiting_human",
    "succeeded",
    "failed",
    "blocked",
    "skipped",
    "stale",
    "cancelled",
  ];
  if (value && (allowed as string[]).includes(value)) return value as WorkflowNodeRunStatus;
  return "pending";
}

function mapNodes(
  definition: WorkflowDefinition,
  options: {
    nodeRuns?: WorkflowCanvasProjection["run"]["nodeRuns"];
    primaryAgentIdByNode?: ReadonlyMap<string, string>;
    runtimeCurrentNodeIds?: string[];
    pendingHumanNodeIds?: Set<string>;
    blockedReason?: string | null;
  } = {},
): WorkflowCanvasNodeInput[] {
  const current = new Set(options.runtimeCurrentNodeIds ?? []);
  const firstId = definition.nodes[0]?.nodeId;
  const lastId = definition.nodes[definition.nodes.length - 1]?.nodeId;

  return definition.nodes.map((node) => {
    const run = options.nodeRuns?.[node.nodeId];
    const actorKind = asActorKind(run?.actorKind || node.actorKind);
    const visualKind: WorkflowNodeVisualKind = resolveNodeVisualKind({
      nodeId: node.nodeId,
      actorKind,
      isFirstInWorkflow: node.nodeId === firstId,
      isTerminalPackage: node.nodeId === lastId || node.nodeId === "result_package",
    });
    const status = asStatus(run?.status as NodeRunStatus | undefined);
    const isRuntimeCurrent = current.has(node.nodeId);
    const hasPendingHumanTask = options.pendingHumanNodeIds?.has(node.nodeId) ?? false;
    // waiting_human may also come from node run status alone.
    const effectiveStatus: WorkflowNodeRunStatus =
      hasPendingHumanTask && status !== "succeeded" && status !== "failed" && status !== "cancelled"
        ? status === "pending" || status === "ready"
          ? "waiting_human"
          : status
        : status;

    return {
      nodeId: node.nodeId,
      stageId: node.stageId,
      label: node.label,
      actorKind,
      visualKind,
      description: node.description,
      primaryRoleKey: node.primaryRoleKey,
      collaboratorRoleKeys: node.collaboratorRoleKeys,
      producesArtifactKinds: node.producesArtifactKinds,
      acceptsGateKinds: node.acceptsGateKinds,
      status: isRuntimeCurrent && effectiveStatus === "pending" ? "running" : effectiveStatus,
      attempt: run?.attempt,
      primaryAgentId: run?.primaryAgentId || options.primaryAgentIdByNode?.get(node.nodeId),
      isRuntimeCurrent,
      hasPendingHumanTask,
      blockedReason:
        effectiveStatus === "blocked" || effectiveStatus === "failed"
          ? options.blockedReason ?? null
          : null,
    };
  });
}

function mapEdges(
  definition: WorkflowDefinition,
  nodes: WorkflowCanvasNodeInput[],
  runtimeCurrentNodeIds: string[],
): WorkflowCanvasEdgeInput[] {
  const nodeById = new Map(nodes.map((n) => [n.nodeId, n]));
  const current = new Set(runtimeCurrentNodeIds);
  const partial = definition.edges.map((edge) => {
    const semanticKind = resolveEdgeSemanticKind({
      edgeId: edge.edgeId,
      label: edge.label,
      gateKind: edge.gateKind,
      requiresHumanAccept: edge.requiresHumanAccept,
      fromNodeId: edge.fromNodeId,
      toNodeId: edge.toNodeId,
    });
    const sourceHandle =
      edge.fromNodeId === "iteration_decision"
        ? decisionSourceHandle(semanticKind, edge.edgeId)
        : undefined;
    return {
      edgeId: edge.edgeId,
      fromNodeId: edge.fromNodeId,
      toNodeId: edge.toNodeId,
      label: edge.label,
      gateKind: edge.gateKind,
      requiresHumanAccept: edge.requiresHumanAccept,
      requiredArtifactKinds: edge.requiredArtifactKinds,
      semanticKind,
      sourceHandle,
      labelAlwaysVisible: edgeLabelAlwaysVisible(semanticKind, edge.gateKind),
    };
  });
  return buildEdgePathStates(partial, nodeById, current);
}

export type DefinitionCanvasGraphOptions = {
  primaryAgentIdByNode?: ReadonlyMap<string, string>;
};

export function definitionToCanvasGraph(
  definition: WorkflowDefinition,
  options: DefinitionCanvasGraphOptions = {},
): WorkflowLayoutInput {
  const nodes = mapNodes(definition, options);
  const edges = mapEdges(definition, nodes, []);
  const stages = definition.stages.map((stage) => {
    const members = nodes.filter((n) => n.stageId === stage.stageId);
    return {
      stageId: stage.stageId,
      label: stage.label,
      nodeIds: stage.nodeIds,
      index: stage.index,
      stageTone: stageToneFromNodes(members),
    };
  });
  return {
    stages,
    nodes,
    edges,
    run: null,
  };
}

export function projectionToCanvasGraph(projection: WorkflowCanvasProjection): WorkflowLayoutInput {
  const run = projection.run;
  const pendingHumanNodeIds = new Set(
    (run.pendingHumanTasks || []).map((t) => String(t.nodeId)).filter(Boolean),
  );
  const nodes = mapNodes(projection.definition, {
    nodeRuns: run.nodeRuns || {},
    runtimeCurrentNodeIds: run.runtimeCurrentNodeIds || [],
    pendingHumanNodeIds,
    blockedReason: run.blockedReason,
  });
  const edges = mapEdges(projection.definition, nodes, run.runtimeCurrentNodeIds || []);
  const stages = projection.definition.stages.map((stage) => {
    const members = nodes.filter((n) => n.stageId === stage.stageId);
    return {
      stageId: stage.stageId,
      label: stage.label,
      nodeIds: stage.nodeIds,
      index: stage.index,
      stageTone: stageToneFromNodes(members),
    };
  });
  return {
    stages,
    nodes,
    edges,
    run: {
      runId: run.runId,
      status: run.status,
      runtimeCurrentNodeIds: [...(run.runtimeCurrentNodeIds || [])],
      blockedReason: run.blockedReason,
      completionKind: run.completionKind,
      parentRunId: run.parentRunId,
      childRunIds: run.childRunIds ? [...run.childRunIds] : undefined,
      iterationBudgetMax: run.iterationBudgetMax,
    },
  };
}

/** UI selection must never be treated as runtime current. */
export function mergeSelectionAndRuntime(options: {
  selectedNodeId: string | null;
  runtimeCurrentNodeIds: string[];
}): { selectedNodeId: string | null; runtimeCurrentNodeIds: string[] } {
  return {
    selectedNodeId: options.selectedNodeId,
    runtimeCurrentNodeIds: [...options.runtimeCurrentNodeIds],
  };
}
