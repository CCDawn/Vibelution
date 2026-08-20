/**
 * Geometry-aware orthogonal connector for serpentine auto-layout edges.
 *
 * ELK still owns node placement. After boxes are known, this module picks
 * facing sides and a Manhattan body the way draw.io OrthConnector / JointJS
 * rightAngle do:
 *  - leave toward the target, with a horizontal bias (R2);
 *  - arrive on the facing side (R3);
 *  - keep a straight stub before the first bend (R1);
 *  - prefer a one-bend L, then a two-bend Z (JointJS rightAngle). Other
 *    cards are ignored unless that simple elbow actually crosses their
 *    interior; only then take a lane around the blocking card, not around
 *    the union of every card in the source–target hull (R7);
 *  - same-side ends (incoming and outgoing) share one magnet set (R4):
 *    project the far card, snap to 3/5 slots, keep opposite order so
 *    stubs do not cross or stack on the box.
 *
 * Not a port of mxGraph. Only those side-selection, magnet, and obstacle
 * rules are reused; output is the existing WorkflowEdgeSection polyline.
 */
import type {
  WorkflowLayoutPoint,
  WorkflowPortSide,
} from "../../../product/workflow/workflowCanvasTypes";

export type OrthogonalSide = "left" | "right" | "top" | "bottom";

export type OrthogonalRect = { x: number; y: number; width: number; height: number };

export const WORKFLOW_ORTHOGONAL_STUB = 20;
export const WORKFLOW_ORTHOGONAL_PADDING = 8;
/** Left/right sides of a 72px serpentine card: three magnets. */
export const WORKFLOW_SNAP_SLOTS_SHORT = [0.25, 0.5, 0.75] as const;
/** Top/bottom of a wide card: five magnets, draw.io relative 1/6…5/6. */
export const WORKFLOW_SNAP_SLOTS_LONG = [1 / 6, 2 / 6, 3 / 6, 4 / 6, 5 / 6] as const;
const SNAP_INSET = 0.18;

export function elkSideFromOrthogonal(side: OrthogonalSide): WorkflowPortSide {
  if (side === "left") return "WEST";
  if (side === "right") return "EAST";
  if (side === "top") return "NORTH";
  return "SOUTH";
}

export function orthogonalFromElkSide(side: WorkflowPortSide): OrthogonalSide {
  if (side === "WEST") return "left";
  if (side === "EAST") return "right";
  if (side === "NORTH") return "top";
  return "bottom";
}

export function snapSlotsForSide(side: OrthogonalSide): readonly number[] {
  return side === "left" || side === "right" ? WORKFLOW_SNAP_SLOTS_SHORT : WORKFLOW_SNAP_SLOTS_LONG;
}

export function projectedSnapFraction(
  rect: OrthogonalRect,
  side: OrthogonalSide,
  far: OrthogonalRect,
): number {
  const raw = side === "left" || side === "right"
    ? (centerY(far) - rect.y) / Math.max(rect.height, 1)
    : (centerX(far) - rect.x) / Math.max(rect.width, 1);
  return Math.min(1 - SNAP_INSET, Math.max(SNAP_INSET, raw));
}

/**
 * Assign unique magnets on one side. k=1 snaps to the nearest slot of the
 * far card; k>1 keeps draw.io R4 order (sort by opposite coordinate) so
 * stubs do not cross or stack on the box edge. Incoming and outgoing ends
 * on the same side must share this assignment.
 */
export function assignSnapFractions(
  items: ReadonlyArray<{ id: string; preferred: number }>,
  slots: readonly number[],
): Map<string, number> {
  const result = new Map<string, number>();
  if (items.length === 0 || slots.length === 0) return result;
  const sorted = [...items].sort((a, b) => a.preferred - b.preferred || a.id.localeCompare(b.id));
  if (sorted.length === 1) {
    result.set(sorted[0]!.id, nearestSlot(sorted[0]!.preferred, slots));
    return result;
  }
  if (sorted.length <= slots.length) {
    const used = new Set<number>();
    let last = Number.NEGATIVE_INFINITY;
    for (const item of sorted) {
      const remaining = slots.filter((slot) => !used.has(slot) && slot + 1e-9 >= last);
      const pool = remaining.length > 0 ? remaining : slots.filter((slot) => !used.has(slot));
      const chosen = nearestSlot(item.preferred, pool);
      used.add(chosen);
      last = chosen;
      result.set(item.id, chosen);
    }
    return result;
  }
  sorted.forEach((item, index) => {
    result.set(item.id, (index + 1) / (sorted.length + 1));
  });
  return result;
}

function nearestSlot(preferred: number, slots: readonly number[]): number {
  return slots.reduce(
    (best, slot) => (Math.abs(slot - preferred) < Math.abs(best - preferred) - 1e-9 ? slot : best),
    slots[0]!,
  );
}

export function facingOrthogonalSides(
  source: OrthogonalRect,
  target: OrthogonalRect,
): { source: OrthogonalSide; target: OrthogonalSide } {
  const overlapX = rangesOverlap(source.x, source.x + source.width, target.x, target.x + target.width);
  const overlapY = rangesOverlap(source.y, source.y + source.height, target.y, target.y + target.height);
  const dx = centerX(target) - centerX(source);
  const dy = centerY(target) - centerY(source);

  if (overlapX && !overlapY) {
    return dy >= 0
      ? { source: "bottom", target: "top" }
      : { source: "top", target: "bottom" };
  }
  if (overlapY && !overlapX) {
    return dx >= 0
      ? { source: "right", target: "left" }
      : { source: "left", target: "right" };
  }
  // Diagonal: slight horizontal bias so side-by-side cards with a small
  // vertical drift still use a short east-west bridge.
  if (Math.abs(dx) >= Math.abs(dy) * 0.75) {
    return dx >= 0
      ? { source: "right", target: "left" }
      : { source: "left", target: "right" };
  }
  return dy >= 0
    ? { source: "bottom", target: "top" }
    : { source: "top", target: "bottom" };
}

export function portPointOnRect(
  rect: OrthogonalRect,
  side: OrthogonalSide,
  fraction = 0.5,
): WorkflowLayoutPoint {
  const t = Math.min(1, Math.max(0, fraction));
  if (side === "left") return { x: rect.x, y: rect.y + rect.height * t };
  if (side === "right") return { x: rect.x + rect.width, y: rect.y + rect.height * t };
  if (side === "top") return { x: rect.x + rect.width * t, y: rect.y };
  return { x: rect.x + rect.width * t, y: rect.y + rect.height };
}

export function orthogonalLead(
  point: WorkflowLayoutPoint,
  side: OrthogonalSide,
  distance = WORKFLOW_ORTHOGONAL_STUB,
): WorkflowLayoutPoint {
  if (side === "left") return { x: point.x - distance, y: point.y };
  if (side === "right") return { x: point.x + distance, y: point.y };
  if (side === "top") return { x: point.x, y: point.y - distance };
  return { x: point.x, y: point.y + distance };
}

export function routeOrthogonalConnector(input: {
  source: OrthogonalRect;
  target: OrthogonalRect;
  sourceSide?: OrthogonalSide;
  targetSide?: OrthogonalSide;
  sourceFraction?: number;
  targetFraction?: number;
  obstacles?: readonly OrthogonalRect[];
  stub?: number;
  padding?: number;
}): {
  points: WorkflowLayoutPoint[];
  sourceSide: OrthogonalSide;
  targetSide: OrthogonalSide;
} {
  const preferred = input.sourceSide && input.targetSide
    ? [{ source: input.sourceSide, target: input.targetSide }]
    : facingSideCandidates(input.source, input.target);
  const stub = input.stub ?? WORKFLOW_ORTHOGONAL_STUB;
  const padding = input.padding ?? WORKFLOW_ORTHOGONAL_PADDING;
  const obstacles = (input.obstacles ?? []).filter(
    (rect) => rect !== input.source && rect !== input.target && !sameRect(rect, input.source) && !sameRect(rect, input.target),
  );

  const scored: Array<{
    points: WorkflowLayoutPoint[];
    hits: number;
    length: number;
    bends: number;
    sourceSide: OrthogonalSide;
    targetSide: OrthogonalSide;
  }> = [];

  const scoreBody = (
    sides: { source: OrthogonalSide; target: OrthogonalSide },
    start: WorkflowLayoutPoint,
    end: WorkflowLayoutPoint,
    body: WorkflowLayoutPoint[],
  ) => {
    const points = compactPoints([start, ...body, end]);
    if (points.length < 2) return;
    scored.push({
      points,
      // Interior crossings only. A padded graze is not a reason to pick a
      // six-bend hull skirt the way JointJS rightAngle ignores other nodes.
      hits: countObstacleHits(points, obstacles, 0, input.source, input.target),
      length: polylineLength(points),
      bends: Math.max(0, points.length - 2),
      sourceSide: sides.source,
      targetSide: sides.target,
    });
  };

  for (const sides of preferred) {
    const start = portPointOnRect(input.source, sides.source, input.sourceFraction ?? 0.5);
    const end = portPointOnRect(input.target, sides.target, input.targetFraction ?? 0.5);
    const sourceLead = orthogonalLead(start, sides.source, stub);
    const targetLead = orthogonalLead(end, sides.target, stub);
    for (const body of simpleConnectorBodies(sourceLead, targetLead)) {
      scoreBody(sides, start, end, body);
    }
  }
  scored.sort(compareOrthogonalScores);
  const bestSimple = scored[0];
  if (bestSimple && bestSimple.hits === 0) {
    return { points: bestSimple.points, sourceSide: bestSimple.sourceSide, targetSide: bestSimple.targetSide };
  }

  for (const sides of preferred) {
    const start = portPointOnRect(input.source, sides.source, input.sourceFraction ?? 0.5);
    const end = portPointOnRect(input.target, sides.target, input.targetFraction ?? 0.5);
    const sourceLead = orthogonalLead(start, sides.source, stub);
    const targetLead = orthogonalLead(end, sides.target, stub);
    for (const body of detourConnectorBodies(sourceLead, targetLead, input.source, input.target, stub, padding, obstacles)) {
      scoreBody(sides, start, end, body);
    }
  }
  scored.sort(compareOrthogonalScores);
  const winner = scored[0];
  if (!winner) {
    const sides = preferred[0]!;
    const start = portPointOnRect(input.source, sides.source, input.sourceFraction ?? 0.5);
    const end = portPointOnRect(input.target, sides.target, input.targetFraction ?? 0.5);
    return {
      points: compactPoints([start, orthogonalLead(start, sides.source, stub), orthogonalLead(end, sides.target, stub), end]),
      sourceSide: sides.source,
      targetSide: sides.target,
    };
  }
  return { points: winner.points, sourceSide: winner.sourceSide, targetSide: winner.targetSide };
}

function compareOrthogonalScores(
  a: { hits: number; bends: number; length: number },
  b: { hits: number; bends: number; length: number },
): number {
  return a.hits - b.hits || a.bends - b.bends || a.length - b.length;
}

function facingSideCandidates(
  source: OrthogonalRect,
  target: OrthogonalRect,
): Array<{ source: OrthogonalSide; target: OrthogonalSide }> {
  const primary = facingOrthogonalSides(source, target);
  const dx = centerX(target) - centerX(source);
  const dy = centerY(target) - centerY(source);
  const secondary = primary.source === "left" || primary.source === "right"
    ? (dy >= 0 ? { source: "bottom" as const, target: "top" as const } : { source: "top" as const, target: "bottom" as const })
    : (dx >= 0 ? { source: "right" as const, target: "left" as const } : { source: "left" as const, target: "right" as const });
  return secondary.source === primary.source ? [primary] : [primary, secondary];
}

export function longestStrokeLabelAnchor(points: readonly WorkflowLayoutPoint[]): WorkflowLayoutPoint | null {
  let best: { start: WorkflowLayoutPoint; end: WorkflowLayoutPoint; length: number } | null = null;
  for (let i = 0; i + 1 < points.length; i += 1) {
    const start = points[i]!;
    const end = points[i + 1]!;
    const length = Math.abs(end.x - start.x) + Math.abs(end.y - start.y);
    if (!best || length > best.length) {
      best = { start, end, length };
    }
  }
  if (!best) return null;
  return {
    x: (best.start.x + best.end.x) / 2,
    y: (best.start.y + best.end.y) / 2,
  };
}

export function longestStrokeIsVertical(points: readonly WorkflowLayoutPoint[]): boolean {
  let bestVertical = false;
  let bestLength = -1;
  for (let i = 0; i + 1 < points.length; i += 1) {
    const start = points[i]!;
    const end = points[i + 1]!;
    const length = Math.abs(end.x - start.x) + Math.abs(end.y - start.y);
    if (length > bestLength) {
      bestLength = length;
      bestVertical = Math.abs(end.x - start.x) < 1e-3;
    }
  }
  return bestVertical;
}

function simpleConnectorBodies(
  sourceLead: WorkflowLayoutPoint,
  targetLead: WorkflowLayoutPoint,
): WorkflowLayoutPoint[][] {
  const bodies: WorkflowLayoutPoint[][] = [
    [sourceLead, { x: sourceLead.x, y: targetLead.y }, targetLead],
    [sourceLead, { x: targetLead.x, y: sourceLead.y }, targetLead],
  ];
  if (almostEqual(sourceLead.x, targetLead.x) || almostEqual(sourceLead.y, targetLead.y)) {
    return bodies;
  }
  const midX = sourceLead.x + (targetLead.x - sourceLead.x) / 2;
  const midY = sourceLead.y + (targetLead.y - sourceLead.y) / 2;
  bodies.push(
    [sourceLead, { x: midX, y: sourceLead.y }, { x: midX, y: targetLead.y }, targetLead],
    [sourceLead, { x: sourceLead.x, y: midY }, { x: targetLead.x, y: midY }, targetLead],
  );
  return bodies;
}

function detourConnectorBodies(
  sourceLead: WorkflowLayoutPoint,
  targetLead: WorkflowLayoutPoint,
  source: OrthogonalRect,
  target: OrthogonalRect,
  stub: number,
  padding: number,
  obstacles: readonly OrthogonalRect[],
): WorkflowLayoutPoint[][] {
  const hull = inflate(boundsBetween(source, target), padding + stub);
  const candidates: WorkflowLayoutPoint[][] = [
    [sourceLead, { x: sourceLead.x, y: hull.y }, { x: targetLead.x, y: hull.y }, targetLead],
    [sourceLead, { x: sourceLead.x, y: hull.y + hull.height }, { x: targetLead.x, y: hull.y + hull.height }, targetLead],
    [sourceLead, { x: hull.x, y: sourceLead.y }, { x: hull.x, y: targetLead.y }, targetLead],
    [sourceLead, { x: hull.x + hull.width, y: sourceLead.y }, { x: hull.x + hull.width, y: targetLead.y }, targetLead],
  ];
  for (const blocker of obstacles) {
    if (!rectsOverlap(hull, inflate(blocker, padding))) continue;
    const padded = inflate(blocker, padding + stub);
    const laneTop = padded.y;
    const laneBottom = padded.y + padded.height;
    const laneLeft = padded.x;
    const laneRight = padded.x + padded.width;
    candidates.push(
      [sourceLead, { x: sourceLead.x, y: laneTop }, { x: laneLeft, y: laneTop }, { x: laneLeft, y: targetLead.y }, targetLead],
      [sourceLead, { x: sourceLead.x, y: laneTop }, { x: laneRight, y: laneTop }, { x: laneRight, y: targetLead.y }, targetLead],
      [sourceLead, { x: sourceLead.x, y: laneBottom }, { x: laneLeft, y: laneBottom }, { x: laneLeft, y: targetLead.y }, targetLead],
      [sourceLead, { x: sourceLead.x, y: laneBottom }, { x: laneRight, y: laneBottom }, { x: laneRight, y: targetLead.y }, targetLead],
      [sourceLead, { x: laneLeft, y: sourceLead.y }, { x: laneLeft, y: laneTop }, { x: targetLead.x, y: laneTop }, targetLead],
      [sourceLead, { x: laneRight, y: sourceLead.y }, { x: laneRight, y: laneTop }, { x: targetLead.x, y: laneTop }, targetLead],
      [sourceLead, { x: laneLeft, y: sourceLead.y }, { x: laneLeft, y: laneBottom }, { x: targetLead.x, y: laneBottom }, targetLead],
      [sourceLead, { x: laneRight, y: sourceLead.y }, { x: laneRight, y: laneBottom }, { x: targetLead.x, y: laneBottom }, targetLead],
    );
  }
  return candidates;
}

function segmentCrossesRect(
  a: WorkflowLayoutPoint,
  b: WorkflowLayoutPoint,
  rect: OrthogonalRect,
  padding: number,
): boolean {
  const r = inflate(rect, padding);
  const minX = Math.min(a.x, b.x);
  const maxX = Math.max(a.x, b.x);
  const minY = Math.min(a.y, b.y);
  const maxY = Math.max(a.y, b.y);
  // Strict interior: a graze along the padded border is not a crossing.
  return maxX > r.x && minX < r.x + r.width && maxY > r.y && minY < r.y + r.height;
}

function countObstacleHits(
  points: readonly WorkflowLayoutPoint[],
  obstacles: readonly OrthogonalRect[],
  padding: number,
  source: OrthogonalRect,
  target: OrthogonalRect,
): number {
  let hits = 0;
  for (let i = 0; i + 1 < points.length; i += 1) {
    const a = points[i]!;
    const b = points[i + 1]!;
    for (const obstacle of obstacles) {
      if (sameRect(obstacle, source) || sameRect(obstacle, target)) continue;
      if (segmentCrossesRect(a, b, obstacle, padding)) hits += 1;
    }
  }
  return hits;
}

function compactPoints(points: readonly WorkflowLayoutPoint[]): WorkflowLayoutPoint[] {
  const compacted: WorkflowLayoutPoint[] = [];
  for (const point of points) {
    const previous = compacted[compacted.length - 1];
    if (previous && almostEqual(previous.x, point.x) && almostEqual(previous.y, point.y)) continue;
    const older = compacted[compacted.length - 2];
    if (
      previous
      && older
      && ((almostEqual(older.x, previous.x) && almostEqual(previous.x, point.x))
        || (almostEqual(older.y, previous.y) && almostEqual(previous.y, point.y)))
    ) {
      compacted[compacted.length - 1] = point;
      continue;
    }
    compacted.push(point);
  }
  return compacted;
}

function polylineLength(points: readonly WorkflowLayoutPoint[]): number {
  let length = 0;
  for (let i = 0; i + 1 < points.length; i += 1) {
    length += Math.abs(points[i + 1]!.x - points[i]!.x) + Math.abs(points[i + 1]!.y - points[i]!.y);
  }
  return length;
}

function boundsBetween(a: OrthogonalRect, b: OrthogonalRect): OrthogonalRect {
  const x = Math.min(a.x, b.x);
  const y = Math.min(a.y, b.y);
  const right = Math.max(a.x + a.width, b.x + b.width);
  const bottom = Math.max(a.y + a.height, b.y + b.height);
  return { x, y, width: right - x, height: bottom - y };
}

function inflate(rect: OrthogonalRect, pad: number): OrthogonalRect {
  return { x: rect.x - pad, y: rect.y - pad, width: rect.width + pad * 2, height: rect.height + pad * 2 };
}

function rectsOverlap(a: OrthogonalRect, b: OrthogonalRect): boolean {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
}

function sameRect(a: OrthogonalRect, b: OrthogonalRect): boolean {
  return a.x === b.x && a.y === b.y && a.width === b.width && a.height === b.height;
}

function rangesOverlap(a0: number, a1: number, b0: number, b1: number): boolean {
  return a0 < b1 && b0 < a1;
}

function centerX(rect: OrthogonalRect): number {
  return rect.x + rect.width / 2;
}

function centerY(rect: OrthogonalRect): number {
  return rect.y + rect.height / 2;
}

function almostEqual(a: number, b: number): boolean {
  return Math.abs(a - b) <= 1e-3;
}
