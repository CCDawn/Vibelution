/**
 * Outer ELK meta-graph adapter (true outer layout, spacer-node architecture).
 *
 * Builds a REAL ELK graph for the outer layer:
 *  - three stage meta nodes sized by the phase-A boxes;
 *  - one VIRTUAL label spacer node per cross-stage edge, sized by the shared
 *    label geometry contract (workflowEdgeLabelGeometry);
 *  - each cross-stage edge becomes TWO layout edges:
 *        stage A (EAST gateway port) -> spacer (WEST) -> stage B (WEST port)
 *  - spacer nodes are pure layout occupancy: never rendered as workflow nodes,
 *    never user-visible; they force ELK to widen the gap when the label grows.
 *
 * Gateway ports use FIXED_SIDE + explicit anchor Y matching the internal
 * source/target task center, so the routed edge leaves the stage near its real
 * internal origin.
 */
import type { ElkNode } from "elkjs/lib/elk-api";

import type {
  WorkflowLayoutInput,
  WorkflowCanvasEdgeInput,
} from "../../../product/workflow/workflowCanvasTypes";
import type { Rect } from "./workflowLayoutGeometry";
import type { EdgeLabelSpec } from "./workflowEdgeLabelGeometry";

export const OUTER_SPACER_PREFIX = "__label_spacer__";

const PORT_SIDE_OPTION = "elk.port.side";
const PORT_ANCHOR_OPTION = "org.eclipse.elk.port.anchor";
const PORT_CONSTRAINTS_OPTION = "org.eclipse.elk.portConstraints";

export type OuterEdgeSpec = {
  edge: WorkflowCanvasEdgeInput;
  labelSpec: EdgeLabelSpec;
  /** Internal (local) center Y of the source task within its stage. */
  sourceAnchorY: number;
  /** Internal (local) center Y of the target task within its stage. */
  targetAnchorY: number;
};

export type OuterElkGraph = {
  root: ElkNode;
  stageElkIds: Map<string, string>;
  spacerElkIds: Map<string, string>;
  /** edgeId -> { leg1, leg2 } layout edge ids (for section reassembly). */
  legs: Map<string, { leg1: string; leg2: string }>;
  /** edgeId -> spacer node id (label position owner). */
  spacerOfEdge: Map<string, string>;
};

export function buildOuterElkGraph(
  input: WorkflowLayoutInput,
  stageBoxes: Map<string, Rect>,
  edgeSpecs: OuterEdgeSpec[],
): OuterElkGraph {
  const stageElkIds = new Map<string, string>();
  const spacerElkIds = new Map<string, string>();
  const legs = new Map<string, { leg1: string; leg2: string }>();
  const spacerOfEdge = new Map<string, string>();
  const stageOf = new Map(input.nodes.map((n) => [n.nodeId, n.stageId] as const));

  const children: ElkNode[] = [];
  for (const stage of input.stages) {
    const box = stageBoxes.get(stage.stageId);
    if (!box) {
      throw new Error(`workflowOuterElkGraphAdapter: no phase-A box for stage "${stage.stageId}"`);
    }
    const stageElkId = `stage:${stage.stageId}`;
    stageElkIds.set(stage.stageId, stageElkId);
    children.push({
      id: stageElkId,
      width: box.width,
      height: box.height,
      labels: [],
      children: [],
      edges: [],
      ports: [],
    });
  }

  const edges: ElkNode["edges"] = [];
  let spacerIndex = 0;
  for (const spec of edgeSpecs) {
    const fromStage = stageOf.get(spec.edge.fromNodeId);
    const toStage = stageOf.get(spec.edge.toNodeId);
    if (!fromStage || !toStage || fromStage === toStage) {
      continue; // internal edges are phase-A only
    }
    const sourceStageElkId = stageElkIds.get(fromStage)!;
    const targetStageElkId = stageElkIds.get(toStage)!;
    const spacerId = `${OUTER_SPACER_PREFIX}${spec.edge.edgeId}`;
    spacerElkIds.set(spec.edge.edgeId, spacerId);
    spacerOfEdge.set(spec.edge.edgeId, spacerId);

    // Spacer node sized exactly like the rendered label (shared contract).
    // It carries WEST/EAST gateway ports so every leg is port-to-port (mixed
    // node-id/port-id edges confused ELK's routing direction).
    const spacerWest = `${spacerId}:west`;
    const spacerEast = `${spacerId}:east`;
    children.push({
      id: spacerId,
      width: spec.labelSpec.width,
      height: spec.labelSpec.height,
      labels: [],
      children: [],
      edges: [],
      ports: [
        { id: spacerWest, layoutOptions: { [PORT_SIDE_OPTION]: "WEST" } },
        { id: spacerEast, layoutOptions: { [PORT_SIDE_OPTION]: "EAST" } },
      ],
    });

    // Gateway ports on the stage meta nodes: EAST on source (anchor = source
    // task center), WEST on target (anchor = target task center). Anchors are
    // relative Y in px from the stage top; the source stage's port is on its
    // right edge, the target's on its left.
    const sourcePortId = `gate:${spec.edge.edgeId}:src`;
    const targetPortId = `gate:${spec.edge.edgeId}:tgt`;
    ensurePort(children, sourceStageElkId, sourcePortId, "EAST", spec.sourceAnchorY);
    ensurePort(children, targetStageElkId, targetPortId, "WEST", spec.targetAnchorY);

    const leg1 = `__leg1_${spec.edge.edgeId}__`;
    const leg2 = `__leg2_${spec.edge.edgeId}__`;
    edges.push({
      id: leg1,
      sources: [sourcePortId],
      targets: [spacerWest],
      labels: [],
    });
    edges.push({
      id: leg2,
      sources: [spacerEast],
      targets: [targetPortId],
      labels: [],
    });
    legs.set(spec.edge.edgeId, { leg1, leg2 });
    spacerIndex += 1;
  }

  const root: ElkNode = {
    id: "workflow:root:outer",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": "RIGHT",
      "elk.edgeRouting": "ORTHOGONAL",
      "elk.separateConnectedComponents": "false",
      "elk.spacing.nodeNodeBetweenLayers": "32",
      "elk.spacing.edgeNodeBetweenLayers": "24",
      "elk.spacing.edgeEdgeBetweenLayers": "12",
      "elk.layered.spacing.edgeNodeBetweenLayers": "24",
      "elk.portConstraints": "FIXED_SIDE",
    },
    children,
    edges,
  };

  return { root, stageElkIds, spacerElkIds, legs, spacerOfEdge };
}

function ensurePort(
  children: ElkNode[],
  stageElkId: string,
  portId: string,
  side: "EAST" | "WEST",
  anchorY: number,
): void {
  const stage = children.find((c) => c.id === stageElkId);
  if (!stage) return;
  const ports = (stage.ports ?? []).slice();
  if (!ports.some((p) => p.id === portId)) {
    void anchorY;
    ports.push({
      id: portId,
      layoutOptions: {
        [PORT_SIDE_OPTION]: side,
        [PORT_CONSTRAINTS_OPTION]: "FIXED_SIDE",
      },
    });
  }
  stage.ports = ports;
}
