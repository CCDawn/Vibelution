/**
 * Browser-local presentation overrides for the editable serpentine workflow
 * canvas. These values never enter the workflow graph or runtime projection:
 * ELK remains the initial / auto-arrange geometry authority.
 */

import {
  cloneWorkflowEdgeAnchors,
  parseWorkflowEdgeAnchors,
  type WorkflowEdgeAnchors,
} from "./workflowEdgeAnchors";

export const WORKFLOW_MANUAL_LAYOUT_GRID = 16;
export const WORKFLOW_EDGE_TERMINAL_STUB = 32;
export const WORKFLOW_STAGE_LABEL_WIDTH = 240;
export const WORKFLOW_STAGE_LABEL_HEIGHT = 32;
export const WORKFLOW_STAGE_LABEL_GAP = 20;
const STORAGE_PREFIX = "vibelution.workflow-manual-layout.v1";

export type WorkflowManualPosition = { x: number; y: number };
export type WorkflowManualPositions = Record<string, WorkflowManualPosition>;

export type WorkflowManualLayoutScope = {
  structureKey: string;
  runId: string | null;
  nodeIds: readonly string[];
  stageIds: readonly string[];
};

export type WorkflowManualLayoutState = {
  positions: WorkflowManualPositions;
  stageLabelOffsets: WorkflowManualPositions;
  edgeAnchors: WorkflowEdgeAnchors;
  locked: boolean;
};

type StoredWorkflowManualLayoutV1 = Omit<WorkflowManualLayoutState, "stageLabelOffsets" | "edgeAnchors"> & {
  version: 1;
  structureKey: string;
  runId: string | null;
  nodeIds: string[];
};

type StoredWorkflowManualLayoutV2 = Omit<WorkflowManualLayoutState, "edgeAnchors"> & {
  version: 2;
  structureKey: string;
  runId: string | null;
  nodeIds: string[];
  stageIds: string[];
};

type StoredWorkflowManualLayoutV3 = WorkflowManualLayoutState & {
  version: 3;
  structureKey: string;
  runId: string | null;
  nodeIds: string[];
  stageIds: string[];
};

type StorageLike = Pick<Storage, "getItem" | "setItem">;

const EMPTY_STATE: WorkflowManualLayoutState = {
  positions: {},
  stageLabelOffsets: {},
  edgeAnchors: {},
  locked: false,
};

export function snapWorkflowManualPosition(
  position: WorkflowManualPosition,
  grid = WORKFLOW_MANUAL_LAYOUT_GRID,
): WorkflowManualPosition {
  return {
    x: Math.round(position.x / grid) * grid,
    y: Math.round(position.y / grid) * grid,
  };
}

export function workflowManualLayoutStorageKey(scope: Pick<WorkflowManualLayoutScope, "structureKey" | "runId">): string {
  return `${STORAGE_PREFIX}:${encodeURIComponent(scope.structureKey)}:${encodeURIComponent(scope.runId ?? "definition")}`;
}

export function readWorkflowManualLayout(
  scope: WorkflowManualLayoutScope,
  storage: StorageLike | null = browserStorage(),
): WorkflowManualLayoutState {
  if (!storage || !scope.structureKey) return EMPTY_STATE;
  try {
    const value = storage.getItem(workflowManualLayoutStorageKey(scope));
    if (!value) return EMPTY_STATE;
    const stored = JSON.parse(value) as Partial<
      StoredWorkflowManualLayoutV1 | StoredWorkflowManualLayoutV2 | StoredWorkflowManualLayoutV3
    >;
    if (
      (stored.version !== 1 && stored.version !== 2 && stored.version !== 3)
      || stored.structureKey !== scope.structureKey
      || stored.runId !== scope.runId
      || !Array.isArray(stored.nodeIds)
      || !sameNodeSet(stored.nodeIds, scope.nodeIds)
      || !isRecord(stored.positions)
      || typeof stored.locked !== "boolean"
    ) {
      return EMPTY_STATE;
    }
    const validIds = new Set(scope.nodeIds);
    const positions: WorkflowManualPositions = {};
    for (const [id, position] of Object.entries(stored.positions)) {
      if (validIds.has(id) && isPosition(position)) {
        positions[id] = snapWorkflowManualPosition(position);
      }
    }
    const stageLabelOffsets: WorkflowManualPositions = {};
    if (stored.version === 2 || stored.version === 3) {
      if (!Array.isArray(stored.stageIds) || !sameNodeSet(stored.stageIds, scope.stageIds) || !isRecord(stored.stageLabelOffsets)) {
        return EMPTY_STATE;
      }
      const validStageIds = new Set(scope.stageIds);
      for (const [id, offset] of Object.entries(stored.stageLabelOffsets)) {
        if (validStageIds.has(id) && isPosition(offset)) {
          stageLabelOffsets[id] = snapWorkflowManualPosition(offset);
        }
      }
    }
    const edgeAnchors = stored.version === 3 ? parseWorkflowEdgeAnchors(stored.edgeAnchors) : {};
    return { positions, stageLabelOffsets, edgeAnchors, locked: stored.locked };
  } catch {
    return EMPTY_STATE;
  }
}

export function persistWorkflowManualLayout(
  scope: WorkflowManualLayoutScope,
  state: WorkflowManualLayoutState,
  storage: StorageLike | null = browserStorage(),
): void {
  if (!storage || !scope.structureKey) return;
  const validIds = new Set(scope.nodeIds);
  const positions = Object.fromEntries(
    Object.entries(state.positions)
      .filter(([id, position]) => validIds.has(id) && isPosition(position))
      .map(([id, position]) => [id, snapWorkflowManualPosition(position)]),
  );
  const validStageIds = new Set(scope.stageIds);
  const stageLabelOffsets = Object.fromEntries(
    Object.entries(state.stageLabelOffsets)
      .filter(([id, position]) => validStageIds.has(id) && isPosition(position))
      .map(([id, position]) => [id, snapWorkflowManualPosition(position)]),
  );
  const payload: StoredWorkflowManualLayoutV3 = {
    version: 3,
    structureKey: scope.structureKey,
    runId: scope.runId,
    nodeIds: [...scope.nodeIds].sort(),
    stageIds: [...scope.stageIds].sort(),
    positions,
    stageLabelOffsets,
    edgeAnchors: cloneWorkflowEdgeAnchors(state.edgeAnchors ?? {}),
    locked: state.locked,
  };
  try {
    storage.setItem(workflowManualLayoutStorageKey(scope), JSON.stringify(payload));
  } catch {
    // Storage can be disabled or full. The in-memory arrangement remains usable.
  }
}

export function cloneWorkflowManualPositions(positions: WorkflowManualPositions): WorkflowManualPositions {
  return Object.fromEntries(
    Object.entries(positions).map(([id, position]) => [id, { ...position }]),
  );
}

export type WorkflowManualLayoutSnapshot = Pick<
  WorkflowManualLayoutState,
  "positions" | "stageLabelOffsets" | "edgeAnchors"
>;

export function cloneWorkflowManualLayoutSnapshot(snapshot: WorkflowManualLayoutSnapshot): WorkflowManualLayoutSnapshot {
  return {
    positions: cloneWorkflowManualPositions(snapshot.positions),
    stageLabelOffsets: cloneWorkflowManualPositions(snapshot.stageLabelOffsets),
    edgeAnchors: cloneWorkflowEdgeAnchors(snapshot.edgeAnchors ?? {}),
  };
}

export type WorkflowStageMemberGeometry = WorkflowManualPosition & { width: number; height: number };

/** Stage identity comes from graph membership; screen position only places its compact label. */
export function resolveWorkflowStageLabelPosition(
  members: readonly WorkflowStageMemberGeometry[],
  offset: WorkflowManualPosition = { x: 0, y: 0 },
  fallback: WorkflowManualPosition = { x: 0, y: 0 },
): WorkflowManualPosition {
  const anchor = members.length > 0
    ? {
        x: Math.min(...members.map((member) => member.x)),
        y: Math.min(...members.map((member) => member.y)) - WORKFLOW_STAGE_LABEL_HEIGHT - WORKFLOW_STAGE_LABEL_GAP,
      }
    : fallback;
  return { x: anchor.x + offset.x, y: anchor.y + offset.y };
}

export type WorkflowEdgeTerminalSide = "left" | "right" | "top" | "bottom";

export function workflowEdgeTerminalLead(
  endpoint: WorkflowManualPosition,
  side: WorkflowEdgeTerminalSide,
  distance = WORKFLOW_EDGE_TERMINAL_STUB,
): WorkflowManualPosition {
  if (side === "left") return { x: endpoint.x - distance, y: endpoint.y };
  if (side === "right") return { x: endpoint.x + distance, y: endpoint.y };
  if (side === "top") return { x: endpoint.x, y: endpoint.y - distance };
  return { x: endpoint.x, y: endpoint.y + distance };
}

/** A minimal orthogonal route for live drag feedback after ELK geometry is overridden. */
export function resolveWorkflowManualEdgeGeometry(
  source: WorkflowManualPosition,
  target: WorkflowManualPosition,
  sourceSide: WorkflowEdgeTerminalSide = "right",
  targetSide: WorkflowEdgeTerminalSide = "left",
): { path: string; labelAnchor: WorkflowManualPosition } {
  const sourceLead = workflowEdgeTerminalLead(source, sourceSide);
  const targetLead = workflowEdgeTerminalLead(target, targetSide);
  const dx = targetLead.x - sourceLead.x;
  const dy = targetLead.y - sourceLead.y;
  let body: WorkflowManualPosition[];
  if (Math.abs(dx) >= Math.abs(dy)) {
    const middleX = sourceLead.x + dx / 2;
    body = [sourceLead, { x: middleX, y: sourceLead.y }, { x: middleX, y: targetLead.y }, targetLead];
  } else {
    const middleY = sourceLead.y + dy / 2;
    body = [sourceLead, { x: sourceLead.x, y: middleY }, { x: targetLead.x, y: middleY }, targetLead];
  }
  const points = dedupeConsecutivePoints([source, ...body, target]);
  return {
    path: points.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`).join(" "),
    labelAnchor: { x: sourceLead.x + dx / 2, y: sourceLead.y + dy / 2 },
  };
}

function dedupeConsecutivePoints(points: readonly WorkflowManualPosition[]): WorkflowManualPosition[] {
  return points.filter((point, index) => index === 0 || point.x !== points[index - 1]?.x || point.y !== points[index - 1]?.y);
}

function browserStorage(): StorageLike | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isPosition(value: unknown): value is WorkflowManualPosition {
  return isRecord(value)
    && typeof value.x === "number"
    && Number.isFinite(value.x)
    && typeof value.y === "number"
    && Number.isFinite(value.y);
}

function sameNodeSet(a: readonly string[], b: readonly string[]): boolean {
  if (a.length !== b.length) return false;
  const expected = new Set(a);
  return expected.size === b.length && b.every((id) => expected.has(id));
}
