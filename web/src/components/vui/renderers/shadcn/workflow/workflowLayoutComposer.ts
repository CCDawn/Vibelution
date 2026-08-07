/**
 * Final layout composer: combines phase-A internal layouts with the outer ELK
 * result into the public `WorkflowLayoutResult`.
 *
 *  - task absolute = outer stage position + internal local position;
 *  - internal edge sections = local sections offset by the stage position;
 *  - cross-stage edges = outer ELK leg sections (spacer-node routed), label
 *    rect from the spacer position;
 *  - port sides / target handles derived from the port assignments.
 *
 * React Flow consumes ONLY this final projection — no geometry is invented
 * here beyond the offset composition.
 */
import type {
  WorkflowLayoutInput,
  WorkflowLayoutNode,
  WorkflowLayoutPoint,
  WorkflowLayoutResult,
  WorkflowPortSide,
} from "../../../product/workflow/workflowCanvasTypes";
import { DECISION_OUTCOME_IDS } from "./workflowElkPorts";
import type { StageLocalLayout } from "./workflowStageLayout";
import type { OuterLayoutResult } from "./workflowOuterElkLayout";
import type { Rect } from "./workflowLayoutGeometry";

export type ComposerInput = {
  input: WorkflowLayoutInput;
  localLayouts: Map<string, StageLocalLayout>;
  outer: OuterLayoutResult;
  stageBoxes: Map<string, Rect>;
  portSidesByNode: Map<string, WorkflowLayoutNode["portSides"]>;
  targetHandleByEdge: Map<string, string>;
};

export function composeFinalLayout(ctx: ComposerInput): WorkflowLayoutResult {
  const { input, localLayouts, outer, stageBoxes, portSidesByNode, targetHandleByEdge } = ctx;
  const nodes: WorkflowLayoutNode[] = [];
  const stageById = new Map(input.stages.map((s) => [s.stageId, s] as const));
  const nodeById = new Map(input.nodes.map((n) => [n.nodeId, n] as const));

  for (const stage of input.stages) {
    const pos = outer.stagePositions.get(stage.stageId);
    if (!pos) {
      throw new Error(`workflowLayoutComposer: no outer position for stage "${stage.stageId}"`);
    }
    const box = stageBoxes.get(stage.stageId)!;
    const local = localLayouts.get(stage.stageId);
    const meta = stageById.get(stage.stageId);

    nodes.push({
      id: `stage:${stage.stageId}`,
      stageId: stage.stageId,
      label: meta?.label ?? stage.stageId,
      actorKind: "system",
      visualKind: "stage_region",
      kind: "stage",
      x: pos.x,
      y: pos.y,
      width: box.width,
      height: box.height,
      stageTone: meta?.stageTone,
    });

    for (const task of local?.tasks ?? []) {
      const metaNode = nodeById.get(task.id);
      if (!metaNode) continue;
      const uniqueHandles: string[] = [];
      for (const edge of input.edges) {
        if (edge.fromNodeId === task.id && edge.sourceHandle && !uniqueHandles.includes(edge.sourceHandle)) {
          uniqueHandles.push(edge.sourceHandle);
        }
      }
      nodes.push({
        id: task.id,
        stageId: stage.stageId,
        label: metaNode.label,
        actorKind: metaNode.actorKind,
        visualKind: metaNode.visualKind,
        x: pos.x + task.x,
        y: pos.y + task.y,
        width: task.width,
        height: task.height,
        kind: "task",
        parentStageId: `stage:${stage.stageId}`,
        relativeX: task.x,
        relativeY: task.y,
        status: metaNode.status,
        attempt: metaNode.attempt,
        primaryAgentId: metaNode.primaryAgentId,
        isRuntimeCurrent: metaNode.isRuntimeCurrent,
        hasPendingHumanTask: metaNode.hasPendingHumanTask,
        blockedReason: metaNode.blockedReason,
        description: metaNode.description,
        primaryRoleKey: metaNode.primaryRoleKey,
        sourceHandleIds: uniqueHandles.length > 0 ? uniqueHandles : undefined,
        decisionOutcomeIds: metaNode.visualKind === "decision" ? [...DECISION_OUTCOME_IDS] : undefined,
        portSides: portSidesByNode.get(task.id),
      });
    }
  }

  const edges: WorkflowLayoutResult["edges"] = input.edges.map((edge) => {
    const internal = collectInternalSections(input, localLayouts, edge.edgeId, outer);
    const crossSections = internal ?? outer.edgeSections.get(edge.edgeId);
    const labelBounds = internal
      ? internalLabelBounds(localLayouts, input, edge.edgeId, outer)
      : outer.labelPositions.get(edge.edgeId);
    return {
      id: edge.edgeId,
      source: edge.fromNodeId,
      target: edge.toNodeId,
      label: edge.label,
      semanticKind: edge.semanticKind,
      pathState: edge.pathState,
      labelAlwaysVisible: edge.labelAlwaysVisible,
      sourceHandle: edge.sourceHandle,
      targetHandle: targetHandleByEdge.get(edge.edgeId),
      gateKind: edge.gateKind,
      requiresHumanAccept: edge.requiresHumanAccept,
      sections: crossSections ?? [],
      labelBounds,
    };
  });

  return { nodes, edges, width: outer.size.width, height: outer.size.height };
}

/** Internal edge sections: local sections offset by the outer stage position. */
function collectInternalSections(
  input: WorkflowLayoutInput,
  localLayouts: Map<string, StageLocalLayout>,
  edgeId: string,
  outer: OuterLayoutResult,
): WorkflowLayoutResult["edges"][number]["sections"] | undefined {
  const edge = input.edges.find((e) => e.edgeId === edgeId);
  if (!edge) return undefined;
  const stageId = input.nodes.find((n) => n.nodeId === edge.fromNodeId)?.stageId;
  const local = localLayouts.get(stageId ?? "");
  const pos = outer.stagePositions.get(stageId ?? "");
  if (!local || !pos) return undefined;
  const internalEdge = local.internalEdges.find((ie) => ie.id === edgeId);
  if (!internalEdge) return undefined;
  return (internalEdge.sections ?? []).map((s, i) => ({
    id: `${edgeId}_s${i}`,
    start: offset(s.startPoint, pos),
    end: offset(s.endPoint, pos),
    bendPoints: (s.bendPoints ?? []).map((p) => offset(p, pos)),
    incomingSectionIds: s.incomingSections ? [...s.incomingSections] : [],
    outgoingSectionIds: s.outgoingSections ? [...s.outgoingSections] : [],
  }));
}

function internalLabelBounds(
  localLayouts: Map<string, StageLocalLayout>,
  input: WorkflowLayoutInput,
  edgeId: string,
  outer: OuterLayoutResult,
): WorkflowLayoutResult["edges"][number]["labelBounds"] {
  const edge = input.edges.find((e) => e.edgeId === edgeId);
  if (!edge) return undefined;
  const stageId = input.nodes.find((n) => n.nodeId === edge.fromNodeId)?.stageId;
  const local = localLayouts.get(stageId ?? "");
  const pos = outer.stagePositions.get(stageId ?? "");
  if (!local || !pos) return undefined;
  const internalEdge = local.internalEdges.find((ie) => ie.id === edgeId);
  const label = internalEdge?.label;
  if (!label) return undefined;
  return {
    x: label.x + pos.x,
    y: label.y + pos.y,
    width: label.width,
    height: label.height,
  };
}

function offset(p: WorkflowLayoutPoint, by: { x: number; y: number }): WorkflowLayoutPoint {
  return { x: p.x + by.x, y: p.y + by.y };
}
