/**
 * ELK layout result -> public `WorkflowLayoutResult`.
 *
 * Consumes the ELK graph built by `workflowElkGraphAdapter`, runs the engine,
 * and returns public geometry only (node positions, edge sections, label
 * bounds). No React Flow types here; no ELK types leak into
 * `product/workflow`.
 */
import type { ElkNode } from "elkjs/lib/elk-api";

import type {
  WorkflowLayoutInput,
  WorkflowLayoutNode,
  WorkflowLayoutPoint,
  WorkflowLayoutResult,
  WorkflowEdgeSection,
  WorkflowLabelBounds,
} from "../../../product/workflow/workflowCanvasTypes";
import { DECISION_OUTCOME_IDS } from "./workflowElkPorts";

import type { WorkflowLayoutEngine } from "./workflowElkClient";

export type { WorkflowLayoutEngine } from "./workflowElkClient";

type ElkEdgeLike = NonNullable<ElkNode["edges"]>[number];

function point(x: number, y: number): WorkflowLayoutPoint {
  return { x, y };
}

export function toEdgeSections(
  sections: ElkEdgeLike["sections"],
  offset: WorkflowLayoutPoint = point(0, 0),
): WorkflowEdgeSection[] {
  return (sections ?? []).map((section) => ({
    id: section.id,
    start: point(section.startPoint.x + offset.x, section.startPoint.y + offset.y),
    end: point(section.endPoint.x + offset.x, section.endPoint.y + offset.y),
    bendPoints: (section.bendPoints ?? []).map((p) => point(p.x + offset.x, p.y + offset.y)),
    incomingSectionIds: [...(section.incomingSections ?? [])],
    outgoingSectionIds: [...(section.outgoingSections ?? [])],
  }));
}

function stageElkId(stageId: string): string {
  return `stage:${stageId}`;
}

export function fromElkLayout(layouted: ElkNode, input: WorkflowLayoutInput): WorkflowLayoutResult {
  const nodeById = new Map(input.nodes.map((n) => [n.nodeId, n] as const));
  const stageById = new Map(input.stages.map((s) => [s.stageId, s] as const));
  const stageIdOfElk = new Map(
    input.stages.map((s) => [stageElkId(s.stageId), s.stageId] as const),
  );
  const stageOffsetOfElkId = new Map<string, WorkflowLayoutPoint>();

  const nodes: WorkflowLayoutNode[] = [];
  let maxRight = 0;
  let maxBottom = 0;

  for (const stageNode of layouted.children ?? []) {
    const stageId = stageIdOfElk.get(stageNode.id);
    if (stageId == null) continue;

    const sx = stageNode.x ?? 0;
    const sy = stageNode.y ?? 0;
    stageOffsetOfElkId.set(stageNode.id, point(sx, sy));

    const stageMeta = stageById.get(stageId);
    nodes.push({
      id: stageNode.id,
      stageId,
      label: stageMeta?.label ?? stageNode.id,
      actorKind: "system",
      visualKind: "stage_region",
      kind: "stage",
      x: sx,
      y: sy,
      width: stageNode.width ?? 0,
      height: stageNode.height ?? 0,
      stageTone: stageMeta?.stageTone,
    });
    maxRight = Math.max(maxRight, sx + (stageNode.width ?? 0));
    maxBottom = Math.max(maxBottom, sy + (stageNode.height ?? 0));

    for (const taskNode of stageNode.children ?? []) {
      const metaNode = nodeById.get(taskNode.id);
      if (!metaNode) {
        throw new Error(`fromElkLayout: ELK layout returned unknown node "${taskNode.id}"`);
      }
      const rx = taskNode.x ?? 0;
      const ry = taskNode.y ?? 0;
      const uniqueHandles: string[] = [];
      for (const edge of input.edges) {
        if (edge.fromNodeId === taskNode.id && edge.sourceHandle && !uniqueHandles.includes(edge.sourceHandle)) {
          uniqueHandles.push(edge.sourceHandle);
        }
      }
      nodes.push({
        id: taskNode.id,
        stageId,
        label: taskNode.labels?.[0]?.text ?? metaNode.label,
        actorKind: metaNode.actorKind,
        visualKind: metaNode.visualKind,
        kind: "task",
        x: sx + rx,
        y: sy + ry,
        width: taskNode.width ?? 0,
        height: taskNode.height ?? 0,
        parentStageId: stageNode.id,
        relativeX: rx,
        relativeY: ry,
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
  }

  type EdgeContext = { sections: WorkflowEdgeSection[]; labelBounds?: WorkflowLabelBounds };
  const edgeById = new Map<string, EdgeContext>();

  const collectEdge = (elkEdge: ElkEdgeLike, offset: WorkflowLayoutPoint) => {
    const sections = toEdgeSections(elkEdge.sections, offset);
    const labelElk = elkEdge.labels?.[0];
    const labelBounds: WorkflowLabelBounds | undefined = labelElk
      ? {
          x: (labelElk.x ?? 0) + offset.x,
          y: (labelElk.y ?? 0) + offset.y,
          width: labelElk.width ?? 0,
          height: labelElk.height ?? 0,
        }
      : undefined;
    edgeById.set(elkEdge.id, { sections, labelBounds });
  };

  for (const elkEdge of layouted.edges ?? []) {
    collectEdge(elkEdge, point(0, 0));
  }
  for (const stageNode of layouted.children ?? []) {
    const offset = stageOffsetOfElkId.get(stageNode.id) ?? point(0, 0);
    for (const elkEdge of stageNode.edges ?? []) {
      collectEdge(elkEdge, offset);
    }
  }

  const edges: WorkflowLayoutResult["edges"] = input.edges.map((inputEdge) => {
    const ctx = edgeById.get(inputEdge.edgeId);
    return {
      id: inputEdge.edgeId,
      source: inputEdge.fromNodeId,
      target: inputEdge.toNodeId,
      label: inputEdge.label,
      semanticKind: inputEdge.semanticKind,
      pathState: inputEdge.pathState,
      labelAlwaysVisible: inputEdge.labelAlwaysVisible,
      sourceHandle: inputEdge.sourceHandle,
      gateKind: inputEdge.gateKind,
      requiresHumanAccept: inputEdge.requiresHumanAccept,
      sections: ctx?.sections ?? [],
      labelBounds: ctx?.labelBounds,
    };
  });

  return { nodes, edges, width: maxRight, height: maxBottom };
}

export type { WorkflowLabelBounds };
export type { WorkflowLayoutResult };