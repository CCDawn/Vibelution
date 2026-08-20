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
import type { HypothesisFirstCanvasRegion } from "./hypothesisFirstCanvasRegion";

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
      // runtimeCurrent is a cursor (where the run will continue), not in-flight work.
      status: effectiveStatus,
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

export function projectionToCanvasGraph(
  projection: WorkflowCanvasProjection,
  options: { primaryAgentIdByNode?: ReadonlyMap<string, string> } = {},
): WorkflowLayoutInput {
  const run = projection.run;
  const pendingHumanNodeIds = new Set(
    (run.pendingHumanTasks || []).map((t) => String(t.nodeId)).filter(Boolean),
  );
  const nodes = mapNodes(projection.definition, {
    nodeRuns: run.nodeRuns || {},
    primaryAgentIdByNode: options.primaryAgentIdByNode,
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

/**
 * Prepends the hypothesis-first region (display layer only) to a base canvas
 * graph: the region stage becomes stages[0] and existing stages shift one
 * position. Region gate edges point at main-graph nodes (`source_finding` /
 * `hypothesis_design`), so their pathState is re-resolved here against the
 * full node set — the region fragment only sees its own cards. A null region
 * returns the base graph untouched (field-for-field identical).
 *
 * Until the first review round closes (or a collection request exists), the
 * downstream 16-node pipeline is omitted so idle knowledge-collection cards
 * do not read as current work.
 */
export function composeHypothesisFirstGraph(
  base: WorkflowLayoutInput,
  region: HypothesisFirstCanvasRegion | null,
  options?: { demotePipelineStages?: boolean },
): WorkflowLayoutInput {
  if (!region) {
    return base;
  }
  const includePipeline = region.showDownstreamPipeline;
  const pipelineNodes = includePipeline ? base.nodes : [];
  const pipelineEdges = includePipeline ? base.edges : [];
  const nodeById = new Map(
    [...pipelineNodes, ...region.nodes].map((node) => [node.nodeId, node] as const),
  );
  const runtimeCurrent = new Set(base.run?.runtimeCurrentNodeIds ?? []);
  const regionEdges = buildEdgePathStates(
    region.edges
      .filter((edge) => nodeById.has(edge.fromNodeId) && nodeById.has(edge.toNodeId))
      .map((edge) => ({ ...edge, pathState: undefined })),
    nodeById,
    runtimeCurrent,
  );
  const demotePipeline = Boolean(options?.demotePipelineStages) && includePipeline;
  // While the hypothesis-first discussion owns the flow, the downstream
  // pipeline renders as an idle preview. Give its not-yet-started nodes an
  // explicit wait reason instead of dead pixels (GitHub Actions shows pending
  // checks as "queued, waiting on …").
  const annotatedPipelineNodes = demotePipeline
    ? pipelineNodes.map((node) =>
        node.status === "pending"
          ? {
              ...node,
              description: node.description?.trim()
                ? `${node.description} · 评审讨论进行中，完成后此步骤自动开启`
                : "评审讨论进行中，完成后此步骤自动开启",
            }
          : node,
      )
    : pipelineNodes;
  return {
    ...base,
    stages: [
      {
        ...region.stage,
        stageTone: region.stage.stageTone,
      },
      ...pipelineNodes.length === 0
        ? []
        : base.stages.map((stage, position) => ({
          ...stage,
          index: position + 1,
          stageTone: demotePipeline ? "idle" as const : stage.stageTone,
        })),
    ],
    nodes: [...region.nodes, ...annotatedPipelineNodes],
    edges: [...regionEdges, ...pipelineEdges],
  };
}
