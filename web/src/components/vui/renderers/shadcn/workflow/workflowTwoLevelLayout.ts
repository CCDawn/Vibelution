/**
 * Two-level layout orchestrator (spacer-node outer ELK architecture).
 *
 *   phase A: stage-internal ELK DOWN layouts (independent per stage)
 *   phase B: OUTER ELK graph — three stage meta nodes + virtual label spacer
 *            nodes; cross-stage edges become two layout legs through the
 *            spacer; ELK owns stage positions, gaps, routes and label space
 *   composition: task absolute = stage meta position + internal local
 *
 * No fixed channel gap, no hand-written cross-stage router, no hand-computed
 * label bounds in the production path — ELK is the single geometry authority.
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
import { buildOuterElkGraph, type OuterEdgeSpec } from "./workflowOuterElkGraphAdapter";
import { layoutOuter } from "./workflowOuterElkLayout";
import { composeFinalLayout } from "./workflowLayoutComposer";
import { resolveEdgeLabelSpec } from "./workflowEdgeLabelGeometry";
import type { WorkflowNodeSize } from "./workflowLayoutHash";
import type { WorkflowCanvasLayoutMode } from "./workflowElkOptions";

export type TwoLevelLayoutEngine = {
  layout: (graph: ElkNode) => Promise<ElkNode>;
};

export async function layoutTwoLevel(
  input: WorkflowLayoutInput,
  engine: TwoLevelLayoutEngine,
  sizes?: ReadonlyMap<string, WorkflowNodeSize>,
  options: { layoutMode?: WorkflowCanvasLayoutMode } = {},
): Promise<WorkflowLayoutResult> {
  const layoutMode = options.layoutMode ?? "stage-columns";
  // Phase A: per-stage subgraphs + DOWN layouts (parallel).
  const bundle = buildStageSubgraphs(input, sizes, layoutMode);
  const stageLayouts = await layoutStages(
    bundle.subgraphs.map((s) => ({ stageId: s.stageId, root: s.root, nodeIds: s.nodeIds })),
    engine,
  );
  const localLayouts = new Map<string, ReturnType<typeof consumeStageLayout>>();
  for (const local of stageLayouts) {
    localLayouts.set(local.stageId, local);
  }
  const stageBoxes = new Map(stageLayouts.map((s) => [s.stageId, s.box] as const));

  // Outer edge specs: cross-stage edges only, with label geometry. Gateway
  // port Y is not controllable (ELK layered ignores fixed port coordinates);
  // the composer bridges from the internal task centers to the engine's
  // channel Y via gateway stubs.
  const stageOf = new Map(input.nodes.map((n) => [n.nodeId, n.stageId] as const));
  const edgeSpecs: OuterEdgeSpec[] = [];
  for (const edge of input.edges) {
    const fromStage = stageOf.get(edge.fromNodeId);
    const toStage = stageOf.get(edge.toNodeId);
    if (!fromStage || !toStage || fromStage === toStage) {
      continue;
    }
    const sourceLocal = localLayouts.get(fromStage);
    const targetLocal = localLayouts.get(toStage);
    if (
      !sourceLocal?.tasks.some((t) => t.id === edge.fromNodeId) ||
      !targetLocal?.tasks.some((t) => t.id === edge.toNodeId)
    ) {
      continue;
    }
    edgeSpecs.push({
      edge,
      labelSpec: resolveEdgeLabelSpec(edge.label),
    });
  }

  // Phase B: real outer ELK layout (spacer-node architecture).
  const outerGraph = buildOuterElkGraph(input, stageBoxes, edgeSpecs, layoutMode);
  const outer = await layoutOuter(outerGraph, engine);

  // Port sides / handles (same semantics as before). Serpentine auto-layout
  // may later rewrite the side of an existing handle to the facing side.
  const portSidesByNode = buildPortSides(input, bundle);
  const sourceHandleByEdge = new Map<string, string>();
  const targetHandleByEdge = new Map<string, string>();
  for (const edge of input.edges) {
    const assignment = bundle.byEdgeId.get(edge.edgeId);
    if (assignment) {
      sourceHandleByEdge.set(edge.edgeId, edge.sourceHandle ?? assignment.sourcePortId);
      targetHandleByEdge.set(edge.edgeId, shortNameOfTargetPort(assignment.targetPortId));
    }
  }

  // Final projection.
  return composeFinalLayout({
    input,
    localLayouts,
    outer,
    stageBoxes,
    portSidesByNode,
    sourceHandleByEdge,
    targetHandleByEdge,
    layoutMode,
  });
}

function buildPortSides(
  input: WorkflowLayoutInput,
  bundle: ReturnType<typeof buildStageSubgraphs>,
): Map<string, WorkflowLayoutNode["portSides"]> {
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
  const map = new Map<string, WorkflowLayoutNode["portSides"]>();
  for (const nodeId of bundle.byNodeId.keys()) {
    const specs = bundle.byNodeId.get(nodeId);
    if (!specs || specs.length === 0) continue;
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
    map.set(nodeId, { source, target });
  }
  return map;
}

function shortNameOfTargetPort(elkPortId: string): string {
  const lastColon = elkPortId.lastIndexOf(":");
  return lastColon > 0 ? elkPortId.slice(0, lastColon) : elkPortId;
}
