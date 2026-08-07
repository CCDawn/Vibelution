/**
 * Pure geometry helpers for the two-level workflow layout.
 *
 * No ELK, no React Flow, no state. Used by the stage layout, meta layout,
 * cross-stage router and the geometry acceptance tests.
 */

export type Rect = { x: number; y: number; width: number; height: number };

export type Point = { x: number; y: number };

export function rectOf(node: { x: number; y: number; width: number; height: number }): Rect {
  return { x: node.x, y: node.y, width: node.width, height: node.height };
}

export function rectsOverlap(a: Rect, b: Rect): boolean {
  return (
    a.x < b.x + b.width &&
    b.x < a.x + a.width &&
    a.y < b.y + b.height &&
    b.y < a.y + a.height
  );
}

export function pointInRect(p: Point, r: Rect): boolean {
  return p.x >= r.x && p.x <= r.x + r.width && p.y >= r.y && p.y <= r.y + r.height;
}

/** Strict interior test: the point must be strictly inside the rect. */
export function pointStrictlyInRect(p: Point, r: Rect): boolean {
  return p.x > r.x && p.x < r.x + r.width && p.y > r.y && p.y < r.y + r.height;
}

/**
 * AABB of a set of rects; returns null for an empty set.
 */
export function boundsOf(rects: Rect[]): Rect | null {
  if (rects.length === 0) {
    return null;
  }
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const r of rects) {
    minX = Math.min(minX, r.x);
    minY = Math.min(minY, r.y);
    maxX = Math.max(maxX, r.x + r.width);
    maxY = Math.max(maxY, r.y + r.height);
  }
  return { x: minX, y: minY, width: maxX - minX, height: maxY - minY };
}

/**
 * True when the horizontal band of `a` overlaps the horizontal band of `b`
 * (used to detect stacked rows that share the same column region).
 */
export function horizontalBandsOverlap(a: Rect, b: Rect): boolean {
  return a.y < b.y + b.height && b.y < a.y + a.height;
}

/**
 * Signed horizontal distance between two rects (positive when `b` is fully to
 * the right of `a` with a gap, 0 when overlapping/adjacent).
 */
export function horizontalGap(a: Rect, b: Rect): number {
  if (a.x + a.width <= b.x) {
    return b.x - (a.x + a.width);
  }
  if (b.x + b.width <= a.x) {
    return a.x - (b.x + b.width);
  }
  return 0;
}

/**
 * Center of a rect.
 */
export function centerOf(r: Rect): Point {
  return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
}

/**
 * Vertical gap between two rects on the same column: distance from the bottom
 * of the upper rect to the top of the lower rect. Negative when overlapping.
 */
export function verticalGap(upper: Rect, lower: Rect): number {
  return lower.y - (upper.y + upper.height);
}
