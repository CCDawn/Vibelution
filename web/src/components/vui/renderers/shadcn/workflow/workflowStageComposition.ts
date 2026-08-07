/**
 * Coordinate composition (two-level layout, phase B output).
 *
 * task absolute position = stage meta position + task local position.
 * Stage nodes and their internal edges are emitted here; cross-stage edges
 * are filled by `workflowCrossStageRouter` afterwards.
 */
import type {
  WorkflowLayoutInput,
  WorkflowLayoutNode,
  WorkflowLayoutPoint,
  WorkflowEdgeSection,
} from "../../../product/workflow/workflowCanvasTypes";
import { DECISION_OUTCOME_IDS } from "./workflowElkPorts";
import type { StageLocalLayout } from "./workflowStageLayout";
import type { StageMetaPositions } from "./workflowStageMetaGraphAdapter";
import type { Rect } from "./workflowLayoutGeometry";

export type CompositionInput = {
  input: WorkflowLayoutInput;
  localLayouts: Map<string, StageLocalLayout>;
  meta: StageMetaPositions;
  stageBoxes: Map<string, Rect>;
};

/** Minimal ELK section shape consumed by the composition offset pass. */
type ElkSectionLike = {
  id: string;
  startPoint: WorkflowLayoutPoint;
  endPoint: WorkflowLayoutPoint;
  bendPoints?: WorkflowLayoutPoint[];
  incomingSections?: string[];
  outgoingSections?: string[];
};

export function composeLayout(ctx: CompositionInput): {
  nodes: WorkflowLayoutNode[];
  internalSections: Map<string, WorkflowEdgeSection[]>;
  internalLabels: Map<string, { x: number; y: number; width: number; height: number }>;
  size: { width: number; height: number };
} {
  const { input, localLayouts, meta, stageBoxes } = ctx;
  const nodes: WorkflowLayoutNode[] = [];
  const internalSections = new Map<string, WorkflowEdgeSection[]>();
  const internalLabels = new Map<string, { x: number; y: number; width: number; height: number }>();
  const stageById = new Map(input.stages.map((s) => [s.stageId, s] as const));

  for (const stage of input.stages) {
    const metaPos = meta.positions.get(stage.stageId);
    if (!metaPos) {
      throw new Error(`workflowStageComposition: no meta position for stage "${stage.stageId}"`);
    }
    const box = stageBoxes.get(stage.stageId)!;
    const local = localLayouts.get(stage.stageId);
    const stageMeta = stageById.get(stage.stageId);

    // Stage node (absolute).
    nodes.push({
      id: `stage:${stage.stageId}`,
      stageId: stage.stageId,
      label: stageMeta?.label ?? stage.stageId,
      actorKind: "system",
      visualKind: "stage_region",
      kind: "stage",
      x: metaPos.x,
      y: metaPos.y,
      width: box.width,
      height: box.height,
      stageTone: stageMeta?.stageTone,
    });

    // Task nodes (absolute = meta + local).
    for (const task of local?.tasks ?? []) {
      const metaNode = input.nodes.find((n) => n.nodeId === task.id);
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
        x: metaPos.x + task.x,
        y: metaPos.y + task.y,
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
      });
    }

    // Internal edge sections: local sections offset by the meta position.
    for (const internalEdge of local?.internalEdges ?? []) {
      const sections: WorkflowEdgeSection[] = (internalEdge.sections ?? []).map((section: ElkSectionLike) => ({
        id: section.id,
        start: offset(section.startPoint, metaPos),
        end: offset(section.endPoint, metaPos),
        bendPoints: (section.bendPoints ?? []).map((p: WorkflowLayoutPoint) => offset(p, metaPos)),
        incomingSectionIds: [...(section.incomingSections ?? [])],
        outgoingSectionIds: [...(section.outgoingSections ?? [])],
      }));
      internalSections.set(internalEdge.id, sections);
      if (internalEdge.label) {
        internalLabels.set(internalEdge.id, {
          x: internalEdge.label.x + metaPos.x,
          y: internalEdge.label.y + metaPos.y,
          width: internalEdge.label.width,
          height: internalEdge.label.height,
        });
      }
    }
  }

  return { nodes, internalSections, internalLabels, size: meta.size };
}

function offset(p: WorkflowLayoutPoint, by: { x: number; y: number }): WorkflowLayoutPoint {
  return { x: p.x + by.x, y: p.y + by.y };
}
