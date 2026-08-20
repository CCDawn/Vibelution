import { describe, expect, it } from "vitest";

import {
  applyWorkflowEdgeAnchorsToPortSides,
  parseWorkflowSnapHandle,
  resolveWorkflowEdgeAnchorPatch,
  workflowReconnectKeepsEndpoints,
  workflowSnapHandleId,
} from "./workflowEdgeAnchors";

describe("workflowEdgeAnchors", () => {
  it("parses snap handle ids back into a side and fraction", () => {
    expect(parseWorkflowSnapHandle(workflowSnapHandleId("SOUTH", 0.75))).toEqual({
      side: "SOUTH",
      fraction: 0.75,
    });
    expect(parseWorkflowSnapHandle("out:east:one")).toBeNull();
  });

  it("rejects reconnects that would change source or target node ids", () => {
    expect(workflowReconnectKeepsEndpoints(
      { source: "protocol", target: "review" },
      { source: "protocol", target: "review", sourceHandle: null, targetHandle: "workflow-snap:WEST:0.2500" },
    )).toBe(true);
    expect(workflowReconnectKeepsEndpoints(
      { source: "protocol", target: "review" },
      { source: "protocol", target: "design", sourceHandle: null, targetHandle: "workflow-snap:WEST:0.2500" },
    )).toBe(false);
  });

  it("turns a same-node snap drop into a visual anchor patch", () => {
    expect(resolveWorkflowEdgeAnchorPatch({
      handleType: "target",
      connection: {
        source: "protocol",
        target: "review",
        sourceHandle: "out:east",
        targetHandle: workflowSnapHandleId("SOUTH", 0.5),
      },
    })).toEqual({ targetSide: "SOUTH", targetFraction: 0.5 });
  });

  it("overlays local anchors onto the already assigned handle without renaming it", () => {
    const portSides = applyWorkflowEdgeAnchorsToPortSides(
      "review",
      {
        source: {},
        target: { "in:west": "WEST" },
        targetAnchor: { "in:west": 0.5 },
      },
      [{
        id: "protocol->review",
        source: "protocol",
        target: "review",
        sourceHandle: "out:east",
        targetHandle: "in:west",
      }],
      {
        "protocol->review": { targetSide: "SOUTH", targetFraction: 0.75 },
      },
    );
    expect(portSides).toEqual({
      source: {},
      target: { "in:west": "SOUTH" },
      sourceAnchor: {},
      targetAnchor: { "in:west": 0.75 },
    });
  });
});
