import { describe, expect, it } from "vitest";

import { isStageDrawerPanel, shouldApplyCanvasNodeSelection } from "./researchProcessPanelSelection";

describe("researchProcessPanelSelection", () => {
  it("does not let an empty canvas initialization replace a non-node panel", () => {
    expect(shouldApplyCanvasNodeSelection({ nodeId: null, panel: "agents" })).toBe(false);
    expect(shouldApplyCanvasNodeSelection({ nodeId: null, panel: "timeline" })).toBe(false);
  });

  it("keeps ordinary node selection and node-panel clearing intact", () => {
    expect(shouldApplyCanvasNodeSelection({ nodeId: "source_finding", panel: "agents" })).toBe(true);
    expect(shouldApplyCanvasNodeSelection({ nodeId: null, panel: "node" })).toBe(true);
  });

  it("classifies experiment and knowledge as stage drawer panels", () => {
    expect(isStageDrawerPanel("experiment")).toBe(true);
    expect(isStageDrawerPanel("knowledge")).toBe(true);
    expect(isStageDrawerPanel("node")).toBe(false);
    expect(isStageDrawerPanel("agents")).toBe(false);
    expect(isStageDrawerPanel("timeline")).toBe(false);
  });
});
