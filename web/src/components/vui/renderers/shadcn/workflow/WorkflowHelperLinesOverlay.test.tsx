/**
 * Helper-line overlay must live inside the React Flow viewport portal.
 * A full-pane sibling with z-index 5 covers `.react-flow__renderer` (z-index 4)
 * and hides every card behind the workspace background.
 */
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("@xyflow/react", () => ({
  useViewport: () => ({ x: 10, y: 20, zoom: 1 }),
  ViewportPortal: ({ children }: { children: React.ReactNode }) =>
    React.createElement("div", { "data-viewport-portal": "true" }, children),
}));

import { WorkflowHelperLinesOverlay } from "./WorkflowHelperLinesOverlay";

describe("WorkflowHelperLinesOverlay", () => {
  it("paints flow-space guides inside ViewportPortal instead of covering the renderer", () => {
    const markup = renderToStaticMarkup(
      <WorkflowHelperLinesOverlay lines={{ vertical: 100, horizontal: 40 }} />,
    );
    expect(markup).toContain('data-viewport-portal="true"');
    expect(markup).toContain('data-vui="workflow-helper-lines"');
    expect(markup).toContain('x1="100"');
    expect(markup).toContain('y1="40"');
    expect(markup).not.toContain("z-[5]");
    expect(markup).not.toContain("inset-0");
  });

  it("renders nothing when no guide is active", () => {
    expect(renderToStaticMarkup(<WorkflowHelperLinesOverlay lines={null} />)).toBe("");
    expect(renderToStaticMarkup(<WorkflowHelperLinesOverlay lines={{}} />)).toBe("");
  });
});
