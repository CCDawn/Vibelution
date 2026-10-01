import { applyNodeChanges, type Node, type NodeChange } from "@xyflow/react";

export type WorkflowMeasuredSize = {
  width: number;
  height: number;
};

export type WorkflowNodeChangeOutcome = {
  measured: Record<string, WorkflowMeasuredSize>;
  /** Present only when this batch includes a select change. `null` clears. */
  selectedId?: string | null;
  /** Resting task-card positions. Empty during an in-progress drag. */
  positions: Record<string, { x: number; y: number }>;
  dragging: boolean;
};

/**
 * Observation canvas contract: React Flow may report dimensions, selection,
 * and position while manual layout is unlocked. Add, remove, and replace
 * never become topology edits. Dimension changes update `measured` only;
 * ELK still owns width and height.
 */
export function resolveWorkflowNodeChangeOutcome(
  changes: readonly NodeChange[],
  nodes: readonly Node[],
  positionAllowed: boolean,
): WorkflowNodeChangeOutcome | null {
  const accepted: NodeChange[] = [];
  for (const change of changes) {
    if (change.type === "dimensions") {
      accepted.push({ ...change, setAttributes: false });
    } else if (change.type === "select") {
      accepted.push(change);
    } else if (change.type === "position" && positionAllowed && change.position) {
      accepted.push(change);
    }
  }
  if (accepted.length === 0) return null;

  const next = applyNodeChanges(accepted, [...nodes]);
  const measured: Record<string, WorkflowMeasuredSize> = {};
  for (const change of accepted) {
    if (change.type !== "dimensions" || !change.dimensions) continue;
    const { width, height } = change.dimensions;
    if (!Number.isFinite(width) || !Number.isFinite(height)) continue;
    measured[change.id] = { width, height };
  }

  let selectedId: string | null | undefined;
  if (accepted.some((change) => change.type === "select")) {
    const picked = next.find((node) => node.selected && node.selectable !== false);
    selectedId = picked?.id ?? null;
  }

  const dragging = accepted.some((change) => change.type === "position" && change.dragging === true);
  const positions: Record<string, { x: number; y: number }> = {};
  if (!dragging) {
    const previous = new Map(nodes.map((node) => [node.id, node]));
    for (const change of accepted) {
      if (change.type !== "position" || !change.position || change.dragging) continue;
      const before = previous.get(change.id);
      if (!before || before.type === "stageRegion") continue;
      positions[change.id] = { x: change.position.x, y: change.position.y };
    }
  }

  return { measured, selectedId, positions, dragging };
}
