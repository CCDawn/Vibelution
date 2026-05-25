import { describe, expect, it } from "vitest";

import source from "./PaneCollapseHandle.tsx?raw";

describe("PaneCollapseHandle", () => {
  it("renders a separator-owned centered toggle without starting resize drag", () => {
    expect(source).toContain('role="separator"');
    expect(source).toContain("stopHandleDrag");
    expect(source).toContain("event.stopPropagation()");
    expect(source).toContain("onToggle()");
  });

  it("switches labels and chevron direction for collapsed panes", () => {
    expect(source).toContain("const label = collapsed ? expandLabel : collapseLabel");
    expect(source).toContain('type PaneSide = "left" | "right"');
    expect(source).toContain('side === "left"');
    expect(source).toContain('collapsed ? "left" : "right"');
    expect(source).toContain("ChevronLeft");
    expect(source).toContain("ChevronRight");
    expect(source).toContain("aria-pressed={collapsed}");
  });
});
