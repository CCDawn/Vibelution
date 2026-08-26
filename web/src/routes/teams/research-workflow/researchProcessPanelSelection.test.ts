import { describe, expect, it } from "vitest";

import {
  RESEARCH_PROCESS_INSPECTOR_CLOSED,
  resolveResearchProcessAutofocus,
  shouldApplyCanvasNodeSelection,
  shouldOpenResearchProcessInspector,
  shouldShowResearchProcessInspector,
} from "./researchProcessPanelSelection";

describe("researchProcessPanelSelection", () => {
  it("opens workflow inspector panels by default and honors an explicit close marker", () => {
    expect(shouldOpenResearchProcessInspector({ panel: "node", inspector: null })).toBe(true);
    expect(shouldOpenResearchProcessInspector({ panel: "team", inspector: undefined })).toBe(true);
    expect(shouldOpenResearchProcessInspector({
      panel: "node",
      inspector: RESEARCH_PROCESS_INSPECTOR_CLOSED,
    })).toBe(false);
    expect(shouldOpenResearchProcessInspector({ panel: "question", inspector: null })).toBe(false);
  });

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

  it("keeps the inspector column mounted so the canvas cannot swallow the right pane", () => {
    expect(shouldShowResearchProcessInspector({ panel: "node", selectedNodeId: null })).toBe(true);
    expect(shouldShowResearchProcessInspector({ panel: "node", selectedNodeId: "source_finding" })).toBe(true);
    expect(shouldShowResearchProcessInspector({
      panel: "node",
      selectedNodeId: null,
      nextTarget: "hf_generation",
    })).toBe(true);
    expect(shouldShowResearchProcessInspector({ panel: "launch", selectedNodeId: null })).toBe(true);
    expect(shouldShowResearchProcessInspector({ panel: "agents", selectedNodeId: null })).toBe(true);
  });
});

describe("resolveResearchProcessAutofocus", () => {
  it("opens the node inspector when panel=node and nothing is selected", () => {
    expect(resolveResearchProcessAutofocus({
      panel: "node",
      selectedNodeId: null,
      nextTarget: "hf_generation",
      previousNextTarget: null,
    })).toEqual({ node: "hf_generation", panel: "node" });
  });

  it("follows when the current-task target changes", () => {
    expect(resolveResearchProcessAutofocus({
      panel: "node",
      selectedNodeId: "hf_generation",
      nextTarget: "hf_selection",
      previousNextTarget: "hf_generation",
    })).toEqual({ node: "hf_selection", panel: "node" });
  });

  it("does not steal the inspector while the same task is current and the user selected another card", () => {
    expect(resolveResearchProcessAutofocus({
      panel: "node",
      selectedNodeId: "source_finding",
      nextTarget: "hf_generation",
      previousNextTarget: "hf_generation",
    })).toBeNull();
  });

  it("does not steal agents/team/timeline/progress/launch panels", () => {
    for (const panel of ["agents", "team", "timeline", "progress", "launch"] as const) {
      expect(resolveResearchProcessAutofocus({
        panel,
        selectedNodeId: null,
        nextTarget: "hf_generation",
        previousNextTarget: null,
      })).toBeNull();
    }
  });

  it("is a no-op when the URL already points at the current task", () => {
    expect(resolveResearchProcessAutofocus({
      panel: "node",
      selectedNodeId: "hf_generation",
      nextTarget: "hf_generation",
      previousNextTarget: null,
    })).toBeNull();
  });
});
