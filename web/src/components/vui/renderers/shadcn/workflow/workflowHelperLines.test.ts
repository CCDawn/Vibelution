import { describe, expect, it } from "vitest";

import {
  WORKFLOW_HELPER_LINE_THRESHOLD,
  resolveWorkflowManualCardDrag,
  snapWorkflowNodeToHelpers,
  workflowHelperLineToScreen,
  workflowHelperLinesActive,
} from "./workflowHelperLines";

const card = { width: 300, height: 72 };

describe("workflowHelperLines", () => {
  it("snaps a dragged left edge to a neighbor left edge", () => {
    const result = snapWorkflowNodeToHelpers({
      position: { x: 104, y: 200 },
      ...card,
      others: [{ x: 100, y: 40, ...card }],
    });
    expect(result.position.x).toBe(100);
    expect(result.lines.vertical).toBe(100);
  });

  it("snaps horizontal centers even when they are off the 16px grid", () => {
    const result = snapWorkflowNodeToHelpers({
      position: { x: -46, y: 10 },
      width: 300,
      height: 72,
      others: [{ x: 0, y: 200, width: 200, height: 72 }],
    });
    expect(result.position.x).toBe(-50);
    expect(result.lines.vertical).toBe(100);
  });

  it("snaps a dragged left edge onto a neighbor right edge", () => {
    const neighbor = { x: 16, y: 40, ...card };
    const result = snapWorkflowNodeToHelpers({
      position: { x: 312, y: 80 },
      ...card,
      others: [neighbor],
    });
    expect(result.position.x).toBe(316);
    expect(result.lines.vertical).toBe(316);
  });

  it("snaps both axes independently", () => {
    const result = snapWorkflowNodeToHelpers({
      position: { x: 103, y: 44 },
      ...card,
      others: [{ x: 100, y: 40, width: 180, height: 72 }],
    });
    expect(result.position).toEqual({ x: 100, y: 40 });
    expect(result.lines).toEqual({ vertical: 100, horizontal: 40 });
  });

  it("does not snap when every edge and center is outside the threshold", () => {
    const result = snapWorkflowNodeToHelpers({
      position: { x: 40, y: 40 },
      ...card,
      others: [{ x: 200, y: 200, ...card }],
    });
    expect(result.position).toEqual({ x: 40, y: 40 });
    expect(result.lines).toEqual({});
    expect(workflowHelperLinesActive(result.lines)).toBe(false);
  });

  it("snaps at the threshold and ignores the next pixel", () => {
    const inside = snapWorkflowNodeToHelpers({
      position: { x: 100 + WORKFLOW_HELPER_LINE_THRESHOLD, y: 80 },
      ...card,
      others: [{ x: 100, y: 200, ...card }],
    });
    const outside = snapWorkflowNodeToHelpers({
      position: { x: 100 + WORKFLOW_HELPER_LINE_THRESHOLD + 1, y: 80 },
      ...card,
      others: [{ x: 100, y: 200, ...card }],
    });
    expect(inside.position.x).toBe(100);
    expect(outside.position.x).toBe(109);
    expect(outside.lines.vertical).toBeUndefined();
  });

  it("prefers the closer of two neighboring alignments", () => {
    const result = snapWorkflowNodeToHelpers({
      position: { x: 103, y: 20 },
      ...card,
      others: [
        { x: 100, y: 0, ...card },
        { x: 108, y: 400, ...card },
      ],
    });
    expect(result.position.x).toBe(100);
    expect(result.lines.vertical).toBe(100);
  });

  it("keeps helper snap on one axis and 16px grid on the other", () => {
    const result = resolveWorkflowManualCardDrag({
      position: { x: 103, y: 41 },
      ...card,
      others: [{ x: 100, y: 400, ...card }],
    });
    expect(result.position).toEqual({ x: 100, y: 48 });
    expect(result.lines).toEqual({ vertical: 100 });
  });

  it("falls back to the 16px grid when nothing aligns", () => {
    const result = resolveWorkflowManualCardDrag({
      position: { x: 39, y: 57 },
      ...card,
      others: [{ x: 400, y: 400, ...card }],
    });
    expect(result.position).toEqual({ x: 32, y: 64 });
    expect(result.lines).toEqual({});
  });

  it("maps a flow-space guide into screen space with the viewport transform", () => {
    expect(workflowHelperLineToScreen(100, 12, 0.5)).toBe(62);
  });
});
