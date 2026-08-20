import { describe, expect, it } from "vitest";

import {
  facingOrthogonalSides,
  longestStrokeIsVertical,
  portPointOnRect,
  routeOrthogonalConnector,
  sameSideHandleOffset,
} from "./workflowOrthogonalRoute";

const card = (x: number, y: number): { x: number; y: number; width: number; height: number } => ({
  x,
  y,
  width: 300,
  height: 72,
});

describe("workflowOrthogonalRoute", () => {
  it("uses facing east-west sides for horizontally adjacent cards", () => {
    expect(facingOrthogonalSides(card(0, 80), card(360, 80))).toEqual({
      source: "right",
      target: "left",
    });
    expect(facingOrthogonalSides(card(360, 80), card(0, 88))).toEqual({
      source: "left",
      target: "right",
    });
  });

  it("uses facing north-south sides only when the cards share a column", () => {
    expect(facingOrthogonalSides(card(40, 0), card(60, 200))).toEqual({
      source: "bottom",
      target: "top",
    });
  });

  it("keeps a slight horizontal bias when the neighbor is only a little lower", () => {
    expect(facingOrthogonalSides(card(0, 0), card(360, 40))).toEqual({
      source: "right",
      target: "left",
    });
  });

  it("routes a short orthogonal bridge instead of a south-north detour", () => {
    const source = card(0, 80);
    const target = card(360, 80);
    const route = routeOrthogonalConnector({ source, target });
    expect(route.sourceSide).toBe("right");
    expect(route.targetSide).toBe("left");
    expect(route.points[0]).toEqual(portPointOnRect(source, "right"));
    expect(route.points[route.points.length - 1]).toEqual(portPointOnRect(target, "left"));
    const minY = Math.min(...route.points.map((point) => point.y));
    const maxY = Math.max(...route.points.map((point) => point.y));
    expect(maxY - minY).toBeLessThan(source.height);
    expect(longestStrokeIsVertical(route.points)).toBe(false);
  });

  it("goes around a blocking card instead of cutting through it", () => {
    const source = card(0, 0);
    const target = card(80, 240);
    const blocker = card(40, 100);
    const route = routeOrthogonalConnector({
      source,
      target,
      obstacles: [blocker],
    });
    const hits = route.points.some((point, index) => {
      const next = route.points[index + 1];
      if (!next) return false;
      const minX = Math.min(point.x, next.x);
      const maxX = Math.max(point.x, next.x);
      const minY = Math.min(point.y, next.y);
      const maxY = Math.max(point.y, next.y);
      return maxX > blocker.x + 8
        && minX < blocker.x + blocker.width - 8
        && maxY > blocker.y + 8
        && minY < blocker.y + blocker.height - 8;
    });
    expect(hits).toBe(false);
  });

  it("drops a blocked east-west run instead of cutting the next card", () => {
    const source = card(0, 0);
    const neighbor = card(320, 0);
    const target = card(640, 200);
    const route = routeOrthogonalConnector({
      source,
      target,
      obstacles: [neighbor],
    });
    const hits = route.points.some((point, index) => {
      const next = route.points[index + 1];
      if (!next) return false;
      const minX = Math.min(point.x, next.x);
      const maxX = Math.max(point.x, next.x);
      const minY = Math.min(point.y, next.y);
      const maxY = Math.max(point.y, next.y);
      return maxX > neighbor.x + 8
        && minX < neighbor.x + neighbor.width - 8
        && maxY > neighbor.y + 8
        && minY < neighbor.y + neighbor.height - 8;
    });
    expect(hits).toBe(false);
  });

  it("spreads same-side handles around the center", () => {
    expect(sameSideHandleOffset(0, 1)).toBe(0);
    expect(sameSideHandleOffset(0, 2)).toBe(-8);
    expect(sameSideHandleOffset(1, 2)).toBe(8);
  });
});
