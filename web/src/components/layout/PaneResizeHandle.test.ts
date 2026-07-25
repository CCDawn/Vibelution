import { describe, expect, it } from "vitest";

import source from "./PaneResizeHandle.tsx?raw";
import stylesSource from "./PaneResizeHandle.styles.ts?raw";

describe("PaneResizeHandle", () => {
  it("exposes the shared resize aria and data contract", () => {
    expect(source).toContain('role="separator"');
    expect(source).toContain('data-vui-layout-handle="resize"');
    expect(source).toContain("aria-valuenow");
    expect(source).toContain("aria-valuemin");
    expect(source).toContain("aria-valuemax");
    expect(source).toContain("collapsed");
  });

  it("keeps a wide hit target with a hover-lit 1px rule", () => {
    expect(stylesSource).toContain("cursor-col-resize");
    expect(stylesSource).toContain("after:w-3");
    expect(stylesSource).toContain("before:w-px");
    expect(stylesSource).toContain("hover:before:opacity-100");
    expect(stylesSource).toContain("handleActive");
  });
});
