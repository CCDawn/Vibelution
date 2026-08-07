/**
 * Two-level layout orchestrator.
 *
 *   phase A: stage-internal ELK DOWN layouts (independent per stage)
 *   phase B: stage meta-graph ELK RIGHT layout (three meta nodes)
 *   composition: task absolute = meta + local; internal edge sections offset
 *   cross-stage router: gateway orthogonal channels for inter-stage edges
 *
 * Produces the same public `WorkflowLayoutResult` shape as the previous
 * single-compound pipeline so the canvas/edge consumers stay unchanged.
 */
import type { ElkNode } from "elkjs/lib/elk-api";

import type {
  WorkflowLayoutInput,
  WorkflowLayoutNode,
  WorkflowLayoutResult,
  WorkflowPortSide,
} from "../../../product/workflow/workflowCanvasTypes";
import { resolveElkPorts } from "./workflowElkPorts";
import { buildStageSubgraphs } from "./workflowStageSubgraphAdapter";
import { consumeStageLayout, layoutStages } from "./workflowStageLayout";
import { buildStageMetaGraph } from "./workflowStageMetaGraphAdapter";
import { composeLayout } from "./workflowStageComposition";
import { portPoint, routeCrossStageEdge } from "./workflowCrossStageRouter";
import { rectOf } from "./workflowLayoutGeometry";
import type { WorkflowNodeSize } from "./workflowLayoutHash";

export type TwoLevelLayoutEngine = {
  layout: (graph: ElkNode) => Promise<ElkNode>;
};

export async function layoutTwoLevel(
  input: WorkflowLayoutInput,
  engine: TwoLevelLayoutEngine,
  sizes?: ReadonlyMap<string, WorkflowNodeSize>,
): Promise<WorkflowLayoutResult> {
  // Phase A: per-stage subgraphs + DOWN layouts.
  const bundle = buildStageSubgraphs(input, sizes);
  const stageLayouts = await layoutStages(
    bundle.subgraphs.map((s) => ({ stageId: s.stageId, root: s.root, nodeIds: s.nodeIds })),
    engine,
  );
  const localLayouts = new Map<string, ReturnType<typeof consumeStageLayout>>();
  for (const local of stageLayouts) {
    localLayouts.set(local.stageId, local);
  }

  // Phase B: deterministic stage meta row (RIGHT, definition order, channel
  // gap). ELK cannot order unconnected compounds, so the meta placement is a
  // pure function of the phase-A boxes — no engine call needed.
  const stageBoxes = new Map(stageLayouts.map((s) => [s.stageId, s.box] as const));
  const meta = buildStageMetaGraph(input, stageBoxes).positions;

  // Composition: absolute node positions + internal edge sections/labels.
  const composed = composeLayout({ input, localLayouts, meta, stageBoxes });
  const nodes: WorkflowLayoutNode[] = composed.nodes.map((node) =>
    node.kind === "task" ? { ...node, portSides: portSidesOf(node.id, input, bundle) } : node,
  );

  // Edges.
  const nodeById = new Map(nodes.map((n) => [n.id, n] as const));
  const stageById = new Map(
    nodes.filter((n) => n.kind === "stage").map((n) => [n.stageId, n] as const),
  );
  const stageOf = new Map(input.nodes.map((n) => [n.nodeId, n.stageId] as const));

  const edges: WorkflowLayoutResult["edges"] = input.edges.map((edge) => {
    const internalSections = composed.internalSections.get(edge.edgeId);
    const assignment = bundle.byEdgeId.get(edge.edgeId);
    const sourceStageId = stageOf.get(edge.fromNodeId);
    const targetStageId = stageOf.get(edge.toNodeId);
    const targetHandle = assignment
      ? shortNameOfTargetPort(assignment.targetPortId)
      : undefined;

    if (internalSections) {
      return {
        id: edge.edgeId,
        source: edge.fromNodeId,
        target: edge.toNodeId,
        label: edge.label,
        semanticKind: edge.semanticKind,
        pathState: edge.pathState,
        labelAlwaysVisible: edge.labelAlwaysVisible,
        sourceHandle: edge.sourceHandle,
        targetHandle,
        gateKind: edge.gateKind,
        requiresHumanAccept: edge.requiresHumanAccept,
        sections: internalSections,
        labelBounds: composed.internalLabels.get(edge.edgeId),
      };
    }

    // Cross-stage edge: gateway channel route.
    const sourceNode = nodeById.get(edge.fromNodeId);
    const targetNode = nodeById.get(edge.toNodeId);
    const sourceStage = stageById.get(sourceStageId ?? "");
    const targetStage = stageById.get(targetStageId ?? "");
    if (!assignment || !sourceNode || !targetNode || !sourceStage || !targetStage) {
      return {
        id: edge.edgeId,
        source: edge.fromNodeId,
        target: edge.toNodeId,
        label: edge.label,
        semanticKind: edge.semanticKind,
        pathState: edge.pathState,
        labelAlwaysVisible: edge.labelAlwaysVisible,
        sourceHandle: edge.sourceHandle,
        targetHandle,
        gateKind: edge.gateKind,
        requiresHumanAccept: edge.requiresHumanAccept,
        sections: [],
        labelBounds: undefined,
      };
    }
    const sourceSpec = bundle.byNodeId.get(edge.fromNodeId)?.find((p) => p.id === assignment.sourcePortId);
    const targetSpec = bundle.byNodeId.get(edge.toNodeId)?.find((p) => p.id === assignment.targetPortId);
    const sourceSide = sourceSpec?.side ?? "EAST";
    const targetSide = targetSpec?.side ?? "WEST";
    const sections = routeCrossStageEdge({
      edge,
      source: {
        taskId: edge.fromNodeId,
        portId: assignment.sourcePortId,
        side: sourceSide,
        point: portPoint(rectOf(sourceNode), sourceSide),
      },
      target: {
        taskId: edge.toNodeId,
        portId: assignment.targetPortId,
        side: targetSide,
        point: portPoint(rectOf(targetNode), targetSide),
      },
      sourceStage: rectOf(sourceStage),
      targetStage: rectOf(targetStage),
    });
    return {
      id: edge.edgeId,
      source: edge.fromNodeId,
      target: edge.toNodeId,
      label: edge.label,
      semanticKind: edge.semanticKind,
      pathState: edge.pathState,
      labelAlwaysVisible: edge.labelAlwaysVisible,
      sourceHandle: edge.sourceHandle,
      targetHandle,
      gateKind: edge.gateKind,
      requiresHumanAccept: edge.requiresHumanAccept,
      sections,
      labelBounds: crossStageLabelBounds(
        sections,
        edge.edgeId,
        (targetStage.x - (sourceStage.x + sourceStage.width)),
        sourceStage.x + sourceStage.width,
        targetStage.x,
      ),
    };
  });

  return { nodes, edges, width: composed.size.width, height: composed.size.height };
}

function portSidesOf(
  nodeId: string,
  input: WorkflowLayoutInput,
  bundle: ReturnType<typeof buildStageSubgraphs>,
): WorkflowLayoutNode["portSides"] {
  const specs = bundle.byNodeId.get(nodeId);
  if (!specs || specs.length === 0) {
    return undefined;
  }
  const roleOfPort = new Map<string, "source" | "target">();
  for (const assignment of bundle.byEdgeId.values()) {
    roleOfPort.set(assignment.sourcePortId, "source");
    roleOfPort.set(assignment.targetPortId, "target");
  }
  const handleIdOfSourcePort = new Map<string, string>();
  for (const edge of input.edges) {
    const assignment = bundle.byEdgeId.get(edge.edgeId);
    if (assignment && edge.sourceHandle) {
      handleIdOfSourcePort.set(assignment.sourcePortId, edge.sourceHandle);
    }
  }
  const source: Record<string, WorkflowPortSide> = {};
  const target: Record<string, WorkflowPortSide> = {};
  for (const spec of specs) {
    const role = roleOfPort.get(spec.id) ?? "source";
    if (role === "source") {
      source[handleIdOfSourcePort.get(spec.id) ?? spec.id] = spec.side;
    } else {
      target[shortNameOfTargetPort(spec.id)] = spec.side;
    }
  }
  return { source, target };
}

function shortNameOfTargetPort(elkPortId: string): string {
  const lastColon = elkPortId.lastIndexOf(":");
  return lastColon > 0 ? elkPortId.slice(0, lastColon) : elkPortId;
}

/** Cross-stage label anchor: centered in the gap on the horizontal channel
 * leg that actually spans the gap, sized to fit it so the label never
 * overlaps a stage body. */
function crossStageLabelBounds(
  sections: WorkflowLayoutResult["edges"][number]["sections"],
  edgeId: string,
  channelGap: number,
  gapLeft: number,
  gapRight: number,
): WorkflowLayoutResult["edges"][number]["labelBounds"] {
  void edgeId;
  const channel = sections.find(
    (s) =>
      Math.abs(s.start.y - s.end.y) < 1e-6 &&
      s.start.x >= gapLeft - 1e-3 &&
      s.end.x <= gapRight + 1e-3 &&
      s.end.x - s.start.x >= 32,
  );
  if (!channel) {
    return undefined;
  }
  const cx = (channel.start.x + channel.end.x) / 2;
  const cy = channel.start.y;
  const width = Math.max(80, Math.min(152, channelGap - 12));
  return { x: cx - width / 2, y: cy - 13, width, height: 26 };
}

export type { WorkflowLayoutResult };
