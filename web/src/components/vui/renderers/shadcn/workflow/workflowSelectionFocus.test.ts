import { describe, expect, it } from "vitest";

import {
  resolveWorkflowNodeFocusCenter,
  shouldPanWorkflowSelectionIntoView,
  workflowEdgeTouchesNode,
} from "./workflowSelectionFocus";

describe("workflowEdgeTouchesNode", () => {
  it("matches incoming and outgoing ends only", () => {
    expect(workflowEdgeTouchesNode("protocol", "review", "protocol")).toBe(true);
    expect(workflowEdgeTouchesNode("protocol", "review", "review")).toBe(true);
    expect(workflowEdgeTouchesNode("protocol", "review", "design")).toBe(false);
    expect(workflowEdgeTouchesNode("protocol", "review", null)).toBe(false);
    expect(workflowEdgeTouchesNode("protocol", "review", "")).toBe(false);
  });
});

describe("shouldPanWorkflowSelectionIntoView", () => {
  const ready = {
    selectedNodeId: "protocol",
    canvasOriginNodeId: null as string | null,
    lastPannedNodeId: null as string | null,
    pendingInitialFit: false,
    nodesInitialized: true,
  };

  it("pans an external selection after the initial fit has settled", () => {
    expect(shouldPanWorkflowSelectionIntoView(ready)).toBe(true);
  });

  it("skips a card the user clicked on the canvas", () => {
    expect(shouldPanWorkflowSelectionIntoView({
      ...ready,
      canvasOriginNodeId: "protocol",
    })).toBe(false);
  });

  it("skips until React Flow has initialized nodes and the first fit is done", () => {
    expect(shouldPanWorkflowSelectionIntoView({ ...ready, pendingInitialFit: true })).toBe(false);
    expect(shouldPanWorkflowSelectionIntoView({ ...ready, nodesInitialized: false })).toBe(false);
  });

  it("does not pan the same card twice", () => {
    expect(shouldPanWorkflowSelectionIntoView({
      ...ready,
      lastPannedNodeId: "protocol",
    })).toBe(false);
  });
});

describe("resolveWorkflowNodeFocusCenter", () => {
  it("uses the card box, then adds a parent stage offset", () => {
    const node = {
      position: { x: 40, y: 80 },
      width: 300,
      height: 72,
      parentId: "stage:experiment",
    };
    const parent = { position: { x: 10, y: 20 } };
    expect(resolveWorkflowNodeFocusCenter(node, (id) => (id === "stage:experiment" ? parent : undefined))).toEqual({
      x: 200,
      y: 136,
    });
  });

  it("reads width and height from style when the RF node has no numeric size", () => {
    expect(resolveWorkflowNodeFocusCenter(
      { position: { x: 40, y: 80 }, style: { width: 300, height: 72 } },
      () => undefined,
    )).toEqual({ x: 190, y: 116 });
  });
});
