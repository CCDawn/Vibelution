/**
 * Browser-local presentation overrides for the editable serpentine workflow
 * canvas. These values never enter the workflow graph or runtime projection:
 * ELK remains the initial / auto-arrange geometry authority.
 */

export const WORKFLOW_MANUAL_LAYOUT_GRID = 16;
const STORAGE_PREFIX = "vibelution.workflow-manual-layout.v1";

export type WorkflowManualPosition = { x: number; y: number };
export type WorkflowManualPositions = Record<string, WorkflowManualPosition>;

export type WorkflowManualLayoutScope = {
  structureKey: string;
  runId: string | null;
  nodeIds: readonly string[];
};

export type WorkflowManualLayoutState = {
  positions: WorkflowManualPositions;
  locked: boolean;
};

type StoredWorkflowManualLayout = WorkflowManualLayoutState & {
  version: 1;
  structureKey: string;
  runId: string | null;
  nodeIds: string[];
};

type StorageLike = Pick<Storage, "getItem" | "setItem">;

const EMPTY_STATE: WorkflowManualLayoutState = { positions: {}, locked: false };

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
    const stored = JSON.parse(value) as Partial<StoredWorkflowManualLayout>;
    if (
      stored.version !== 1
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
    return { positions, locked: stored.locked };
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
  const payload: StoredWorkflowManualLayout = {
    version: 1,
    structureKey: scope.structureKey,
    runId: scope.runId,
    nodeIds: [...scope.nodeIds].sort(),
    positions,
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

/** A minimal orthogonal route for live drag feedback after ELK geometry is overridden. */
export function resolveWorkflowManualEdgeGeometry(
  source: WorkflowManualPosition,
  target: WorkflowManualPosition,
): { path: string; labelAnchor: WorkflowManualPosition } {
  const dx = target.x - source.x;
  const dy = target.y - source.y;
  if (Math.abs(dx) >= Math.abs(dy)) {
    const middleX = source.x + dx / 2;
    return {
      path: `M ${source.x} ${source.y} L ${middleX} ${source.y} L ${middleX} ${target.y} L ${target.x} ${target.y}`,
      labelAnchor: { x: middleX, y: source.y + dy / 2 },
    };
  }
  const middleY = source.y + dy / 2;
  return {
    path: `M ${source.x} ${source.y} L ${source.x} ${middleY} L ${target.x} ${middleY} L ${target.x} ${target.y}`,
    labelAnchor: { x: source.x + dx / 2, y: middleY },
  };
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
