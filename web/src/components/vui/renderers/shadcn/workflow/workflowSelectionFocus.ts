/**
 * Observer-canvas selection helpers: which edges belong to the selected card,
 * and where to pan when selection originates outside the canvas.
 *
 * Topology never changes here. Pan is a viewport move only.
 */

export function workflowEdgeTouchesNode(
  source: string,
  target: string,
  nodeId: string | null | undefined,
): boolean {
  return typeof nodeId === "string" && nodeId.length > 0 && (source === nodeId || target === nodeId);
}

export function shouldPanWorkflowSelectionIntoView(input: {
  selectedNodeId: string | null | undefined;
  canvasOriginNodeId: string | null;
  lastPannedNodeId: string | null;
  pendingInitialFit: boolean;
  nodesInitialized: boolean;
}): boolean {
  if (typeof input.selectedNodeId !== "string" || input.selectedNodeId.length === 0) {
    return false;
  }
  if (input.canvasOriginNodeId === input.selectedNodeId) return false;
  if (input.lastPannedNodeId === input.selectedNodeId) return false;
  if (input.pendingInitialFit || !input.nodesInitialized) return false;
  return true;
}

type FocusableNode = {
  position: { x: number; y: number };
  width?: number | null;
  height?: number | null;
  parentId?: string | null;
  measured?: { width?: number; height?: number };
  style?: { width?: number | string; height?: number | string };
};

const DEFAULT_FOCUS_WIDTH = 300;
const DEFAULT_FOCUS_HEIGHT = 72;

export function resolveWorkflowNodeFocusCenter(
  node: FocusableNode,
  getNode: (id: string) => FocusableNode | undefined,
): { x: number; y: number } {
  const width = positiveDimension(
    node.measured?.width,
    node.width,
    node.style?.width,
  ) ?? DEFAULT_FOCUS_WIDTH;
  const height = positiveDimension(
    node.measured?.height,
    node.height,
    node.style?.height,
  ) ?? DEFAULT_FOCUS_HEIGHT;
  let x = node.position.x + width / 2;
  let y = node.position.y + height / 2;
  if (node.parentId) {
    const parent = getNode(node.parentId);
    if (parent) {
      x += parent.position.x;
      y += parent.position.y;
    }
  }
  return { x, y };
}

function positiveDimension(...values: Array<number | string | null | undefined>): number | undefined {
  for (const value of values) {
    if (typeof value === "number" && Number.isFinite(value) && value > 0) return value;
    if (typeof value === "string") {
      const parsed = Number.parseFloat(value);
      if (Number.isFinite(parsed) && parsed > 0) return parsed;
    }
  }
  return undefined;
}
