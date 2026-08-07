/**
 * Deterministic fixed layout for Challenge Cup three-stage workflow.
 * Pure geometry — no React Flow import (keeps tests light).
 */

export type WorkflowLayoutNode = {
  id: string;
  stageId: string;
  label: string;
  actorKind: string;
  x: number;
  y: number;
  width: number;
  height: number;
  kind: "stage" | "task";
};

export type WorkflowLayoutEdge = {
  id: string;
  source: string;
  target: string;
  label: string;
};

export type WorkflowLayoutInput = {
  stages: Array<{ stageId: string; label: string; nodeIds: string[] }>;
  nodes: Array<{
    nodeId: string;
    stageId: string;
    label: string;
    actorKind: string;
  }>;
  edges: Array<{
    edgeId: string;
    fromNodeId: string;
    toNodeId: string;
    label: string;
  }>;
};

const STAGE_WIDTH = 320;
const STAGE_GAP = 48;
const NODE_WIDTH = 200;
const NODE_HEIGHT = 72;
const NODE_GAP_Y = 20;
const STAGE_PAD_X = 60;
const STAGE_PAD_TOP = 56;

export function layoutWorkflowCanvas(input: WorkflowLayoutInput): {
  nodes: WorkflowLayoutNode[];
  edges: WorkflowLayoutEdge[];
  width: number;
  height: number;
} {
  const nodes: WorkflowLayoutNode[] = [];
  let maxHeight = 0;

  input.stages.forEach((stage, stageIndex) => {
    const stageX = stageIndex * (STAGE_WIDTH + STAGE_GAP);
    const stageNodes = input.nodes.filter((n) => n.stageId === stage.stageId);
    const contentHeight =
      STAGE_PAD_TOP + stageNodes.length * (NODE_HEIGHT + NODE_GAP_Y) + 24;
    maxHeight = Math.max(maxHeight, contentHeight);

    nodes.push({
      id: `stage:${stage.stageId}`,
      stageId: stage.stageId,
      label: stage.label,
      actorKind: "system",
      x: stageX,
      y: 0,
      width: STAGE_WIDTH,
      height: contentHeight,
      kind: "stage",
    });

    stageNodes.forEach((node, index) => {
      nodes.push({
        id: node.nodeId,
        stageId: node.stageId,
        label: node.label,
        actorKind: node.actorKind,
        x: stageX + STAGE_PAD_X,
        y: STAGE_PAD_TOP + index * (NODE_HEIGHT + NODE_GAP_Y),
        width: NODE_WIDTH,
        height: NODE_HEIGHT,
        kind: "task",
      });
    });
  });

  const edges: WorkflowLayoutEdge[] = input.edges.map((edge) => ({
    id: edge.edgeId,
    source: edge.fromNodeId,
    target: edge.toNodeId,
    label: edge.label,
  }));

  const width =
    input.stages.length * STAGE_WIDTH + Math.max(0, input.stages.length - 1) * STAGE_GAP + 40;
  return { nodes, edges, width, height: Math.max(maxHeight, 360) };
}
