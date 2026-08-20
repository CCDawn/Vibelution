/**
 * Alignment guides for serpentine manual card drag.
 *
 * Compare the dragged card's left / center / right and top / center / bottom
 * to every other task card. Snap engages within 8px. Once an axis is held,
 * it stays on that line until the pointer is more than 16px away, so vertical
 * drags do not chatter between a neighbor's top / center / bottom or the 16px
 * grid. Unaligned axes fall back to the 16px grid. This is the draw.io /
 * JointJS / MIT xyflow-helper-line algorithm plus sticky hold; it is not the
 * Pro example source.
 */

import { snapWorkflowManualPosition } from "./workflowManualLayout";

export const WORKFLOW_HELPER_LINE_THRESHOLD = 8;
export const WORKFLOW_HELPER_LINE_RELEASE = 16;

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

export type WorkflowHelperSnapHold = {
  vertical?: number;
  horizontal?: number;
};

export type WorkflowHelperSnapResult = {
  position: { x: number; y: number };
  lines: WorkflowHelperLines;
};

export type WorkflowManualCardDragResult = WorkflowHelperSnapResult & {
  hold: WorkflowHelperSnapHold;
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

function axisDistanceToLine(position: number, size: number, line: number): number {
  return Math.min(
    Math.abs(position - line),
    Math.abs(position + size / 2 - line),
    Math.abs(position + size - line),
  );
}

function snapAxisToLine(position: number, size: number, line: number): number {
  const origins = [0, size / 2, size];
  let bestOrigin = 0;
  let bestDistance = Number.POSITIVE_INFINITY;
  for (const origin of origins) {
    const distance = Math.abs(position + origin - line);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestOrigin = origin;
    }
  }
  return line - bestOrigin;
}

function resolveHeldAxis(input: {
  raw: number;
  size: number;
  heldLine?: number;
  helperLine?: number;
  helperPosition: number;
  grid: number;
  release: number;
}): { position: number; line?: number; hold?: number } {
  if (input.heldLine != null && axisDistanceToLine(input.raw, input.size, input.heldLine) <= input.release) {
    return {
      position: snapAxisToLine(input.raw, input.size, input.heldLine),
      line: input.heldLine,
      hold: input.heldLine,
    };
  }
  if (input.helperLine != null) {
    return {
      position: input.helperPosition,
      line: input.helperLine,
      hold: input.helperLine,
    };
  }
  return { position: input.grid };
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
  release?: number;
  hold?: WorkflowHelperSnapHold | null;
}): WorkflowManualCardDragResult {
  if (!(input.width > 0) || !(input.height > 0)) {
    return { position: snapWorkflowManualPosition(input.position), lines: {}, hold: {} };
  }
  const helper = snapWorkflowNodeToHelpers(input);
  const grid = snapWorkflowManualPosition(input.position);
  const release = input.release ?? WORKFLOW_HELPER_LINE_RELEASE;
  const x = resolveHeldAxis({
    raw: input.position.x,
    size: input.width,
    heldLine: input.hold?.vertical,
    helperLine: helper.lines.vertical,
    helperPosition: helper.position.x,
    grid: grid.x,
    release,
  });
  const y = resolveHeldAxis({
    raw: input.position.y,
    size: input.height,
    heldLine: input.hold?.horizontal,
    helperLine: helper.lines.horizontal,
    helperPosition: helper.position.y,
    grid: grid.y,
    release,
  });
  return {
    position: { x: x.position, y: y.position },
    lines: {
      ...(x.line != null ? { vertical: x.line } : {}),
      ...(y.line != null ? { horizontal: y.line } : {}),
    },
    hold: {
      ...(x.hold != null ? { vertical: x.hold } : {}),
      ...(y.hold != null ? { horizontal: y.hold } : {}),
    },
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

export function workflowHelperLinesEqual(
  a: WorkflowHelperLines | null | undefined,
  b: WorkflowHelperLines | null | undefined,
): boolean {
  return (a?.vertical ?? undefined) === (b?.vertical ?? undefined)
    && (a?.horizontal ?? undefined) === (b?.horizontal ?? undefined);
}
