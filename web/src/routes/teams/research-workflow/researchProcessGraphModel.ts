/** Project workflow definition DTO into VWorkflowCanvas graph input. */

import type { WorkflowCanvasProjection, WorkflowDefinition } from "../../../api/types/researchWorkflow";
import type { WorkflowLayoutInput } from "../../../components/vui/renderers/shadcn/workflowCanvasLayout";

export function definitionToCanvasGraph(definition: WorkflowDefinition): WorkflowLayoutInput {
  return {
    stages: definition.stages.map((stage) => ({
      stageId: stage.stageId,
      label: stage.label,
      nodeIds: stage.nodeIds,
    })),
    nodes: definition.nodes.map((node) => ({
      nodeId: node.nodeId,
      stageId: node.stageId,
      label: node.label,
      actorKind: node.actorKind,
    })),
    edges: definition.edges.map((edge) => ({
      edgeId: edge.edgeId,
      fromNodeId: edge.fromNodeId,
      toNodeId: edge.toNodeId,
      label: edge.label,
    })),
  };
}

export function projectionToCanvasGraph(projection: WorkflowCanvasProjection): WorkflowLayoutInput {
  return definitionToCanvasGraph(projection.definition);
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
