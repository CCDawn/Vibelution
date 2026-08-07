/**
 * Shared collision detection for layout tests and dev diagnostics.
 *
 * Pure geometry: rect/rect and segment/rect overlap, with optional safety
 * padding so tests can enforce the design's minimum distances.
 */
import type { WorkflowLayoutPoint } from "../../../product/workflow/workflowCanvasTypes";

export type RectLike = { x: number; y: number; width: number; height: number };
export type PointLike = { x: number; y: number };

export function rectsOverlap(a: RectLike, b: RectLike): boolean {
  return (
    a.x < b.x + b.width &&
    b.x < a.x + a.width &&
    a.y < b.y + b.height &&
    b.y < a.y + a.height
  );
}

export function paddedRect(r: RectLike, pad: number): RectLike {
  return { x: r.x - pad, y: r.y - pad, width: r.width + pad * 2, height: r.height + pad * 2 };
}

/**
 * Conservative segment-vs-rect test: true when the segment's bounding box
 * intersects the (optionally padded) rect. Exact for axis-aligned segments,
 * conservative for diagonal ones.
 */
export function segmentIntersectsRect(
  a: PointLike,
  b: PointLike,
  rect: RectLike,
  pad = 0,
): boolean {
  const r = paddedRect(rect, pad);
  const minX = Math.min(a.x, b.x);
  const maxX = Math.max(a.x, b.x);
  const minY = Math.min(a.y, b.y);
  const maxY = Math.max(a.y, b.y);
  return maxX >= r.x && minX <= r.x + r.width && maxY >= r.y && minY <= r.y + r.height;
}

export function pointInRectStrictly(p: PointLike, r: RectLike): boolean {
  return p.x > r.x && p.x < r.x + r.width && p.y > r.y && p.y < r.y + r.height;
}

export function centerOf(r: RectLike): PointLike {
  return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
}

export type { WorkflowLayoutPoint };
