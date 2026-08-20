import { describe, expect, it } from "vitest";

import {
  assignSnapFractions,
  facingOrthogonalSides,
  longestStrokeIsVertical,
  portPointOnRect,
  projectedSnapFraction,
  routeOrthogonalConnector,
  snapSlotsForSide,
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

  it("uses a one-bend L when the neighbor is below-right and the corridor is empty", () => {
    const source = card(0, 0);
    const target = card(360, 160);
    const route = routeOrthogonalConnector({ source, target });
    expect(route.sourceSide).toBe("right");
    expect(route.targetSide).toBe("left");
    expect(route.points.length).toBeLessThanOrEqual(5);
    const xs = new Set(route.points.map((point) => Math.round(point.x)));
    expect(xs.size).toBeLessThanOrEqual(3);
  });

  it("keeps the simple L when another card sits in the hull but not on the elbow", () => {
    const source = card(0, 0);
    const target = card(400, 200);
    const spectator = card(330, 80);
    const route = routeOrthogonalConnector({
      source,
      target,
      obstacles: [spectator],
    });
    expect(route.points.length).toBeLessThanOrEqual(5);
    const maxX = Math.max(...route.points.map((point) => point.x));
    expect(maxX).toBeLessThan(spectator.x + spectator.width);
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

  it("snaps a single edge to the magnet facing the other card", () => {
    const source = card(0, 80);
    const lower = card(360, 200);
    const assigned = assignSnapFractions(
      [{ id: "e1", preferred: projectedSnapFraction(source, "right", lower) }],
      snapSlotsForSide("right"),
    );
    expect(assigned.get("e1")).toBe(0.75);
    expect(portPointOnRect(source, "right", 0.75).y).toBe(source.y + source.height * 0.75);
  });

  it("gives two same-side edges distinct magnets that follow the far cards", () => {
    const source = card(0, 80);
    const high = card(360, 0);
    const low = card(360, 180);
    const assigned = assignSnapFractions(
      [
        { id: "high", preferred: projectedSnapFraction(source, "right", high) },
        { id: "low", preferred: projectedSnapFraction(source, "right", low) },
      ],
      snapSlotsForSide("right"),
    );
    expect(assigned.get("high")).toBe(0.25);
    expect(assigned.get("low")).toBe(0.75);
    const highStart = portPointOnRect(source, "right", assigned.get("high"));
    const lowStart = portPointOnRect(source, "right", assigned.get("low"));
    expect(highStart.y).toBeLessThan(lowStart.y);
  });

  it("splits an incoming and outgoing claim that prefer the same slot", () => {
    const assigned = assignSnapFractions(
      [
        { id: "in", preferred: 0.5 },
        { id: "out", preferred: 0.5 },
      ],
      snapSlotsForSide("right"),
    );
    expect(assigned.get("in")).not.toBe(assigned.get("out"));
    expect(new Set(assigned.values()).size).toBe(2);
  });

  it("routes from the chosen magnet instead of the side midpoint", () => {
    const source = card(0, 80);
    const target = card(360, 200);
    const route = routeOrthogonalConnector({
      source,
      target,
      sourceSide: "right",
      targetSide: "left",
      sourceFraction: 0.75,
      targetFraction: 0.25,
    });
    expect(route.points[0]).toEqual(portPointOnRect(source, "right", 0.75));
    expect(route.points[route.points.length - 1]).toEqual(portPointOnRect(target, "left", 0.25));
  });
});
