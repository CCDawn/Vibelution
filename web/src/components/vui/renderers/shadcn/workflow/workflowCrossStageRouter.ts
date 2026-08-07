/**
 * Cross-stage gateway routing (LEGACY, retired from the production path).
 *
 * Superseded by the outer ELK spacer-node architecture
 * (workflowOuterElkGraphAdapter + workflowOuterElkLayout): cross-stage edges
 * are now real ELK edges through label spacer nodes, and ELK owns the routes.
 *
 * Retained only for reference and tests of the old deterministic router.
 * Deletion condition: all remaining tests migrated to the outer-ELK contracts
 * (workflowOuterElkLayout.test.ts / workflowTwoLevelLayout.test.ts) and no
 * production import remains (workflowTwoLevelLayout no longer imports it).
 *
 * Legacy behavior (kept for the record):
 *   source port (task edge point)
 *     -> horizontal to source stage right boundary
 *     -> horizontal through the gap channel
 *     -> target stage left boundary
 *     -> horizontal to target port (task edge point)
 */
import type {
  WorkflowCanvasEdgeInput,
  WorkflowEdgeSection,
  WorkflowLayoutPoint,
  WorkflowPortSide,
} from "../../../product/workflow/workflowCanvasTypes";
import type { Rect } from "./workflowLayoutGeometry";

export type PortEndpoint = {
  taskId: string;
  portId: string;
  side: WorkflowPortSide;
  /** Exact task-edge coordinate of the port (computed from task box). */
  point: WorkflowLayoutPoint;
};

export type CrossStageEdgeInput = {
  edge: WorkflowCanvasEdgeInput;
  source: PortEndpoint;
  target: PortEndpoint;
  sourceStage: Rect;
  targetStage: Rect;
};

/**
 * Routes one cross-stage edge as an orthogonal chain of sections.
 * Returns an empty array when the route cannot be formed (defensive).
 */
export function routeCrossStageEdge(input: CrossStageEdgeInput): WorkflowEdgeSection[] {
  const { source, target, sourceStage, targetStage } = input;
  const sourceExitX = sourceStage.x + sourceStage.width;
  const targetEntryX = targetStage.x;

  // Channel lane: halfway between the two task centers, clamped into the
  // stage content band (below the title band) on both stages.
  const laneY = (source.point.y + target.point.y) / 2;
  const clamp = (y: number, stage: Rect): number =>
    Math.min(Math.max(y, stage.y + 48), stage.y + stage.height - 8);
  const channelY = (clamp(laneY, sourceStage) + clamp(laneY, targetStage)) / 2;

  // Waypoints: source port -> stage right boundary -> channel -> target stage
  // left boundary -> target port. Degenerate legs are dropped before the
  // chain is emitted, and the section ids re-linked afterwards.
  const waypoints: WorkflowLayoutPoint[] = [
    source.point,
    { x: sourceExitX, y: source.point.y },
    { x: sourceExitX, y: channelY },
    { x: targetEntryX, y: channelY },
    { x: targetEntryX, y: target.point.y },
    target.point,
  ];

  const kept: Array<{ a: WorkflowLayoutPoint; b: WorkflowLayoutPoint }> = [];
  for (let i = 0; i + 1 < waypoints.length; i += 1) {
    const a = waypoints[i]!;
    const b = waypoints[i + 1]!;
    if (Math.abs(a.x - b.x) < 1e-6 && Math.abs(a.y - b.y) < 1e-6) {
      continue;
    }
    kept.push({ a, b });
  }
  if (kept.length === 0) {
    return [];
  }

  const sections: WorkflowEdgeSection[] = [];
  for (let i = 0; i < kept.length; i += 1) {
    const id = `${input.edge.edgeId}_s${i}`;
    sections.push({
      id,
      start: kept[i]!.a,
      end: kept[i]!.b,
      bendPoints: [],
      incomingSectionIds: i > 0 ? [`${input.edge.edgeId}_s${i - 1}`] : [],
      outgoingSectionIds: i + 1 < kept.length ? [`${input.edge.edgeId}_s${i + 1}`] : [],
    });
  }
  return sections;
}

/**
 * Computes the exact task-edge coordinate of a port given its side and the
 * task box.
 */
export function portPoint(task: Rect, side: WorkflowPortSide): WorkflowLayoutPoint {
  switch (side) {
    case "WEST":
      return { x: task.x, y: task.y + task.height / 2 };
    case "EAST":
      return { x: task.x + task.width, y: task.y + task.height / 2 };
    case "NORTH":
      return { x: task.x + task.width / 2, y: task.y };
    case "SOUTH":
      return { x: task.x + task.width / 2, y: task.y + task.height };
  }
}
