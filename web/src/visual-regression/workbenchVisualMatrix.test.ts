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
    expect(coverage.viewports).toEqual(["compact", "standard", "wide"]);
    expect(coverage.states).toEqual(["blocker", "dense", "destructive", "empty", "error"]);
    expect(coverage.paths).toEqual([
      "/",
      "/agents",
      "/chat",
      "/config",
      "/memory",
      "/memory/graph",
      "/memory/manage",
      "/supervised-evolution",
      "/teams",
    ]);
  });

  it("covers compact, standard, and wide desktop viewports without a mobile gate", () => {
    const coverage = summarizeWorkbenchVisualCoverage(WORKBENCH_VISUAL_SCENARIOS);

    expect(coverage.viewports).toEqual(["compact", "standard", "wide"]);
    expect(WORKBENCH_VISUAL_SCENARIOS.some(({ viewport }) => viewport.width === 1280 && viewport.height === 720)).toBe(true);
    expect(WORKBENCH_VISUAL_SCENARIOS.some(({ viewport }) => viewport.width === 1440 && viewport.height === 900)).toBe(true);
    expect(WORKBENCH_VISUAL_SCENARIOS.some(({ viewport }) => viewport.width === 1920 && viewport.height === 1080)).toBe(true);
    expect(WORKBENCH_VISUAL_SCENARIOS.every(({ viewport }) => viewport.width >= 1280)).toBe(true);
  });

  it("keeps every desktop scenario actionable for screenshot capture", () => {
    expect(WORKBENCH_VISUAL_SCENARIOS).toHaveLength(18);

    for (const scenario of WORKBENCH_VISUAL_SCENARIOS) {
      expect(scenario.id).toMatch(/^[a-z0-9-]+$/);
      expect(scenario.path).toMatch(/^\//);
      expect(scenario.viewport.width).toBeGreaterThanOrEqual(1280);
      expect(scenario.viewport.height).toBeGreaterThanOrEqual(720);
      expect(scenario.reviewFocus.length).toBeGreaterThanOrEqual(2);
      expect(scenario.expectedEvidence).toBe("screenshot");
    }
  });

  it("adds explicit light and dark Phase 2 management-route coverage", () => {
    const phase2Paths = ["/agents", "/teams", "/memory", "/memory/manage", "/memory/graph"];

    for (const path of phase2Paths) {
      const scenarios = WORKBENCH_VISUAL_SCENARIOS.filter((scenario) => scenario.path === path);
      expect(scenarios.length).toBeGreaterThan(0);
    }

    expect(WORKBENCH_VISUAL_SCENARIOS.filter(({ id }) => id.startsWith("agents-"))).toHaveLength(2);
    expect(WORKBENCH_VISUAL_SCENARIOS.filter(({ id }) => id.startsWith("teams-"))).toHaveLength(2);
    expect(WORKBENCH_VISUAL_SCENARIOS.filter(({ id }) => id.startsWith("memory-"))).toHaveLength(6);
    expect(WORKBENCH_VISUAL_SCENARIOS).toHaveLength(18);
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
    expect(WORKBENCH_VISUAL_REVIEW_PROTOCOL[0]).toBe(
      "Start the app through Vibelution Launcher; use a scoped Vite dev server only when Launcher cannot render the task branch before integration.",
    );
  });
});
