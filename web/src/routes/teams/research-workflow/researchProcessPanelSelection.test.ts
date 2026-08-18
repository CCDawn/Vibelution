import { describe, expect, it } from "vitest";

import {
  shouldApplyCanvasNodeSelection,
  shouldShowResearchProcessInspector,
} from "./researchProcessPanelSelection";

describe("researchProcessPanelSelection", () => {
  it("does not let an empty canvas initialization replace a non-node panel", () => {
    expect(shouldApplyCanvasNodeSelection({ nodeId: null, panel: "agents" })).toBe(false);
    expect(shouldApplyCanvasNodeSelection({ nodeId: null, panel: "timeline" })).toBe(false);
  });

  it("keeps ordinary node selection and node-panel clearing intact", () => {
    expect(shouldApplyCanvasNodeSelection({ nodeId: "source_finding", panel: "agents" })).toBe(true);
    expect(shouldApplyCanvasNodeSelection({ nodeId: null, panel: "node" })).toBe(true);
  });

  it("keeps launch and evidence panels stable during canvas initialization", () => {
    expect(shouldApplyCanvasNodeSelection({ nodeId: null, panel: "launch" })).toBe(false);
    expect(shouldApplyCanvasNodeSelection({ nodeId: null, panel: "evidence" })).toBe(false);
  });

  it("hides the inspector column until a node is selected or a tool panel is open", () => {
    expect(shouldShowResearchProcessInspector({ panel: "node", selectedNodeId: null })).toBe(false);
    expect(shouldShowResearchProcessInspector({ panel: "node", selectedNodeId: "source_finding" })).toBe(true);
    expect(shouldShowResearchProcessInspector({ panel: "launch", selectedNodeId: null })).toBe(true);
    expect(shouldShowResearchProcessInspector({ panel: "agents", selectedNodeId: null })).toBe(true);
  });
});
