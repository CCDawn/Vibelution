import { describe, expect, it } from "vitest";

import {
  WORKBENCH_VISUAL_ACCEPTANCE_CHECKLIST,
  WORKBENCH_VISUAL_REVIEW_PROTOCOL,
  WORKBENCH_VISUAL_SCENARIOS,
  summarizeWorkbenchVisualCoverage,
} from "./workbenchVisualMatrix";

describe("Workbench visual regression matrix", () => {
  it("covers the Wave 0 theme, background, viewport, route, and state requirements", () => {
    const coverage = summarizeWorkbenchVisualCoverage(WORKBENCH_VISUAL_SCENARIOS);

    expect(coverage.themes).toEqual(["dark", "light"]);
    expect(coverage.backgrounds).toEqual(["custom", "default"]);
    expect(coverage.viewports).toEqual(["desktop", "narrow"]);
    expect(coverage.states).toEqual(["blocker", "dense", "destructive", "empty", "error"]);
    expect(coverage.paths).toEqual([
      "/",
      "/agents",
      "/chat",
      "/config",
      "/memory",
      "/memory/graph",
      "/supervised-evolution",
    ]);
  });

  it("keeps every scenario actionable for manual or automated screenshot capture", () => {
    expect(WORKBENCH_VISUAL_SCENARIOS).toHaveLength(12);

    for (const scenario of WORKBENCH_VISUAL_SCENARIOS) {
      expect(scenario.id).toMatch(/^[a-z0-9-]+$/);
      expect(scenario.path).toMatch(/^\//);
      expect(scenario.viewport.width).toBeGreaterThanOrEqual(390);
      expect(scenario.viewport.height).toBeGreaterThanOrEqual(720);
      expect(scenario.reviewFocus.length).toBeGreaterThanOrEqual(2);
      expect(scenario.expectedEvidence).toContain("screenshot");
    }
  });

  it("documents the quiet workbench visual acceptance checklist", () => {
    expect(WORKBENCH_VISUAL_ACCEPTANCE_CHECKLIST).toEqual([
      "background remains visible",
      "text remains readable",
      "1px thin-line borders",
      "quiet controls by default",
      "visible focus state",
      "clear destructive, error, and blocker states",
      "no card wall",
      "no full-page opaque route wrapper",
    ]);
  });

  it("documents how to collect visual evidence for the matrix", () => {
    expect(WORKBENCH_VISUAL_REVIEW_PROTOCOL).toEqual([
      "Start the app with: cd web && npm run dev -- --host 127.0.0.1",
      "For each scenario, open the path, set the stored theme to the scenario theme, and use a custom background when background is custom.",
      "Capture a screenshot or attach an observation note for every scenario id.",
      "Reject the wave if a screenshot shows a card wall, opaque route wrapper, unreadable text, invisible focus, or muted destructive/error/blocker state.",
    ]);
  });
});
