/**
 * Adapter: public `WorkflowLayoutInput` -> ELK compound graph.
 * The only module that knows ELK's input shape; all geometry consumers only
 * see the public types from `product/workflow`.
 *
 * Determinism: stages follow `input.stages` order; nodes follow each stage's
 * `nodeIds`; ports come from `resolveElkPorts` (definition edge order).
 */
import type { ElkNode } from "elkjs/lib/elk-api";

import type { WorkflowLayoutInput } from "../../../product/workflow/workflowCanvasTypes";
import type { WorkflowNodeSize } from "./workflowLayoutHash";
import { resolveElkPorts } from "./workflowElkPorts";
import {
  WORKFLOW_DECISION_DESIGN_HEIGHT,
  WORKFLOW_EDGE_LABEL_HEIGHT,
  WORKFLOW_EDGE_LABEL_WIDTH,
  WORKFLOW_ELK_ROOT_OPTIONS,
  WORKFLOW_ELK_STAGE_OPTIONS,
  WORKFLOW_NODE_DESIGN_HEIGHT,
  WORKFLOW_NODE_DESIGN_WIDTH,
  WORKFLOW_NODE_LABEL_HEIGHT,
  WORKFLOW_NODE_LABEL_WIDTH,
} from "./workflowElkOptions";

export const WORKFLOW_ELK_ROOT_ID = "workflow:root";

const PORT_SIDE_OPTION = "elk.port.side";
const FIXED_ORDER_PORT_OPTION = "org.eclipse.elk.portConstraints";
const FIXED_ORDER_PORTS = { [FIXED_ORDER_PORT_OPTION]: "FIXED_ORDER" } as const;

export type WorkflowElkGraph = {
  root: ElkNode;
  stageElkIds: Map<string, string>;
};

/**
 * Builds the ELK compound graph. `sizes` (measured DOM sizes from the canvas,
 * P1-5) override the design-contract defaults per node so a second layout pass
 * uses real geometry; absent entries keep the design sizes.
 */
export function toElkGraph(
  input: WorkflowLayoutInput,
  sizes?: ReadonlyMap<string, WorkflowNodeSize>,
): WorkflowElkGraph {
  const { byEdgeId, byNodeId } = resolveElkPorts({ nodes: input.nodes, edges: input.edges });

  const nodeById = new Map(input.nodes.map((n) => [n.nodeId, n] as const));
  const stageOf = new Map(input.nodes.map((n) => [n.nodeId, n.stageId] as const));
  const stageEdgesByStage = new Map<string, ElkNode["edges"]>();
  const rootEdges: ElkNode["edges"] = [];
  const stageElkIds = new Map<string, string>();

  const root: ElkNode = {
    id: WORKFLOW_ELK_ROOT_ID,
    layoutOptions: { ...WORKFLOW_ELK_ROOT_OPTIONS },
    children: [],
    edges: [],
  };

  const nodeSizeOf = (nodeId: string): { width: number; height: number } => {
    const measured = sizes?.get(nodeId);
    if (measured && measured.width > 0 && measured.height > 0) {
      return measured;
    }
    const node = nodeById.get(nodeId);
    const height = node?.visualKind === "decision" ? WORKFLOW_DECISION_DESIGN_HEIGHT : WORKFLOW_NODE_DESIGN_HEIGHT;
    return { width: WORKFLOW_NODE_DESIGN_WIDTH, height };
  };

  for (const stage of input.stages) {
    const stageElkId = `stage:${stage.stageId}`;
    stageElkIds.set(stage.stageId, stageElkId);

    const children: ElkNode[] = [];
    for (const nodeId of stage.nodeIds) {
      const node = nodeById.get(nodeId);
      if (!node) {
        throw new Error(`workflowElkGraphAdapter: stage "${stage.stageId}" references unknown node "${nodeId}"`);
      }
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

    root.children!.push({
      id: stageElkId,
      // Note: elk.priority / elk.position / considerModelOrder do NOT order
      // unconnected compound siblings in elkjs 0.12 — probe-verified. Stage
      // ordering along the RIGHT direction is guaranteed by the real
      // cross-stage handoff edges (knowledge -> experiment -> execution).
      // If no cross-stage edge exists, ELK stacks the compounds vertically.
      layoutOptions: { ...WORKFLOW_ELK_STAGE_OPTIONS },
      labels: [{ text: stage.label, width: 220, height: 24 }],
      children,
      edges: [],
    });
    stageEdgesByStage.set(stage.stageId, []);
  }

  for (const edge of input.edges) {
    const ports = byEdgeId.get(edge.edgeId);
    if (!ports) {
      throw new Error(`workflowElkGraphAdapter: no port assignment for edge "${edge.edgeId}"`);
    }
    // The adapter must verify endpoints itself: an unparseable port id must
    // fail fast here (diagnosable) instead of surfacing as a cryptic ELK
    // "unconnected port" error later.
    const sourceNodePorts = byNodeId.get(edge.fromNodeId) ?? [];
    const targetNodePorts = byNodeId.get(edge.toNodeId) ?? [];
    if (!sourceNodePorts.some((p) => p.id === ports.sourcePortId)) {
      throw new Error(
        `workflowElkGraphAdapter: edge "${edge.edgeId}" source port "${ports.sourcePortId}" ` +
          `does not exist on node "${edge.fromNodeId}"`,
      );
    }
    if (!targetNodePorts.some((p) => p.id === ports.targetPortId)) {
      throw new Error(
        `workflowElkGraphAdapter: edge "${edge.edgeId}" target port "${ports.targetPortId}" ` +
          `does not exist on node "${edge.toNodeId}"`,
      );
    }
    const elkEdge: NonNullable<ElkNode["edges"]>[number] = {
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
    };
    const sourceStage = stageOf.get(edge.fromNodeId);
    const targetStage = stageOf.get(edge.toNodeId);
    if (sourceStage !== undefined && sourceStage === targetStage) {
      stageEdgesByStage.get(sourceStage)!.push(elkEdge);
    } else {
      rootEdges.push(elkEdge);
    }
  }

  for (const [stageId, edges] of stageEdgesByStage) {
    const stageNode = root.children!.find((c) => c.id === stageElkIds.get(stageId));
    stageNode!.edges = edges;
  }
  root.edges = rootEdges;

  return { root, stageElkIds };
}