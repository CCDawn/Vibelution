/**
 * Deterministic three-stage layout for Challenge Cup workflow.
 * Pure geometry — no React Flow import.
 *
 * Stage regions are real groups; task coordinates are relative to stage parent
 * (relativeX/Y) so React Flow parentId binding is stable and testable.
 */

import type {
  WorkflowLayoutEdge,
  WorkflowLayoutInput,
  WorkflowLayoutNode,
  WorkflowNodeVisualKind,
} from "../../../product/workflow/workflowCanvasTypes";

/** Wider stages so 1440×900 can read titles without zooming. */
const STAGE_WIDTH = 380;
const STAGE_GAP = 36;
const NODE_WIDTH = 248;
const NODE_HEIGHT = 88;
const DECISION_HEIGHT = 112;
const NODE_GAP_Y = 18;
const STAGE_PAD_X = 66;
const STAGE_PAD_TOP = 52;
const STAGE_PAD_BOTTOM = 28;
/** Outer rail for feedback loops (rerun/rollback) — left of stage column. */
const LOOP_RAIL_X = 16;

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
    // Preserve definition order via stage.nodeIds when present.
    const ordered =
      stage.nodeIds.length > 0
        ? stage.nodeIds
            .map((id) => stageNodes.find((n) => n.nodeId === id))
            .filter((n): n is (typeof stageNodes)[number] => Boolean(n))
        : stageNodes;

    let cursorY = STAGE_PAD_TOP;
    const placed: Array<{ node: (typeof ordered)[number]; y: number; h: number }> = [];
    for (const node of ordered) {
      const h = node.visualKind === "decision" ? DECISION_HEIGHT : NODE_HEIGHT;
      placed.push({ node, y: cursorY, h });
      cursorY += h + NODE_GAP_Y;
    }
    const contentHeight = Math.max(cursorY + STAGE_PAD_BOTTOM - NODE_GAP_Y, STAGE_PAD_TOP + NODE_HEIGHT + STAGE_PAD_BOTTOM);
    maxHeight = Math.max(maxHeight, contentHeight);

    const stageId = `stage:${stage.stageId}`;
    nodes.push({
      id: stageId,
      stageId: stage.stageId,
      label: stage.label,
      actorKind: "system",
      visualKind: "stage_region",
      x: stageX,
      y: 0,
      width: STAGE_WIDTH,
      height: contentHeight,
      kind: "stage",
      stageTone: stage.stageTone ?? "idle",
    });

    for (const item of placed) {
      const n = item.node;
      nodes.push({
        id: n.nodeId,
        stageId: n.stageId,
        label: n.label,
        actorKind: n.actorKind,
        visualKind: n.visualKind,
        x: stageX + STAGE_PAD_X,
        y: item.y,
        width: NODE_WIDTH,
        height: item.h,
        kind: "task",
        parentStageId: stageId,
        relativeX: STAGE_PAD_X,
        relativeY: item.y,
        status: n.status,
        attempt: n.attempt,
        primaryAgentId: n.primaryAgentId,
        isRuntimeCurrent: n.isRuntimeCurrent,
        hasPendingHumanTask: n.hasPendingHumanTask,
        blockedReason: n.blockedReason,
        description: n.description,
        primaryRoleKey: n.primaryRoleKey,
        sourceHandleIds:
          n.visualKind === "decision"
            ? ["rerun", "promote", "rollback", "stop"]
            : undefined,
      });
    }
  });

  const edges: WorkflowLayoutEdge[] = input.edges.map((edge) => ({
    id: edge.edgeId,
    source: edge.fromNodeId,
    target: edge.toNodeId,
    label: edge.label,
    semanticKind: edge.semanticKind,
    pathState: edge.pathState,
    labelAlwaysVisible: edge.labelAlwaysVisible,
    sourceHandle: edge.sourceHandle,
    gateKind: edge.gateKind,
    requiresHumanAccept: edge.requiresHumanAccept,
  }));

  // Mark loop edges for outer routing (layout metadata on edge is enough for edge renderer).
  void LOOP_RAIL_X;

  const width =
    input.stages.length * STAGE_WIDTH + Math.max(0, input.stages.length - 1) * STAGE_GAP + 48;
  return { nodes, edges, width, height: Math.max(maxHeight, 420) };
}

/** True when two axis-aligned boxes overlap (for layout tests). */
export function boxesOverlap(
  a: { x: number; y: number; width: number; height: number },
  b: { x: number; y: number; width: number; height: number },
  pad = 2,
): boolean {
  return !(
    a.x + a.width + pad <= b.x
    || b.x + b.width + pad <= a.x
    || a.y + a.height + pad <= b.y
    || b.y + b.height + pad <= a.y
  );
}
