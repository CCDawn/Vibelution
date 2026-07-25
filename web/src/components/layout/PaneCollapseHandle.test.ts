import { describe, expect, it } from "vitest";

import source from "./PaneCollapseHandle.tsx?raw";
import stylesSource from "./PaneCollapseHandle.styles.ts?raw";
import resizeStylesSource from "./PaneResizeHandle.styles.ts?raw";

describe("PaneCollapseHandle", () => {
  it("renders a separator-owned centered toggle without starting resize drag", () => {
    expect(source).toContain('role="separator"');
    expect(source).not.toContain("title={separatorLabel}");
    expect(source).toContain("stopHandleDrag");
    expect(source).toContain("event.stopPropagation()");
    expect(source).toContain("onToggle()");
    expect(source).toContain('data-vui-layout-handle="collapse-resize"');
  });

  it("switches labels and chevron direction for collapsed panes", () => {
    expect(source).toContain("const label = collapsed ? expandLabel : collapseLabel");
    expect(source).toContain('export type PaneSide = "left" | "right"');
    expect(source).toContain('side === "left"');
    expect(source).toContain('collapsed ? "left" : "right"');
    expect(source).toContain("ChevronLeft");
    expect(source).toContain("ChevronRight");
    expect(source).toContain("aria-pressed={collapsed}");
    expect(source).toContain('const tooltip = `${separatorLabel} · ${label}`');
    expect(source).toContain("tooltip={tooltip}");
  });

  it("composes the shared PaneResizeHandle visual contract", () => {
    expect(source).toContain("paneResizeHandleStyles.handle");
    expect(source).toContain("paneResizeHandleStyles.handleActive");
    expect(source).toContain("paneResizeHandleStyles.handleCollapsed");
    expect(source).toContain("aria-valuenow");
    expect(resizeStylesSource).toContain("cursor-col-resize");
    expect(resizeStylesSource).toContain("hover:before:opacity-100");
  });

  it("keeps the collapse toggle large enough to target reliably", () => {
    expect(stylesSource).toContain("!h-7 !w-7 !max-w-none");
    expect(stylesSource).not.toContain("!w-3.5");
  });
});
