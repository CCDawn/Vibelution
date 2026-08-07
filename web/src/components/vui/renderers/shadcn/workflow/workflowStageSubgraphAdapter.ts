/**
 * Stage-internal subgraph construction (phase A of the two-level layout).
 *
 * Groups the public graph by stageId and builds ONE ELK graph per stage that
 * contains ONLY the stage's own nodes and the stage's INTERNAL edges.
 * Cross-stage edges are deliberately excluded: they would pull children into a
 * root-level layering and stretch the stage box (the single-compound failure
 * this architecture replaces).
 */
import type { ElkNode } from "elkjs/lib/elk-api";

import type {
  WorkflowLayoutInput,
  WorkflowCanvasNodeInput,
  WorkflowCanvasEdgeInput,
} from "../../../product/workflow/workflowCanvasTypes";
import { resolveElkPorts } from "./workflowElkPorts";
import {
  WORKFLOW_DECISION_DESIGN_HEIGHT,
  WORKFLOW_EDGE_LABEL_HEIGHT,
  WORKFLOW_EDGE_LABEL_WIDTH,
  WORKFLOW_ELK_STAGE_INTERNAL_OPTIONS,
  WORKFLOW_NODE_DESIGN_HEIGHT,
  WORKFLOW_NODE_DESIGN_WIDTH,
  WORKFLOW_NODE_LABEL_HEIGHT,
  WORKFLOW_NODE_LABEL_WIDTH,
} from "./workflowElkOptions";
import type { WorkflowNodeSize } from "./workflowLayoutHash";

const PORT_SIDE_OPTION = "elk.port.side";
const FIXED_ORDER_PORT_OPTION = "org.eclipse.elk.portConstraints";
const FIXED_ORDER_PORTS = { [FIXED_ORDER_PORT_OPTION]: "FIXED_ORDER" } as const;

export type StageSubgraph = {
  stageId: string;
  /** Stage root node with children + internal edges (no cross-stage edges). */
  root: ElkNode;
  /** Node ids inside this stage, in definition order. */
  nodeIds: string[];
};

export type StageSubgraphBundle = {
  subgraphs: StageSubgraph[];
  /** Per-edge port assignment (source/target) for ALL edges (internal + cross). */
  byEdgeId: ReturnType<typeof resolveElkPorts>["byEdgeId"];
  byNodeId: ReturnType<typeof resolveElkPorts>["byNodeId"];
  nodeById: Map<string, WorkflowCanvasNodeInput>;
  stageOf: Map<string, string>;
};

export function buildStageSubgraphs(
  input: WorkflowLayoutInput,
  sizes?: ReadonlyMap<string, WorkflowNodeSize>,
): StageSubgraphBundle {
  const { byEdgeId, byNodeId } = resolveElkPorts({ nodes: input.nodes, edges: input.edges });
  const nodeById = new Map(input.nodes.map((n) => [n.nodeId, n] as const));
  const stageOf = new Map(input.nodes.map((n) => [n.nodeId, n.stageId] as const));

  const nodeSizeOf = (nodeId: string): { width: number; height: number } => {
    const measured = sizes?.get(nodeId);
    if (measured && measured.width > 0 && measured.height > 0) {
      return measured;
    }
    const node = nodeById.get(nodeId);
    const height = node?.visualKind === "decision" ? WORKFLOW_DECISION_DESIGN_HEIGHT : WORKFLOW_NODE_DESIGN_HEIGHT;
    return { width: WORKFLOW_NODE_DESIGN_WIDTH, height };
  };

  const subgraphs: StageSubgraph[] = [];

  for (const stage of input.stages) {
    const stageNodeIds = stage.nodeIds.filter((id) => nodeById.has(id));
    const children: ElkNode[] = [];
    for (const nodeId of stageNodeIds) {
      const node = nodeById.get(nodeId)!;
      const ports = (byNodeId.get(nodeId) ?? []).map((p) => ({
        id: p.id,
        layoutOptions: { [PORT_SIDE_OPTION]: p.side },
      }));
      const { width, height } = nodeSizeOf(nodeId);
      children.push({
        id: nodeId,
        width,
        height,
        labels: [
          {
            text: node.label,
            width: WORKFLOW_NODE_LABEL_WIDTH,
            height: WORKFLOW_NODE_LABEL_HEIGHT,
          },
        ],
        layoutOptions: ports.length > 0 ? FIXED_ORDER_PORTS : undefined,
        ports,
      });
    }

    // Internal edges only: both endpoints inside this stage.
    const stageEdges: ElkNode["edges"] = [];
    for (const edge of input.edges) {
      const fromStage = stageOf.get(edge.fromNodeId);
      const toStage = stageOf.get(edge.toNodeId);
      if (fromStage !== stage.stageId || toStage !== stage.stageId) {
        continue;
      }
      const ports = byEdgeId.get(edge.edgeId);
      if (!ports) {
        throw new Error(`workflowStageSubgraphAdapter: no port assignment for internal edge "${edge.edgeId}"`);
      }
      stageEdges.push({
        id: edge.edgeId,
        sources: [ports.sourcePortId],
        targets: [ports.targetPortId],
        labels:
          edge.label.length > 0
            ? [
                {
                  text: edge.label,
                  width: WORKFLOW_EDGE_LABEL_WIDTH,
                  height: WORKFLOW_EDGE_LABEL_HEIGHT,
                  layoutOptions: { "elk.edgeLabels.placement": "CENTER" },
                },
              ]
            : [],
      });
    }

    subgraphs.push({
      stageId: stage.stageId,
      root: {
        id: `stage:${stage.stageId}`,
        layoutOptions: { ...WORKFLOW_ELK_STAGE_INTERNAL_OPTIONS },
        children,
        edges: stageEdges,
      },
      nodeIds: stageNodeIds,
    });
  }

  return { subgraphs, byEdgeId, byNodeId, nodeById, stageOf };
}

export type { WorkflowCanvasEdgeInput };
