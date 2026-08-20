/**
 * Alignment guides for serpentine manual card drag.
 *
 * Compare the dragged card's left / center / right and top / center / bottom
 * to every other task card. Within the threshold, snap that axis and report
 * the alignment coordinate so the overlay can paint a 1px screen-space guide.
 * Unaligned axes fall back to the 16px grid. This is the draw.io / JointJS /
 * MIT xyflow-helper-line algorithm; it is not the Pro example source.
 */

import { snapWorkflowManualPosition } from "./workflowManualLayout";

export const WORKFLOW_HELPER_LINE_THRESHOLD = 8;

export type WorkflowHelperRect = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type WorkflowHelperLines = {
  vertical?: number;
  horizontal?: number;
};

export type WorkflowHelperSnapResult = {
  position: { x: number; y: number };
  lines: WorkflowHelperLines;
};

type AxisSnap = {
  distance: number;
  position: number;
  line: number;
};

function considerAxis(
  current: AxisSnap | null,
  dragCoord: number,
  origin: number,
  otherCoord: number,
  threshold: number,
): AxisSnap | null {
  const distance = Math.abs(dragCoord - otherCoord);
  if (distance > threshold) return current;
  if (current !== null && distance >= current.distance) return current;
  return { distance, position: otherCoord - origin, line: otherCoord };
}

export function snapWorkflowNodeToHelpers(input: {
  position: { x: number; y: number };
  width: number;
  height: number;
  others: readonly WorkflowHelperRect[];
  threshold?: number;
}): WorkflowHelperSnapResult {
  const threshold = input.threshold ?? WORKFLOW_HELPER_LINE_THRESHOLD;
  const { width, height } = input;
  const left = input.position.x;
  const top = input.position.y;
  let bestX: AxisSnap | null = null;
  let bestY: AxisSnap | null = null;

  for (const other of input.others) {
    if (!(other.width > 0) || !(other.height > 0)) continue;
    const otherXs = [other.x, other.x + other.width / 2, other.x + other.width];
    const otherYs = [other.y, other.y + other.height / 2, other.y + other.height];
    const dragXs = [
      { coord: left, origin: 0 },
      { coord: left + width / 2, origin: width / 2 },
      { coord: left + width, origin: width },
    ];
    const dragYs = [
      { coord: top, origin: 0 },
      { coord: top + height / 2, origin: height / 2 },
      { coord: top + height, origin: height },
    ];
    for (const drag of dragXs) {
      for (const line of otherXs) {
        bestX = considerAxis(bestX, drag.coord, drag.origin, line, threshold);
      }
    }
    for (const drag of dragYs) {
      for (const line of otherYs) {
        bestY = considerAxis(bestY, drag.coord, drag.origin, line, threshold);
      }
    }
  }

  return {
    position: {
      x: bestX?.position ?? input.position.x,
      y: bestY?.position ?? input.position.y,
    },
    lines: {
      ...(bestX ? { vertical: bestX.line } : {}),
      ...(bestY ? { horizontal: bestY.line } : {}),
    },
  };
}

/** Helper snap wins per axis; the other axis stays on the 16px grid. */
export function resolveWorkflowManualCardDrag(input: {
  position: { x: number; y: number };
  width: number;
  height: number;
  others: readonly WorkflowHelperRect[];
  threshold?: number;
}): WorkflowHelperSnapResult {
  if (!(input.width > 0) || !(input.height > 0)) {
    return { position: snapWorkflowManualPosition(input.position), lines: {} };
  }
  const helper = snapWorkflowNodeToHelpers(input);
  const grid = snapWorkflowManualPosition(input.position);
  return {
    position: {
      x: helper.lines.vertical != null ? helper.position.x : grid.x,
      y: helper.lines.horizontal != null ? helper.position.y : grid.y,
    },
    lines: helper.lines,
  };
}

/** Flow-space half-extent so portal guides cross the visible canvas at any pan. */
export const WORKFLOW_HELPER_LINE_SPAN = 100_000;

export function workflowHelperLineToScreen(flowCoord: number, origin: number, zoom: number): number {
  return flowCoord * zoom + origin;
}

/** Keep helper strokes ~1px on screen after the viewport scale is applied. */
export function resolveWorkflowHelperOverlayStroke(zoom: number): { strokeWidth: number; dasharray: string } {
  const safeZoom = Number.isFinite(zoom) && zoom > 0 ? zoom : 1;
  return {
    strokeWidth: 1 / safeZoom,
    dasharray: `${6 / safeZoom} ${4 / safeZoom}`,
  };
}

export function workflowHelperLinesActive(lines: WorkflowHelperLines | null | undefined): boolean {
  return lines != null && (lines.vertical != null || lines.horizontal != null);
}
